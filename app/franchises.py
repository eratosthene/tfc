"""Franchises as a tree: a franchise may have one parent (Legacy United ->
Generations -> Transformers). See docs/proposals/data-model.md, "Nested franchises".

A figure is tagged with the lowest franchise that fits; the franchises above it
are worked out from the tree here, never stored on the figure.
"""

import click
from flask_appbuilder.models.sqla.filters import (
    FilterRelationManyToManyEqual,
    SQLAFilterConverter,
)
from flask_appbuilder.models.sqla.interface import SQLAInterface
from sqlalchemy import false, select

from app import app, db
from app.models import Figure, FigureReference, Franchise

# How many levels a tree may have (a franchise with no parent is level 1).
MAX_DEPTH = 8


def parent_map():
    """{franchise id: parent id or None} for every franchise, in one query."""
    return dict(db.session.execute(select(Franchise.id, Franchise.parent_id)).all())


def ancestor_ids(franchise_id, parents=None):
    """The ids above a franchise, nearest first. Stops if the data has a loop."""
    parents = parent_map() if parents is None else parents
    found = []
    current = parents.get(franchise_id)
    while current is not None and current not in found and current != franchise_id:
        found.append(current)
        current = parents.get(current)
    return found


def descendant_levels(franchise_id, parents=None):
    """The ids below a franchise, level by level: [[children], [grandchildren]...]."""
    parents = parent_map() if parents is None else parents
    levels = []
    seen = {franchise_id}
    frontier = {franchise_id}
    while frontier:
        frontier = {i for i, p in parents.items() if p in frontier and i not in seen}
        seen |= frontier
        if frontier:
            levels.append(sorted(frontier))
    return levels


def descendant_ids(franchise_id, parents=None):
    """A franchise and everything below it."""
    return [franchise_id] + [
        i for level in descendant_levels(franchise_id, parents) for i in level
    ]


def check_parent(franchise, parent):
    """Refuse a parent that would make a loop or a tree that is too deep.

    ``franchise`` may be new (no id yet). Raises ValueError with a message for
    the user.
    """
    if parent is None:
        return
    parents = parent_map()
    if franchise.id is not None:
        if parent.id == franchise.id or parent.id in descendant_ids(
            franchise.id, parents
        ):
            raise ValueError(
                "%s cannot go under %s: that would make it its own ancestor."
                % (franchise.name, parent.name)
            )
    below = len(descendant_levels(franchise.id, parents)) if franchise.id else 0
    depth = len(ancestor_ids(parent.id, parents)) + 2 + below
    if depth > MAX_DEPTH:
        raise ValueError(
            "%s under %s would make the tree %d levels deep; the limit is %d."
            % (franchise.name, parent.name, depth, MAX_DEPTH)
        )


def effective_franchises(figure):
    """The franchises a figure is tagged with, then the ones above them."""
    tagged = list(figure.franchise)
    seen = {f.id for f in tagged}
    by_id = {f.id: f for f in db.session.scalars(select(Franchise))}
    parents = {i: f.parent_id for i, f in by_id.items()}
    result = list(tagged)
    for franchise in tagged:
        for above in ancestor_ids(franchise.id, parents):
            if above not in seen:
                seen.add(above)
                result.append(by_id[above])
    return result


# --- the Figure list filter -------------------------------------------------


class FranchiseTreeFilter(FilterRelationManyToManyEqual):
    """ "Franchise is X" also finds the figures tagged with anything below X."""

    def apply_item(self, query, field, value_item):
        try:
            ids = descendant_ids(int(value_item))
        except ValueError:
            return query.filter(false())
        return query.filter(field.any(Franchise.id.in_(ids)))


class AncestorLinkFilter(FilterRelationManyToManyEqual):
    """ "Has ancestor" with the ancestor's wiki link as the value."""

    name = "Has ancestor (link)"
    arg_name = "ancestor_link"

    def apply_item(self, query, field, value_item):
        return query.filter(field.any(FigureReference.link == value_item))


class FigureFilterConverter(SQLAFilterConverter):
    def convert(self, col_name):
        if col_name == "franchise":
            return [FranchiseTreeFilter(col_name, self.datamodel)]
        if col_name == "ancestors":
            return [AncestorLinkFilter(col_name, self.datamodel)]
        return super().convert(col_name)


class NameSortedInterface(SQLAInterface):
    """Drop-downs and lists sort by name unless a view asks for another order.

    Flask-AppBuilder builds a related-field drop-down with an unsorted query, so
    the choices came out in the order they were created.
    """

    def query(self, filters=None, order_column="", order_direction="", *args, **kwargs):
        if not order_column and hasattr(self.obj, "name"):
            order_column, order_direction = "name", "asc"
        return super().query(filters, order_column, order_direction, *args, **kwargs)


class FigureInterface(NameSortedInterface):
    filter_converter_class = FigureFilterConverter


