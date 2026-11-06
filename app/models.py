from flask import url_for
from flask_appbuilder.models.mixins import ImageColumn
from markupsafe import Markup, escape
from sqlalchemy import Column, ForeignKey, Integer, String, Table, event
from sqlalchemy.orm import relationship

from app import db

# Every table is utf8mb4, so names and links can hold any character.
TABLE_ARGS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


def _table(name, *columns):
    return Table(name, db.metadata, *columns, **TABLE_ARGS)


def _position_table(name, left, right, left_fk, right_fk):
    """An association table that keeps the order the items were saved in.

    The right side is not cascaded: deleting a link or franchise that a figure
    still uses is refused by the database, as it would leave a figure that
    points at nothing.
    """
    return _table(
        name,
        Column(
            left, Integer, ForeignKey(left_fk, ondelete="CASCADE"), primary_key=True
        ),
        Column(right, Integer, ForeignKey(right_fk), primary_key=True),
        Column("position", Integer, nullable=False, default=0, server_default="0"),
    )


class Named:
    """__str__ and __repr__ as the name, which is what the views show."""

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


class Franchise(Named, db.Model):
    __tablename__ = "franchise"
    __table_args__ = TABLE_ARGS
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    link = Column(String(500))
    image = Column(
        ImageColumn(thumbnail_size=(100, 50, False), size=(2000, 2000, False)),
    )
    start_year = Column(Integer, nullable=False)
    end_year = Column(Integer)

    def image_show(self):
        if self.image:
            return Markup(
                '<a href="'
                + url_for("FranchiseModelView.show", pk=str(self.id))
                + '" class="thumbnail"><img src="'
                + url_for("FranchiseModelView.img", pk=str(self.id))
                + '" alt="Photo" class="img-rounded img-responsive"></a>'
            )
        else:
            return Markup("")

    def image_thumb_show(self):
        if self.image:
            return Markup(
                '<a href="'
                + url_for("FranchiseModelView.show", pk=str(self.id))
                + '" class="thumbnail"><img src="'
                + url_for("FranchiseModelView.img_thumb", pk=str(self.id))
                + '" alt="Photo" class="img-rounded img-responsive"></a>'
            )
        else:
            return Markup("")

    def link_show(self):
        if not self.link:
            return Markup("")
        return Markup('<a href="{0}">{0}</a>').format(self.link)

    def figure_list(self):
        return Markup(
            '<a href="'
            + url_for("FigureModelView.list", _flt_0_franchise=str(self.id))
            + '">Search Figures</a>'
        )


class Faction(Named, db.Model):
    __tablename__ = "faction"
    __table_args__ = TABLE_ARGS
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    image = Column(
        ImageColumn(thumbnail_size=(100, 50, False), size=(2000, 2000, False)),
    )

    def image_show(self):
        if self.image:
            return Markup(
                '<a href="'
                + url_for("FactionModelView.show", pk=str(self.id))
                + '" class="thumbnail"><img src="'
                + url_for("FactionModelView.img", pk=str(self.id))
                + '" alt="Photo" class="img-rounded img-responsive"></a>'
            )
        else:
            return Markup("")

    def image_thumb_show(self):
        if self.image:
            return Markup(
                '<a href="'
                + url_for("FactionModelView.show", pk=str(self.id))
                + '" class="thumbnail"><img src="'
                + url_for("FactionModelView.img_thumb", pk=str(self.id))
                + '" alt="Photo" class="img-rounded img-responsive"></a>'
            )
        else:
            return Markup("")

    def figure_list(self):
        return Markup(
            '<a href="'
            + url_for("FigureModelView.list", _flt_0_faction=str(self.id))
            + '">Search Figures</a>'
        )


class Tooling(Named, db.Model):
    __tablename__ = "tooling"
    __table_args__ = TABLE_ARGS
    id = Column(Integer, primary_key=True)
    name = Column(String(60), nullable=False, unique=True)

    def figure_list(self):
        return Markup(
            '<a href="'
            + url_for("FigureModelView.list", _flt_0_tooling=str(self.id))
            + '">Search Figures</a>'
        )


class Accessory(Named, db.Model):
    __tablename__ = "accessory"
    __table_args__ = TABLE_ARGS
    id = Column(Integer, primary_key=True)
    name = Column(String(60), nullable=False, unique=True)

    def figure_list(self):
        return Markup(
            '<a href="'
            + url_for("FigureModelView.list", _flt_0_accessories=str(self.id))
            + '">Search Figures</a>'
        )


