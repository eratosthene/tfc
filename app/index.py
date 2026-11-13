from collections import defaultdict

from flask_appbuilder import IndexView
from flask_appbuilder.views import expose
from sqlalchemy import func, select
from app import db
from app.franchises import descendant_ids, parent_map
from app.models import (
    Category,
    Character,
    Continuity,
    ContinuityFamily,
    Faction,
    Figure,
    Franchise,
    Tooling,
    figure_category,
    figure_franchise,
    figure_tooling,
)


def _by_assoc(model, table, key, order_by):
    # The association table's column that points at ``model``.
    right = [c for c in table.c if c.name != "figure_id" and c.name != "position"][0]
    rows = (
        db.session.query(model, func.count(table.c.figure_id))
        .outerjoin(table, right == model.id)
        .group_by(model.id)
        .order_by(*order_by)
        .all()
    )
    return [{key: obj, "total": total} for obj, total in rows]


def _by_franchise():
    """The franchise tree: top-level franchises, each with its ``children``.

    A franchise's total counts the figures tagged with it or anything below it.
    """
    parents = parent_map()
    tagged = defaultdict(set)
    for figure_id, franchise_id in db.session.execute(
        select(figure_franchise.c.figure_id, figure_franchise.c.franchise_id)
    ):
        tagged[franchise_id].add(figure_id)
    nodes = {}
    franchises = select(Franchise).order_by(Franchise.start_year, Franchise.id)
    for franchise in db.session.scalars(franchises):
        figures = set()
        for franchise_id in descendant_ids(franchise.id, parents):
            figures |= tagged[franchise_id]
        nodes[franchise.id] = {
            "franchise": franchise,
            "total": len(figures),
            "children": [],
        }
    roots = []
    for franchise_id, node in nodes.items():
        parent = nodes.get(parents[franchise_id])
        (parent["children"] if parent else roots).append(node)
    return roots


def _by_continuity():
    """Continuity families (each with its ``children``) and family-less continuities.

    A family's total counts each of its figures once, however many of its
    continuities they appear in.
    """
    by_continuity = defaultdict(set)
    for figure_id, continuity_id in db.session.execute(
        select(Figure.id, Character.continuity_id).join(
            Character, Figure.character_id_new == Character.id
        )
    ):
        by_continuity[continuity_id].add(figure_id)
    families = {}
    for family in db.session.scalars(select(ContinuityFamily)):
        families[family.id] = {
            "family": family,
            "figures": set(),
            "children": [],
        }
    roots = []
    for continuity in db.session.scalars(select(Continuity).order_by(Continuity.name)):
        figures = by_continuity[continuity.id]
        node = {"continuity": continuity, "total": len(figures), "children": []}
        family = families.get(continuity.family_id)
        if family:
            family["children"].append(node)
            family["figures"] |= figures
        else:
            roots.append(node)
    for family in families.values():
        family["total"] = len(family.pop("figures"))
        roots.append(family)
    roots.sort(key=lambda n: str((n.get("family") or n["continuity"]).name).lower())
    return roots


class MyIndexView(IndexView):
    index_template = "index.html"

    @expose("/")
    def index(self):
        self.update_redirect()
        num_figures = db.session.query(func.count(Figure.id)).scalar()
        by_franchise = _by_franchise()
        by_continuity = _by_continuity()
        by_faction = [
            {"faction": obj, "total": total}
            for obj, total in db.session.query(Faction, func.count(Figure.id))
            .outerjoin(Figure, Figure.faction_id == Faction.id)
            .group_by(Faction.id)
            .order_by(Faction.name)
            .all()
        ]
        by_tooling = _by_assoc(Tooling, figure_tooling, "tooling", [Tooling.name])
        by_category = _by_assoc(Category, figure_category, "category", [Category.name])
        return self.render_template(
            self.index_template,
            appbuilder=self.appbuilder,
            num_figures=num_figures,
            by_franchise=by_franchise,
            by_continuity=by_continuity,
            by_faction=by_faction,
            by_tooling=by_tooling,
            by_category=by_category,
        )
