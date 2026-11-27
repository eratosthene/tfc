from collections import defaultdict
from decimal import Decimal

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
    figure_gestalt,
    figure_tooling,
)


def _prices():
    """{figure id: (link, average, copies)} for figures with an ActionFigure411 average.

    The average is for the whole retail box, per copy. A figure with no
    quantity counts as one copy (as "Figures owned" does on the Characters list).
    """
    return {
        figure_id: (link, average, quantity or 1)
        for figure_id, link, average, quantity in db.session.execute(
            select(
                Figure.id, Figure.af411_link, Figure.af411_average, Figure.quantity
            ).where(Figure.af411_average.is_not(None))
        )
    }


def _gestalts():
    """The ids of figures made of others (Combiners, Duocons, Duobots).

    They are not sold in a box of their own, so ActionFigure411, which lists
    whole boxes, has no price for them unless they came in the same box as their
    parts (then they have an average like any other figure).
    """
    return set(db.session.scalars(select(figure_gestalt.c.figure_id).distinct()))


def _worth(figure_ids, prices, gestalts):
    """The value of some figures, how many have an average, and how many could.

    The average is for the whole retail box, so the figures sharing a box (the
    same link) are worth it once between them, times the most copies of any of
    them. A gestalt with no average is left out of the count of figures that
    could have one (``of``).
    """
    priced, boxes, of = 0, {}, 0
    for figure_id in figure_ids:
        if figure_id not in prices:
            of += figure_id not in gestalts
            continue
        priced += 1
        of += 1
        link, average, copies = prices[figure_id]
        # No link on a figure is a box of its own.
        box = boxes.setdefault(link or ("figure", figure_id), [average, 0])
        box[1] = max(box[1], copies)
    value = sum((average * copies for average, copies in boxes.values()), Decimal(0))
    return {"value": value, "priced": priced, "of": of}


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
    A franchise with none (so nothing below it has any either) is left out.
    Each also has the ``worth`` of those figures. A figure tagged with several
    franchises is in each of their totals, so these overlap.
    """
    prices, gestalts = _prices(), _gestalts()
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
            "worth": _worth(figures, prices, gestalts),
            "children": [],
        }
    roots = []
    for franchise_id, node in nodes.items():
        parent = nodes.get(parents[franchise_id])
        (parent["children"] if parent else roots).append(node)
    for node in nodes.values():
        node["children"] = [c for c in node["children"] if c["total"]]
    return [node for node in roots if node["total"]]


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
        # Worked out over all the figures, not added up from the franchises.
        worth = _worth(
            set(db.session.scalars(select(Figure.id))), _prices(), _gestalts()
        )
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
            worth=worth,
            by_franchise=by_franchise,
            by_continuity=by_continuity,
            by_faction=by_faction,
            by_tooling=by_tooling,
            by_category=by_category,
        )
