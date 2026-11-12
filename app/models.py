from flask import url_for
from flask_appbuilder.models.mixins import ImageColumn
from markupsafe import Markup, escape
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    event,
    func,
    select,
)
from sqlalchemy.orm import relationship, validates

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


class Legacy:
    """The MongoDB ObjectId a row was migrated from (scripts/migrate_mongo_to_sql.py).

    It makes re-running the migration an upsert, and lets later work match
    records to the old data. Rows made in the app leave it empty. Drop it in a
    cleanup once it is no longer needed.
    """

    legacy_id = Column(String(24), unique=True)

    @validates("legacy_id")
    def _blank_legacy_id_is_null(self, key, value):
        # A form sends "" for an empty box, and the column is unique.
        return value or None


class Named:
    """__str__ and __repr__ as the name, which is what the views show."""

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


class Franchise(Legacy, Named, db.Model):
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
    # The wider franchise this one belongs to (Legacy United -> Generations).
    # Not used by the views yet; see docs/proposals/data-model.md.
    parent_id = Column(Integer, ForeignKey("franchise.id"))

    parent = relationship("Franchise", remote_side=[id])

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


class Faction(Legacy, Named, db.Model):
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


class Tooling(Legacy, Named, db.Model):
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


class Accessory(Legacy, Named, db.Model):
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


class Category(Legacy, Named, db.Model):
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


class TFWikiLink(Legacy, db.Model):
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


# The structures of docs/proposals/data-model.md. They sit next to the old ones
# (tf_wiki_link, accessory, ...) until the cutover and are filled in by
# scripts/migrate_data_model.py; the views do not read them yet.
def _link(url, text):
    return Markup('<a href="{}">{}</a>').format(url, text)


def _list_link(view, text, **filters):
    return Markup('<a href="{}">{}</a>').format(
        url_for(view + ".list", **filters), text
    )


class ContinuityFamily(Named, db.Model):
    """The wiki's grouping of continuities (Aligned, Generation 1, Robots in
    Disguise...). A continuity such as RID or FOC belongs to at most one."""

    __tablename__ = "continuity_family"
    __table_args__ = TABLE_ARGS
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    link = Column(String(500))

    def link_show(self):
        return _link(self.link, self.link) if self.link else Markup("")

    def continuity_list(self):
        return _list_link(
            "ContinuityModelView", "Continuities", _flt_0_family=str(self.id)
        )

    def figure_list(self):
        return _list_link(
            "FigureModelView", "Search Figures", _flt_0_family=str(self.id)
        )


class Continuity(Named, db.Model):
    __tablename__ = "continuity"
    __table_args__ = TABLE_ARGS
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    link = Column(String(500))
    family_id = Column(Integer, ForeignKey("continuity_family.id"))

    family = relationship("ContinuityFamily")

    def link_show(self):
        return _link(self.link, self.link) if self.link else Markup("")

    def character_list(self):
        return _list_link(
            "CharacterModelView", "Characters", _flt_0_continuity=str(self.id)
        )

    def figure_list(self):
        return _list_link(
            "FigureModelView", "Search Figures", _flt_0_continuity=str(self.id)
        )


class Character(Named, db.Model):
    """A character in one continuity, which is what a wiki page is about."""

    __tablename__ = "character"
    __table_args__ = TABLE_ARGS
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    link = Column(String(500), nullable=False, unique=True)
    continuity_id = Column(Integer, ForeignKey("continuity.id"))

    continuity = relationship("Continuity")

    def link_show(self):
        return _link(self.link, self.link)

    def figure_list(self):
        return _list_link(
            "FigureModelView", "Search Figures", _flt_0_character_new=str(self.id)
        )


class FranchiseAlias(db.Model):
    """A wiki toyline heading or anchor that stands for one of our franchises."""

    __tablename__ = "franchise_alias"
    __table_args__ = TABLE_ARGS
    id = Column(Integer, primary_key=True)
    franchise_id = Column(
        Integer, ForeignKey("franchise.id", ondelete="CASCADE"), nullable=False
    )
    alias = Column(String(255), nullable=False, unique=True)

    franchise = relationship("Franchise")


class DataModelMigration(db.Model):
    """What scripts/migrate_data_model.py has done, one row per step.

    The revision that finally drops the old tables refuses to run unless the
    ``verify`` row is there.
    """

    __tablename__ = "data_model_migration"
    __table_args__ = TABLE_ARGS
    id = Column(Integer, primary_key=True)
    step = Column(String(60), nullable=False, unique=True)
    recorded_at = Column(DateTime, nullable=False, server_default=func.now())
    detail = Column(Text)


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


