"""``flask modernise-links``: point old-style figure links at the toys page.

Cache only unless --fetch is given; see app/tfwiki/modernise.py for the rules.
"""

import json
from collections import Counter, defaultdict

import click
from sqlalchemy import select, update

from app import app, db
from app.models import Figure, FigureReference
from app.tfwiki import modernise
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
