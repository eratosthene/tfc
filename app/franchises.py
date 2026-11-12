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
from app.models import Figure, Franchise

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


class FigureFilterConverter(SQLAFilterConverter):
    def convert(self, col_name):
        if col_name == "franchise":
            return [FranchiseTreeFilter(col_name, self.datamodel)]
        return super().convert(col_name)


class FigureInterface(SQLAInterface):
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