class Figure(Legacy, Named, db.Model):
    __tablename__ = "figure"
    __table_args__ = TABLE_ARGS
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    release_year = Column(Integer, nullable=False)
    image = Column(
        ImageColumn(thumbnail_size=(300, 300, False), size=(2000, 2000, False)),
    )
    figure_link_id = Column(Integer, ForeignKey("tf_wiki_link.id"))
    # The old structure, kept until the contract PR. New figures leave it empty.
    character_id = Column(Integer, ForeignKey("tf_wiki_link.id"))
    faction_id = Column(Integer, ForeignKey("faction.id"), nullable=False)
    exclusive_to = Column(String(255))
    hasbro_id = Column(String(255))
    takara_id = Column(String(255))
    condition = Column(String(255))
    quantity = Column(Integer, default=1)
    # The new structures, filled by scripts/migrate_data_model.py and not read by
    # the views yet. They take their final names (link, character_id and
    # accessories) when the old columns go.
    link = Column(String(500))
    character_id_new = Column(Integer, ForeignKey("character.id"))
    accessories_text = Column(Text)

    character_new = relationship("Character")
    # Read-only paths for the Figure list's filters and searches.
    continuity = relationship(
        "Continuity",
        secondary=Character.__table__,
        primaryjoin="Figure.character_id_new == Character.id",
        secondaryjoin="Character.continuity_id == Continuity.id",
        viewonly=True,
    )
    family = relationship(
        "ContinuityFamily",
        secondary=lambda: Character.__table__.join(
            Continuity.__table__, Character.continuity_id == Continuity.id
        ),
        primaryjoin="Figure.character_id_new == Character.id",
        secondaryjoin="Continuity.family_id == ContinuityFamily.id",
        viewonly=True,
    )
    ancestors = relationship(
        "FigureReference",
        primaryjoin="and_(Figure.id == FigureReference.figure_id, "
        "FigureReference.kind == 'ancestor')",
        order_by="FigureReference.position",
        viewonly=True,
    )
    references = relationship(
        "FigureReference",
        order_by="FigureReference.kind, FigureReference.position, FigureReference.id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
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
        char = self.character_new
        if char is None:
            return Markup("")
        text = char.name
        if char.continuity:
            text += " (" + char.continuity.name + ")"
        return _link(char.link, text)

    def continuity_show(self):
        continuity = self.character_new.continuity if self.character_new else None
        if continuity is None:
            return Markup("")
        return _link(
            url_for("ContinuityModelView.show", pk=str(continuity.id)), continuity
        )

    def family_show(self):
        continuity = self.character_new.continuity if self.character_new else None
        if continuity is None or continuity.family is None:
            return Markup("")
        return _link(
            url_for("ContinuityFamilyModelView.show", pk=str(continuity.family.id)),
            continuity.family,
        )

    def franchise_show(self):
        # The tagged franchises, then the ones above them (app/franchises.py).
        from app.franchises import effective_franchises

        return self.link_list_show(effective_franchises(self), True)

    def figure_link_show(self):
        return _link(self.link, self.link) if self.link else Markup("")

    def _references_show(self, kind, others):
        refs = [r for r in self.references if r.kind == kind]
        owned = {}
        if refs:
            for fid, link in db.session.execute(
                select(Figure.id, Figure.link)
                .where(Figure.link.in_({r.link for r in refs}))
                .order_by(Figure.id.desc())
            ):
                owned[link] = fid
        m = Markup('<table class="table table-condensed table-striped"><tbody>')
        for ref in refs:
            m += Markup("<tr><td>") + _link(ref.link, ref.name)
            if ref.link in owned:
                m += Markup(" &mdash; ") + _link(
                    url_for("FigureModelView.show", pk=str(owned[ref.link])),
                    "In collection",
                )
            if others:
                m += Markup(" &middot; ") + _list_link(
                    "FigureModelView",
                    "Other figures from this ancestor",
                    _flt_0_ancestors=ref.link,
                )
            m += Markup("</td></tr>")
        return m + Markup("</tbody></table>")

    def history_show(self):
        return self._references_show("ancestor", True)

    def packed_with_show(self):
        return self._references_show("packed_with", False)


class FigureReference(db.Model):
    """An ancestor or pack-mate of a figure, as the name and wiki link it had."""

    __tablename__ = "figure_reference"
    __table_args__ = TABLE_ARGS
    KINDS = ("ancestor", "packed_with")
    id = Column(Integer, primary_key=True)
    figure_id = Column(
        Integer, ForeignKey("figure.id", ondelete="CASCADE"), nullable=False
    )
    kind = Column(String(20), nullable=False)
    position = Column(Integer, nullable=False, default=0, server_default="0")
    name = Column(String(255), nullable=False)
    link = Column(String(500), nullable=False)


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
