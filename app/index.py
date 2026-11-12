from collections import defaultdict

from flask_appbuilder import IndexView
from flask_appbuilder.views import expose
from sqlalchemy import func, select
from app import db
from app.franchises import descendant_ids, parent_map
from app.models import (
    Category,
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
    """Figures per franchise, counting the ones tagged with anything below it."""
    parents = parent_map()
    tagged = defaultdict(set)
    for figure_id, franchise_id in db.session.execute(
        select(figure_franchise.c.figure_id, figure_franchise.c.franchise_id)
    ):
        tagged[franchise_id].add(figure_id)
    rows = []
    franchises = select(Franchise).order_by(Franchise.start_year, Franchise.id)
    for franchise in db.session.scalars(franchises):
        figures = set()
        for franchise_id in descendant_ids(franchise.id, parents):
            figures |= tagged[franchise_id]
        rows.append({"franchise": franchise, "total": len(figures)})
    return rows


class MyIndexView(IndexView):
    index_template = "index.html"

    @expose("/")
    def index(self):
        self.update_redirect()
        num_figures = db.session.query(func.count(Figure.id)).scalar()
        by_franchise = _by_franchise()
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
            by_faction=by_faction,
            by_tooling=by_tooling,
            by_category=by_category,
        )
