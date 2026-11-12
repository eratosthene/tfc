"""``flask set-continuity-names``: fill in continuities' full names from a file."""

import click
from sqlalchemy import select

from app import app, db
from app.models import Continuity


def parse_names(text):
    """([(line number, continuity name, full name)], [problems]) from lines of
    ``G1 = Generation 1``. Blank lines and ``#`` comments are skipped."""
    found = []
    problems = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name, equals, full = (part.strip() for part in line.partition("="))
        if not equals or not name or not full:
            problems.append("line %d: write it as  Name = Full name" % number)
        elif len(full) > 255:
            problems.append("line %d: the full name is too long" % number)
        else:
            found.append((number, name, full))
    return found, problems


@app.cli.command("set-continuity-names")
@click.argument("file", type=click.File("r"))
@click.option("--apply", "apply_", is_flag=True, help="Save (default: only list).")
@click.option(
    "--overwrite", is_flag=True, help="Also replace full names that are already set."
)
def set_continuity_names(file, apply_, overwrite):
    """Set continuities' full names from FILE (``G1 = Generation 1`` per line).

    Lists what it would change and saves nothing unless --apply is given. A
    continuity that already has a full name is left alone unless --overwrite. If
    anything in the file is wrong, nothing is saved.
    """
    entries, problems = parse_names(file.read())
    by_name = {c.name: c for c in db.session.scalars(select(Continuity))}
    seen = set()
    changes = []
    for number, name, full in entries:
        if name in seen:
            problems.append("line %d: %s is listed twice" % (number, name))
        seen.add(name)
        if name not in by_name:
            problems.append("line %d: no continuity is called %s" % (number, name))
            continue
        row = by_name[name]
        if row.full_name == full:
            continue
        if row.full_name and not overwrite:
            click.echo("%s: keeps %r (use --overwrite)" % (name, row.full_name))
        else:
            changes.append((row, full))
    if problems:
        click.echo("Nothing was changed. Problems:")
        for problem in problems:
            click.echo("  " + problem)
        raise SystemExit(1)
    for row, full in changes:
        click.echo("%s: %s" % (row.name, full))
    if not changes:
        click.echo("Nothing to change.")
    elif apply_:
        for row, full in changes:
            row.full_name = full
        db.session.commit()
        click.echo("Changed %d continuities." % len(changes))
    else:
        click.echo(
            "%d continuities would change. Run again with --apply." % len(changes)
        )
