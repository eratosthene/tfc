from flask_appbuilder import IndexView
from flask_appbuilder.views import expose
from sqlalchemy import func
from app import db
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


class MyIndexView(IndexView):
    index_template = "index.html"

    @expose("/")
    def index(self):
        self.update_redirect()
        num_figures = db.session.query(func.count(Figure.id)).scalar()
        by_franchise = _by_assoc(
            Franchise, figure_franchise, "franchise", [Franchise.start_year]
        )
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
