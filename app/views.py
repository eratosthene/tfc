import os

from flask import (
    abort,
    current_app,
    flash,
    render_template,
    request,
    send_from_directory,
)
from flask_appbuilder import ModelView, expose, has_access, permission_name
from flask_appbuilder.filemanager import thumbgen_filename
from sqlalchemy import select
from wtforms import TextAreaField, widgets
from app import app, appbuilder, db
from app import continuities  # noqa: F401 (registers flask set-continuity-names)
from app.addfigure import AddFromTFWikiView, CsrfOnly
from app.refresh import RefreshFigureView
from app import modernise  # noqa: F401 (registers flask modernise-links)
from app.franchises import FigureInterface, NameSortedInterface, check_parent
from app.models import (
    Character,
    Continuity,
    ContinuityFamily,
    Franchise,
    Faction,
    Figure,
    FigureReference,
    Tooling,
    Category,
)
from app.references import format_references, parse_references


def send_image(item, thumbnail=False):
    """Serve an item's image, or its thumbnail, from the upload folder.

    The table holds only the file name; the thumbnail's name follows from it.
    """
    if item is None or not item.image:
        abort(404)
    folder = current_app.config["IMG_UPLOAD_FOLDER"]
    name = item.image
    if thumbnail:
        thumb = thumbgen_filename(name)
        if os.path.exists(os.path.join(folder, thumb)):
            name = thumb
    return send_from_directory(folder, name)


class FranchiseModelView(ModelView):
    datamodel = NameSortedInterface(Franchise)
    base_order = ("start_year", "asc")
    label_columns = {
        "image_thumb_show": "Picture",
        "image_show": "Picture",
        "link_show": "Link",
        "figure_list": "Figures",
    }
    list_columns = [
        "image_thumb_show",
        "name",
        "parent",
        "start_year",
        "end_year",
        "link_show",
        "figure_list",
    ]
    show_columns = [
        "image_show",
        "name",
        "parent",
        "start_year",
        "end_year",
        "link_show",
    ]
    _columns = [
        "name",
        "parent",
        "link",
        "image",
        "start_year",
        "end_year",
        "legacy_id",
    ]
    add_columns = edit_columns = _columns
    search_columns = ["name", "parent", "link", "start_year", "end_year", "legacy_id"]

    def _check_parent(self, item):
        try:
            check_parent(item, item.parent)
        except ValueError:
            # The form has already put the new parent on the item; drop that.
            self.datamodel.session.rollback()
            raise

    def pre_add(self, item):
        self._check_parent(item)

    def pre_update(self, item):
        self._check_parent(item)

    def pre_delete(self, item):
        if (
            item.id is not None
            and self.datamodel.session.query(Franchise)
            .filter(Franchise.parent_id == item.id)
            .count()
        ):
            raise ValueError(
                "%s still has sub-franchises; move or delete them first." % item.name
            )

    @expose("/franchise_img/<pk>")
    @has_access
    @permission_name("show_img")
    def img(self, pk):
        return send_image(self.datamodel.get(pk))

    @expose("/franchise_img_thumb/<pk>")
    @has_access
    @permission_name("show_img")
    def img_thumb(self, pk):
        return send_image(self.datamodel.get(pk), thumbnail=True)


class FactionModelView(ModelView):
    datamodel = NameSortedInterface(Faction)
    base_order = ("name", "asc")
    label_columns = {
        "image_thumb_show": "Picture",
        "image_show": "Picture",
        "figure_list": "Figures",
    }
    list_columns = ["image_thumb_show", "name", "figure_list"]
    show_columns = ["image_show", "name"]

    @expose("/faction_img/<pk>")
    @has_access
    @permission_name("show_img")
    def img(self, pk):
        return send_image(self.datamodel.get(pk))

    @expose("/faction_img_thumb/<pk>")
    @has_access
    @permission_name("show_img")
    def img_thumb(self, pk):
        return send_image(self.datamodel.get(pk), thumbnail=True)


class ToolingModelView(ModelView):
    datamodel = NameSortedInterface(Tooling)
    base_order = ("name", "asc")
    label_columns = {"figure_list": "Figures"}
    list_columns = ["name", "figure_list"]
    show_columns = ["name"]


