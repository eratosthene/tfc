"""``flask modernise-links``: point old-style figure links at the toys page.

Cache only unless --fetch is given; see app/tfwiki/modernise.py for the rules.
"""

import json
from collections import Counter, defaultdict

import click
from sqlalchemy import select, update

from app import app, db
from app.models import Character, Figure, FigureReference
from app.tfwiki import characters as character_pages
from app.tfwiki import modernise, parser
from app.tfwiki.fetcher import MIN_DELAY, RateLimited, fetcher_from_config


def build_fetcher(fetch, delay=None):
    """The app's fetcher, which only reads its cache unless ``fetch`` is set.
    ``delay`` (seconds between requests) overrides TFWIKI_DELAY."""
    fetcher = fetcher_from_config(
        app.config, **({} if delay is None else {"delay": delay})
    )
    fetcher.enabled = fetcher.enabled and fetch
    return fetcher


def used_links():
    """{link: [figures using it, references using it]} for the old-style ones."""
    counts = defaultdict(lambda: [0, 0])
    for (link,) in db.session.execute(
        select(Figure.link).where(Figure.link.isnot(None))
    ):
        if modernise.old_style(link):
            counts[link][0] += 1
    for (link,) in db.session.execute(select(FigureReference.link)):
        if modernise.old_style(link):
            counts[link][1] += 1
    return counts


def rewrite(model, old, new):
    """Change the rows whose link is exactly ``old``. (The database compares
    text without regard to case, so the match is made here.)"""
    rows = db.session.execute(select(model.id, model.link).where(model.link == old))
    ids = [row.id for row in rows if row.link == old]
    if ids:
        db.session.execute(update(model).where(model.id.in_(ids)).values(link=new))
    return len(ids)


@app.cli.command("modernise-links")
@click.option(
    "--fetch",
    is_flag=True,
    help="Fetch pages that are not cached (needs TFWIKI_ENABLED in config.py).",
)
@click.option(
    "--limit",
    default=50,
    show_default=True,
    help="Most pages to fetch in one run (with --fetch).",
)
@click.option(
    "--delay",
    type=float,
    default=None,
    metavar="SECONDS",
    help="Seconds between requests (default TFWIKI_DELAY, 2). Never less than 2.",
)
@click.option("--apply", "apply_", is_flag=True, help="Save the rewrites.")
@click.option("--json", "json_path", metavar="PATH", help="Also write the report.")
def modernise_links(fetch, limit, delay, apply_, json_path):
    """Rewrite figure links like Name_(G1)#Anchor to Name/toys#Anchor.

    A link is rewritten only when the toys page has that exact {{anchor}}.
    Everything else is left alone and listed with the reason. Without --apply
    nothing is saved. Without --fetch nothing is fetched: only pages already in
    the cache are used. With --fetch, pages are fetched one at a time, two
    seconds apart, and cached, so a second run costs nothing.
    """
    if fetch and not app.config.get("TFWIKI_ENABLED"):
        raise click.ClickException(
            "--fetch needs TFWIKI_ENABLED = True in config.py (see config.py.tpl)."
        )
    if delay is not None and delay < MIN_DELAY:
        click.echo(
            "A gap under %g seconds is not allowed; using %g." % (MIN_DELAY, MIN_DELAY)
        )
        delay = MIN_DELAY
    links = used_links()
    budget = modernise.Budget(build_fetcher(fetch, delay), limit)
    results = {}
    stopped = False
    for link in sorted(links):
        if stopped:
            results[link] = modernise.Result(modernise.LIMIT, "stopped", None)
            continue
        try:
            results[link] = modernise.check(budget, link)
        except RateLimited as error:
            stopped = True
            click.echo("tfwiki.net asked us to slow down; stopped. %s" % error)
            results[link] = modernise.Result(modernise.LIMIT, "stopped", None)
    tally = Counter(r.status for r in results.values())
    click.echo(
        "%d old-style links (%d figure links, %d references); pages fetched: %d"
        % (
            len(links),
            sum(c[0] for c in links.values()),
            sum(c[1] for c in links.values()),
            budget.used,
        )
    )
    for status, label in modernise.LABELS.items():
        if tally[status]:
            click.echo("  %5d  %s" % (tally[status], label))
    rewrites = [(link, r.new) for link, r in results.items() if r.new]
    if rewrites:
        click.echo("Rewrites:")
        for old, new in rewrites:
            figures, references = links[old]
            click.echo(
                "  %s\n    -> %s   [%d figures, %d references]"
                % (old, new, figures, references)
            )
    for status in modernise.LABELS:
        if status != modernise.REWRITE and tally[status]:
            click.echo("%s:" % modernise.LABELS[status])
            for link, result in results.items():
                if result.status == status:
                    click.echo("  %s" % link)
    if tally[modernise.NOT_CACHED] or tally[modernise.LIMIT]:
        click.echo(
            "Some pages are not in the cache. Set TFWIKI_ENABLED and run with "
            "--fetch to get them (about 2 seconds per page)."
        )
    if json_path:
        with open(json_path, "w") as f:
            json.dump(
                {
                    link: {
                        "status": r.status,
                        "detail": r.detail,
                        "new": r.new,
                        "figures": links[link][0],
                        "references": links[link][1],
                    }
                    for link, r in results.items()
                },
                f,
                indent=2,
            )
    if not rewrites:
        click.echo("Nothing to rewrite.")
    elif apply_:
        changed = [0, 0]
        for old, new in rewrites:
            changed[0] += rewrite(Figure, old, new)
            changed[1] += rewrite(FigureReference, old, new)
        db.session.commit()
        click.echo("Rewrote %d figure links and %d references." % tuple(changed))
    else:
        click.echo(
            "%d links would be rewritten. Run again with --apply." % len(rewrites)
        )