class Category(Named, db.Model):
    __tablename__ = "category"
    __table_args__ = TABLE_ARGS
    id = Column(Integer, primary_key=True)
    name = Column(String(60), nullable=False, unique=True)

    def figure_list(self):
        return Markup(
            '<a href="'
            + url_for("FigureModelView.list", _flt_0_categories=str(self.id))
            + '">Search Figures</a>'
        )


class TFWikiLink(db.Model):
    __tablename__ = "tf_wiki_link"
    __table_args__ = TABLE_ARGS
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    link = Column(String(500), nullable=False)

    def __repr__(self):
        return str(self)

    def __str__(self):
        ls = self.link.split("#")
        if len(ls) > 1:
            n = ls[0].split("/")[-1]
            if n == "toys" or n == "Generations_toys":
                n = ls[0].split("/")[-2]
            sn = n.split("_(")
            if len(sn) > 1:
                return (
                    self.name
                    + " ("
                    + sn[-1]
                    + " @ "
                    + ls[-1].replace("_", " ")
                    + " [figure]"
                )
            else:
                return self.name + " @ " + ls[-1].replace("_", " ") + " [figure]"
        n = self.link.split("/")[-1]
        sn = n.split("_(")
        if len(sn) > 1:
            return self.name + " (" + sn[-1] + " [character]"
        else:
            return self.name + " [character]"

    def link_type(self):
        ls = self.link.split("#")
        if len(ls) > 1:
            return "Figure (" + ls[-1].replace("_", " ") + ")"
        n = self.link.split("/")[-1]
        sn = n.split("_(")
        if len(sn) > 1:
            return "Character (" + sn[-1]
        else:
            return "Character"

    def figure_list(self):
        if "Character" in self.link_type():
            return Markup(
                '<a href="'
                + url_for("FigureModelView.list", _flt_0_character=str(self.id))
                + '">Search for this Character</a>'
            )
        else:
            return Markup(
                '<a href="'
                + url_for("FigureModelView.list", _flt_0_figure_link=str(self.id))
                + '">Search for this Figure</a>'
            )

    def history_list(self):
        if "Figure" in self.link_type():
            return Markup(
                '<a href="'
                + url_for("FigureModelView.list", _flt_0_history=str(self.id))
                + '">Search for this Ancestor</a>'
            )
        else:
            return Markup("")


# Many-to-many tables between a figure and the things it lists. Their
# ``position`` column keeps the order the user picked, which the display
# relies on (franchise order, packed-with order, ...).
figure_franchise = _position_table(
    "figure_franchise", "figure_id", "franchise_id", "figure.id", "franchise.id"
)
figure_tooling = _position_table(
    "figure_tooling", "figure_id", "tooling_id", "figure.id", "tooling.id"
)
figure_history = _position_table(
    "figure_history", "figure_id", "tf_wiki_link_id", "figure.id", "tf_wiki_link.id"
)
figure_packed_with = _position_table(
    "figure_packed_with", "figure_id", "tf_wiki_link_id", "figure.id", "tf_wiki_link.id"
)
figure_accessory = _position_table(
    "figure_accessory", "figure_id", "accessory_id", "figure.id", "accessory.id"
)
figure_category = _position_table(
    "figure_category", "figure_id", "category_id", "figure.id", "category.id"
)
figure_gestalt = _position_table(
    "figure_gestalt", "figure_id", "gestalt_id", "figure.id", "figure.id"
)

# (relationship name, association table) pairs whose order is kept.
ORDERED = (
    ("franchise", figure_franchise),
    ("tooling", figure_tooling),
    ("history", figure_history),
    ("packed_with", figure_packed_with),
    ("gestalt_of", figure_gestalt),
    ("accessories", figure_accessory),
    ("categories", figure_category),
)


