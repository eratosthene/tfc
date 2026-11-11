"""``flask import-tfwiki``: review-before-save import from tfwiki.net."""

import os

import click

from app import app, tfwiki


def _cache_dir():
    return app.config.get(
        "TFWIKI_CACHE_DIR", os.path.join(app.root_path, os.pardir, "tfwiki-cache")
    )


@app.cli.command("import-tfwiki")
@click.argument("page")
@click.option("--dry-run", is_flag=True, help="Show the diff only; save nothing.")
@click.option("--yes", is_flag=True, help="Save every importable figure unasked.")
@click.option(
    "--ignore-robots",
    is_flag=True,
    help="Fetch although robots.txt disallows it (or set TFWIKI_IGNORE_ROBOTS).",
)
@click.option("--franchise", help="Franchise name, instead of the toyline heading.")
@click.option("--faction", help="Faction name, when the page does not say one side.")
@click.option("--refresh", is_flag=True, help="Fetch again, ignoring the cache.")
def import_tfwiki(page, dry_run, yes, ignore_robots, franchise, faction, refresh):
    """Import the figures on one tfwiki.net PAGE (``Name`` or ``Name#Section``).

    Each figure is shown as a diff and saved only when confirmed. A figure that
    is already in the collection is skipped, never changed.
    """
    title_in, _, fragment = page.partition("#")
    ignore = ignore_robots or app.config.get("TFWIKI_IGNORE_ROBOTS", False)
    if ignore:
        click.echo("Ignoring robots.txt, as you asked; fetching slowly.", err=True)
    fetcher = tfwiki.Fetcher(_cache_dir(), ignore_robots=bool(ignore))
    try:
        title, text = fetcher.wikitext(title_in, refresh=refresh)
    except tfwiki.FetchError as exc:
        raise click.ClickException(str(exc))
    sections = tfwiki.split_page(title, text, fragment or None)
    if not sections:
        raise click.ClickException(f"No figure found on {page}")
    saved = 0
    for section in sections:
        if franchise:
            section["fields"]["franchise"] = [franchise]
        if faction:
            section["fields"]["faction"] = faction
        plan = tfwiki.plan_import(title, section)
        click.echo(tfwiki.format_diff(plan))
        if plan["existing"] or plan["problems"] or dry_run:
            continue
        if yes or click.confirm("Save this figure?"):
            tfwiki.save_import(plan)
            saved += 1
    click.echo(f"Saved {saved} figure(s).")