# --- flask modernise-characters ---------------------------------------------


def figure_pages(budget, links):
    """(the character pages a character's figures are on, statuses of figure links
    whose pages could not be read yet). An old-style link is resolved first, the
    way modernise-links does, so ``Battletrap#Power_of_the_Primes`` counts as
    being on ``Battletrap_(G1)``."""
    pages, missing = set(), set()
    for link in sorted(set(links)):
        try:
            parser.parse_url(link)
        except parser.ParseError:
            continue
        if modernise.old_style(link):
            result = modernise.check(budget, link)
            if result.status in (modernise.NOT_CACHED, modernise.LIMIT):
                missing.add(result.status)
                continue
            if result.new:
                link = result.new
            elif result.status != modernise.CURRENT:
                continue
        pages.add(
            parser.normalize_title(parser.character_page(parser.parse_url(link)[0]))
        )
    return pages, missing


def settle_conflicts(results, existing):
    """Turn a rewrite into a conflict if another character has (or is about to get)
    the new link. ``existing`` is {lower-case link: character id}; the database
    compares links without regard to case, so this does too."""
    claimed = {}
    for cid in sorted(results):
        result = results[cid]
        if result.status not in character_pages.REWRITES:
            continue
        key = result.new.lower()
        holder = existing.get(key, claimed.get(key))
        if holder is not None and holder != cid:
            results[cid] = modernise.Result(
                character_pages.CONFLICT,
                "character %s already has %s" % (holder, result.new),
                None,
            )
        else:
            claimed[key] = cid
    return results