class Figure(Named, db.Model):
    __tablename__ = "figure"
    __table_args__ = TABLE_ARGS
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    release_year = Column(Integer, nullable=False)
    image = Column(
        ImageColumn(thumbnail_size=(300, 300, False), size=(2000, 2000, False)),
    )
    figure_link_id = Column(Integer, ForeignKey("tf_wiki_link.id"))
    character_id = Column(Integer, ForeignKey("tf_wiki_link.id"), nullable=False)
    faction_id = Column(Integer, ForeignKey("faction.id"), nullable=False)
    exclusive_to = Column(String(255))
    hasbro_id = Column(String(255))
    takara_id = Column(String(255))
    condition = Column(String(255))
    quantity = Column(Integer, default=1)

    figure_link = relationship("TFWikiLink", foreign_keys=[figure_link_id])
    character = relationship("TFWikiLink", foreign_keys=[character_id])
    faction = relationship("Faction")
    franchise = relationship(
        "Franchise", secondary=figure_franchise, order_by=figure_franchise.c.position
    )
    tooling = relationship(
        "Tooling", secondary=figure_tooling, order_by=figure_tooling.c.position
    )
    history = relationship(
        "TFWikiLink", secondary=figure_history, order_by=figure_history.c.position
    )
    packed_with = relationship(
        "TFWikiLink",
        secondary=figure_packed_with,
        order_by=figure_packed_with.c.position,
    )
    gestalt_of = relationship(
        "Figure",
        secondary=figure_gestalt,
        primaryjoin=id == figure_gestalt.c.figure_id,
        secondaryjoin=id == figure_gestalt.c.gestalt_id,
        order_by=figure_gestalt.c.position,
    )
    accessories = relationship(
        "Accessory", secondary=figure_accessory, order_by=figure_accessory.c.position
    )
    categories = relationship(
        "Category", secondary=figure_category, order_by=figure_category.c.position
    )

    def image_show(self):
        if self.image:
            return Markup(
                '<a href="'
                + url_for("FigureModelView.img", pk=str(self.id))
                + '" class="thumbnail" target="_blank"><img src="'
                + url_for("FigureModelView.img", pk=str(self.id))
                + '" alt="Photo" class="img-rounded img-responsive"></a>'
            )
        else:
            return Markup("")

    def image_thumb_show(self):
        if self.image:
            return Markup(
                '<a href="'
                + url_for("FigureModelView.img", pk=str(self.id))
                + '" class="thumbnail" target="_blank"><img src="'
                + url_for("FigureModelView.img_thumb", pk=str(self.id))
                + '" alt="Photo" class="img-rounded img-responsive"></a>'
            )
        else:
            return Markup("")

    def faction_show(self):
        if self.faction is None:
            return Markup("")
        m = Markup("<p>{}</p>").format(str(self.faction))
        if self.faction.image:
            m += Markup('<img src="{}" alt="{}" class="img-responsive">').format(
                url_for("FactionModelView.img_thumb", pk=str(self.faction.id)),
                self.faction.name,
            )
        return m

    def link_show(self, link):
        if link is None:
            return Markup("")
        return Markup('<a href="{}">{}</a>').format(link.link, str(link))

    def link_list_show(self, link_list, hasimg=False):
        m = Markup('<table class="table table-condensed table-striped"><tbody>')
        for item in link_list:
            m += Markup('<tr><td><a href="{}">').format(item.link)
            if hasimg and item.image:
                m += Markup(
                    '<img src="{}" alt="{}" class="img-responsive"><br/>'
                ).format(
                    url_for("FranchiseModelView.img", pk=str(item.id)),
                    item.name,
                )
            m += escape(str(item)) + Markup("</a></td></tr>")
        m += Markup("</tbody></table>")
        return m

    def character_show(self):
        return self.link_show(self.character)

    def franchise_show(self):
        return self.link_list_show(self.franchise, True)

    def figure_link_show(self):
        return self.link_show(self.figure_link)

    def history_show(self):
        return self.link_list_show(self.history)

    def packed_with_show(self):
        return self.link_list_show(self.packed_with)


@event.listens_for(db.session, "after_flush")
def _save_positions(session, flush_context):
    """Write each ordered list's ``position`` once its rows are inserted.

    SQLAlchemy inserts the association rows but has no value for ``position``,
    so number them here from the order of the list on the figure.
    """
    figures = [
        o for o in list(session.new) + list(session.dirty) if isinstance(o, Figure)
    ]
    with session.no_autoflush:
        for fig in figures:
            for attr, table in ORDERED:
                right = [c for c in table.c if c.primary_key and c.name != "figure_id"][
                    0
                ]
                for pos, item in enumerate(getattr(fig, attr)):
                    session.execute(
                        table.update()
                        .where(table.c.figure_id == fig.id)
                        .where(right == item.id)
                        .values(position=pos)
                    )