class CategoryModelView(ModelView):
    datamodel = NameSortedInterface(Category)
    base_order = ("name", "asc")
    label_columns = {"figure_list": "Figures"}
    list_columns = ["name", "figure_list"]
    show_columns = ["name"]


class CharacterModelView(ModelView):
    datamodel = NameSortedInterface(Character)
    base_order = ("name", "asc")
    label_columns = {"link_show": "Link", "figure_list": "Figures"}
    list_columns = ["name", "continuity", "link_show", "figure_list"]
    show_columns = ["name", "continuity", "link_show"]
    add_columns = edit_columns = ["name", "link", "continuity"]
    search_columns = ["name", "link", "continuity"]


class ContinuityModelView(ModelView):
    datamodel = NameSortedInterface(Continuity)
    base_order = ("name", "asc")
    label_columns = {
        "link_show": "Link",
        "full_name": "Full name",
        "character_list": "Characters",
        "figure_list": "Figures",
    }
    list_columns = [
        "name",
        "full_name",
        "family",
        "link_show",
        "character_list",
        "figure_list",
    ]
    show_columns = ["name", "full_name", "family", "link_show"]
    add_columns = edit_columns = ["name", "full_name", "family", "link"]
    search_columns = ["name", "full_name", "family", "link"]


class ContinuityFamilyModelView(ModelView):
    datamodel = NameSortedInterface(ContinuityFamily)
    base_order = ("name", "asc")
    label_columns = {
        "link_show": "Link",
        "continuity_list": "Continuities",
        "figure_list": "Figures",
    }
    list_columns = ["name", "link_show", "continuity_list", "figure_list"]
    show_columns = ["name", "link_show"]
    add_columns = edit_columns = ["name", "link"]
    search_columns = ["name", "link"]


REFERENCE_FIELDS = (
    ("ancestor", "history_text"),
    ("packed_with", "packed_with_text"),
)


class FullWidthTextArea(widgets.TextArea):
    """A text box as wide as the form, tall enough for a few lines."""

    def __call__(self, field, **kwargs):
        kwargs["class"] = "form-control"
        kwargs["rows"] = 8
        return super().__call__(field, **kwargs)


def reference_fields():
    return {
        "history_text": TextAreaField(
            "Model History",
            description="One ancestor per line:  Name | https://tfwiki.net/wiki/...",
            widget=FullWidthTextArea(),
        ),
        "packed_with_text": TextAreaField(
            "Packed With",
            description="One per line:  Name | https://tfwiki.net/wiki/...",
            widget=FullWidthTextArea(),
        ),
    }


# A figure with gestalt components is expected to have one of these categories.
GESTALT_CATEGORIES = ("Combiner", "Duocon", "Duobot")