@app.cli.command("modernise-characters")
@click.option(
    "--fetch",
    is_flag=True,
    help="Fetch pages that are not cached (needs TFWIKI_ENABLED in config.py).",
)
@click.option(
    "--limit",
    default=50,
    show_default=True,
    help="Most pages to fetch in one run (with --fetch).",
)
@click.option(
    "--delay",
    type=float,
    default=None,
    metavar="SECONDS",
    help="Seconds between requests (default TFWIKI_DELAY, 2). Never less than 2.",
)
@click.option("--apply", "apply_", is_flag=True, help="Save the rewrites.")
@click.option("--json", "json_path", metavar="PATH", help="Also write the report.")
def modernise_characters(fetch, limit, delay, apply_, json_path):
    """Point characters at their wiki page's current name.

    A page the wiki renamed (``Alpha_Trion_(G1)`` -> ``Alpha_Trion``) is rewritten to
    the current title. A name that is now a disambiguation page (``Battletrap``) is
    rewritten to the page it lists that the character's own figures are on, only if
    exactly one is. A link another character already has is never taken. Everything
    else is left alone and listed with the reason. Without --apply nothing is saved;
    without --fetch nothing is fetched (see ``modernise-links`` for the rules).
    """
    if fetch and not app.config.get("TFWIKI_ENABLED"):
        raise click.ClickException(
            "--fetch needs TFWIKI_ENABLED = True in config.py (see config.py.tpl)."
        )
    if delay is not None and delay < MIN_DELAY:
        click.echo(
            "A gap under %g seconds is not allowed; using %g." % (MIN_DELAY, MIN_DELAY)
        )
        delay = MIN_DELAY
    people = {
        c.id: c
        for c in db.session.scalars(select(Character).order_by(Character.id))
        if _is_wiki_link(c.link)
    }
    figure_links = defaultdict(list)
    for cid, link in db.session.execute(
        select(Figure.character_id_new, Figure.link).where(
            Figure.character_id_new.isnot(None), Figure.link.isnot(None)
        )
    ):
        figure_links[cid].append(link)
    budget = modernise.Budget(build_fetcher(fetch, delay), limit)
    results = {}
    stopped = False
    for cid, person in people.items():
        if stopped:
            results[cid] = modernise.Result(modernise.LIMIT, "stopped", None)
            continue
        try:
            results[cid] = character_pages.check(
                budget,
                person.link,
                lambda cid=cid: figure_pages(budget, figure_links[cid]),
            )
        except RateLimited as error:
            stopped = True
            click.echo("tfwiki.net asked us to slow down; stopped. %s" % error)
            results[cid] = modernise.Result(modernise.LIMIT, "stopped", None)
    existing = {c.link.lower(): c.id for c in db.session.scalars(select(Character))}
    settle_conflicts(results, existing)
    tally = Counter(r.status for r in results.values())
    click.echo(
        "%d characters with a wiki link; pages fetched: %d" % (len(people), budget.used)
    )
    for status, label in character_pages.LABELS.items():
        if tally[status]:
            click.echo("  %5d  %s" % (tally[status], label))
    rewrites = [(cid, r.new) for cid, r in results.items() if r.new]
    if rewrites:
        click.echo("Rewrites:")
        for cid, new in rewrites:
            click.echo(
                "  %s (character %d)\n    %s\n    -> %s   [%s; %d figures]"
                % (
                    people[cid].name,
                    cid,
                    people[cid].link,
                    new,
                    results[cid].status,
                    len(figure_links[cid]),
                )
            )
    for status in character_pages.LABELS:
        if status not in character_pages.REWRITES and status != character_pages.CURRENT:
            if tally[status]:
                click.echo("%s:" % character_pages.LABELS[status])
                for cid, result in results.items():
                    if result.status == status:
                        click.echo(
                            "  %s (character %d): %s"
                            % (people[cid].name, cid, result.detail)
                        )
    if tally[modernise.NOT_CACHED] or tally[modernise.LIMIT]:
        click.echo(
            "Some pages are not in the cache. Set TFWIKI_ENABLED and run with "
            "--fetch to get them (about 2 seconds per page)."
        )
    if json_path:
        with open(json_path, "w") as f:
            json.dump(
                {
                    str(cid): {
                        "name": people[cid].name,
                        "link": people[cid].link,
                        "status": r.status,
                        "detail": r.detail,
                        "new": r.new,
                        "figures": len(figure_links[cid]),
                    }
                    for cid, r in results.items()
                },
                f,
                indent=2,
            )
    if not rewrites:
        click.echo("Nothing to rewrite.")
    elif apply_:
        for cid, new in rewrites:
            db.session.execute(
                update(Character).where(Character.id == cid).values(link=new)
            )
        db.session.commit()
        click.echo("Rewrote %d character links." % len(rewrites))
    else:
        click.echo(
            "%d character links would be rewritten. Run again with --apply."
            % len(rewrites)
        )


def _is_wiki_link(link):
    try:
        parser.parse_url(link)
    except parser.ParseError:
        return False
    return True