# --- flask prune-franchises -------------------------------------------------


def redundant_tags():
    """[(figure, franchise to drop, the tagged franchise below it)] for every
    figure tagged with a franchise and also with one of its descendants."""
    parents = parent_map()
    names = {f.id: f for f in db.session.scalars(select(Franchise))}
    found = []
    for figure in db.session.scalars(select(Figure).order_by(Figure.id)):
        tagged = {f.id for f in figure.franchise}
        for franchise in list(figure.franchise):
            below = [
                i for i in descendant_ids(franchise.id, parents)[1:] if i in tagged
            ]
            if below:
                found.append((figure, franchise, names[below[0]]))
    return found


@app.cli.command("prune-franchises")
@click.option(
    "--apply", "apply_", is_flag=True, help="Remove the tags (default: only list)."
)
def prune_franchises(apply_):
    """Remove a figure's franchise tag when a franchise below it is also on it.

    Lists what it would remove and changes nothing unless --apply is given. Never
    runs by itself; a figure that is tagged with a whole branch still shows the
    franchises above its lowest tags, so leaving the extra tags is harmless.
    """
    found = redundant_tags()
    for figure, franchise, below in found:
        click.echo(
            "%s (figure %s): drop %s, already covered by %s"
            % (figure.name, figure.id, franchise.name, below.name)
        )
    if not found:
        click.echo("Nothing to prune.")
    elif apply_:
        for figure, franchise, _below in found:
            figure.franchise.remove(franchise)
        db.session.commit()
        click.echo("Removed %d tags." % len(found))
    else:
        click.echo("%d tags would be removed. Run again with --apply." % len(found))


# --- flask set-franchise-parents --------------------------------------------


def parse_tree(text):
    """Read an indented list of franchise names.

    Two spaces of indent is one level down; blank lines and ``#`` comments are
    skipped. Returns ([(line number, name, parent name or None)], [problems]).
    """
    entries = []
    problems = []
    stack = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        spaces = len(line) - len(line.lstrip(" "))
        if line.lstrip(" ").startswith("\t") or spaces % 2:
            problems.append("line %d: indent with two spaces per level" % number)
            continue
        level = spaces // 2
        if level > len(stack):
            problems.append("line %d: indented more than one level" % number)
            continue
        del stack[level:]
        entries.append((number, line.strip(), stack[-1] if stack else None))
        stack.append(line.strip())
    return entries, problems


def plan_parents(entries):
    """Match the names to franchises. Returns ([(line, franchise, parent)], [problems]),
    listing only the franchises whose parent would change."""
    by_name = {}
    for row in db.session.scalars(select(Franchise).order_by(Franchise.id)):
        by_name.setdefault(row.name, []).append(row)
    problems = []
    seen = set()
    for number, name, _parent in entries:
        if name in seen:
            problems.append("line %d: %s is listed twice" % (number, name))
        seen.add(name)
        if name not in by_name:
            problems.append("line %d: no franchise is called %s" % (number, name))
        elif len(by_name[name]) > 1:
            problems.append(
                "line %d: %d franchises are called %s"
                % (number, len(by_name[name]), name)
            )
    if problems:
        return [], problems
    changes = []
    for number, name, parent_name in entries:
        row = by_name[name][0]
        parent = by_name[parent_name][0] if parent_name else None
        if row.parent_id != (parent.id if parent else None):
            changes.append((number, row, parent))
    return changes, problems


@app.cli.command("set-franchise-parents")
@click.argument("file", type=click.File("r"))
@click.option(
    "--apply", "apply_", is_flag=True, help="Save the changes (default: only list)."
)
def set_franchise_parents(file, apply_):
    """Set franchise parents from an indented list of names (FILE, or - for stdin).

    Each parent is checked like the form checks it (no loops, at most 8 levels).
    Lists the changes and saves nothing unless --apply is given; if anything is
    wrong, nothing is saved either way. Franchises not named in the file are left
    alone. See docs/proposals/franchise-hierarchy.txt.
    """
    entries, problems = parse_tree(file.read())
    changes = []
    if not problems:
        changes, problems = plan_parents(entries)
    for number, row, parent in changes:
        was = row.parent.name if row.parent else "none"
        try:
            check_parent(row, parent)
            row.parent = parent
            db.session.flush()
        except ValueError as error:
            problems.append("line %d: %s" % (number, error))
        click.echo(
            "%s: parent %s (was %s)"
            % (row.name, parent.name if parent else "none", was)
        )
    if problems:
        db.session.rollback()
        click.echo("Nothing was changed. Problems:")
        for problem in problems:
            click.echo("  " + problem)
        raise SystemExit(1)
    if not changes:
        click.echo("Nothing to change.")
    elif apply_:
        db.session.commit()
        click.echo("Changed %d franchises." % len(changes))
    else:
        db.session.rollback()
        click.echo("%d franchises would change. Run again with --apply." % len(changes))