class FigureModelView(ModelView):
    datamodel = FigureInterface(Figure)
    base_order = ("name", "asc")
    label_columns = {
        "image_thumb_show": "Picture",
        "image_show": "Picture",
        "character_show": "Character",
        "continuity_show": "Continuity",
        "family_show": "Continuity Family",
        "character_new": "Character",
        "franchise_show": "Franchise(s)",
        "faction_show": "Faction",
        "figure_link_show": "Link to Figure",
        "link": "Link to Figure",
        "history_show": "Model History",
        "packed_with_show": "Packed With",
        "accessories_text": "Accessories",
        "ancestors": "Has ancestor (link)",
        "continuity": "Continuity",
        "family": "Continuity family",
    }
    list_columns = [
        "name",
        "faction",
        "franchise",
        "categories",
        "release_year",
        "image_thumb_show",
    ]
    show_columns = [
        "name",
        "image_show",
        "character_show",
        "continuity_show",
        "family_show",
        "franchise_show",
        "faction_show",
        "release_year",
        "figure_link_show",
        "tooling",
        "history_show",
        "exclusive_to",
        "packed_with_show",
        "hasbro_id",
        "takara_id",
        "gestalt_of",
        "accessories_text",
        "categories",
        "condition",
        "quantity",
    ]
    # Pinned: the form shows the new structures. The old ones (figure_link,
    # character, history, packed_with, accessories) stay in the database, unused,
    # until the contract PR removes them.
    _columns = [
        "name",
        "character_new",
        "faction",
        "franchise",
        "tooling",
        "release_year",
        "image",
        "link",
        "exclusive_to",
        "hasbro_id",
        "takara_id",
        "accessories_text",
        "categories",
        "gestalt_of",
        "condition",
        "quantity",
        "legacy_id",
    ]
    # The two text boxes are form-only fields, so they are named here as well.
    add_columns = edit_columns = _columns + [f for _kind, f in REFERENCE_FIELDS]
    search_columns = [c for c in _columns if c != "image"] + [
        "continuity",
        "family",
        "ancestors",
    ]
    add_form_extra_fields = edit_form_extra_fields = reference_fields()
    edit_template = "figure_edit.html"

    def render_template(self, template, **kwargs):
        """The edit page's "Refresh from TFWiki" panel needs the saved link."""
        if template == self.edit_template:
            kwargs["pk"] = request.view_args.get("pk")
            kwargs["saved_link"] = db.session.scalar(
                select(Figure.link).where(Figure.id == kwargs["pk"])
            )
            kwargs["csrf_form"] = CsrfOnly()
        return super().render_template(template, **kwargs)

    def prefill_form(self, form, pk):
        figure = self.datamodel.get(pk)
        for kind, field in REFERENCE_FIELDS:
            getattr(form, field).data = format_references(
                [r for r in figure.references if r.kind == kind]
            )

    def _check(self, item):
        """Read the form's extra fields onto the item, or refuse with a message."""
        try:
            if item.character_new is None:
                raise ValueError("Pick a character.")
            references = []
            for kind, field in REFERENCE_FIELDS:
                for position, (name, link) in enumerate(
                    parse_references(getattr(item, field, ""))
                ):
                    references.append(
                        FigureReference(
                            kind=kind, position=position, name=name, link=link
                        )
                    )
        except ValueError:
            self.datamodel.session.rollback()
            raise
        item.references = references
        # An empty box means "none", as the migration script stores it.
        item.link = (item.link or "").strip() or None
        item.accessories_text = (item.accessories_text or "").strip() or None
        if item.link and self.datamodel.session.scalar(
            select(Figure.id)
            .where(Figure.link == item.link, Figure.id != (item.id or 0))
            .limit(1)
        ):
            flash("Another figure already has this link (saved anyway).", "warning")
        if item.gestalt_of and not any(
            c.name in GESTALT_CATEGORIES for c in item.categories
        ):
            flash(
                "Gestalt components are set but none of the %s categories is."
                % ", ".join(GESTALT_CATEGORIES),
                "warning",
            )

    def pre_add(self, item):
        self._check(item)

    def pre_update(self, item):
        self._check(item)

    @expose("/figure_img/<pk>")
    @has_access
    @permission_name("show_img")
    def img(self, pk):
        return send_image(self.datamodel.get(pk))

    @expose("/figure_img_thumb/<pk>")
    @has_access
    @permission_name("show_img")
    def img_thumb(self, pk):
        return send_image(self.datamodel.get(pk), thumbnail=True)


appbuilder.add_view(FigureModelView, "Figures")
appbuilder.add_view(AddFromTFWikiView, "Add from TFWiki")
appbuilder.add_view_no_menu(RefreshFigureView)
appbuilder.add_view(FranchiseModelView, "Franchises")
appbuilder.add_view(FactionModelView, "Factions")
appbuilder.add_view(ToolingModelView, "Toolings")
appbuilder.add_view(CategoryModelView, "Categories")
appbuilder.add_view(CharacterModelView, "Characters")
appbuilder.add_view(ContinuityModelView, "Continuities")
appbuilder.add_view(ContinuityFamilyModelView, "Continuity Families")

"""
    Application wide 404 error handler
"""


@app.errorhandler(404)
def page_not_found(e):
    return render_template(
        "404.html", base_template=appbuilder.base_template, appbuilder=appbuilder
    ), 404
