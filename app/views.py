import os

from flask import abort, render_template, send_from_directory, current_app
from flask_appbuilder import ModelView, expose, has_access, permission_name
from flask_appbuilder.filemanager import thumbgen_filename
from flask_appbuilder.models.sqla.interface import SQLAInterface
from app import appbuilder
from app.models import (
    Franchise,
    Faction,
    Figure,
    Tooling,
    Accessory,
    Category,
    TFWikiLink,
)


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
    datamodel = SQLAInterface(Franchise)
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
        "start_year",
        "end_year",
        "link_show",
        "figure_list",
    ]
    show_columns = ["image_show", "name", "start_year", "end_year", "link_show"]

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
    datamodel = SQLAInterface(Faction)
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
    datamodel = SQLAInterface(Tooling)
    base_order = ("name", "asc")
    label_columns = {"figure_list": "Figures"}
    list_columns = ["name", "figure_list"]
    show_columns = ["name"]


class AccessoryModelView(ModelView):
    datamodel = SQLAInterface(Accessory)
    base_order = ("name", "asc")
    label_columns = {"figure_list": "Figures"}
    list_columns = ["name", "figure_list"]
    show_columns = ["name"]


class CategoryModelView(ModelView):
    datamodel = SQLAInterface(Category)
    base_order = ("name", "asc")
    label_columns = {"figure_list": "Figures"}
    list_columns = ["name", "figure_list"]
    show_columns = ["name"]


class TFWikiLinkModelView(ModelView):
    datamodel = SQLAInterface(TFWikiLink)
    base_order = ("name", "asc")
    label_columns = {"figure_list": "Figures", "history_list": "History"}
    list_columns = ["name", "link_type", "link", "figure_list", "history_list"]
    show_columns = ["name", "link"]


class FigureModelView(ModelView):
    datamodel = SQLAInterface(Figure)
    base_order = ("name", "asc")
    label_columns = {
        "image_thumb_show": "Picture",
        "image_show": "Picture",
        "character_show": "Character",
        "franchise_show": "Franchise(s)",
        "faction_show": "Faction",
        "figure_link_show": "Link to Figure",
        "history_show": "Model History",
        "packed_with_show": "Packed With",
    }
    list_columns = [
        "name",
        "faction",
        "franchise",
        "categories",
        "release_year",
        "image_thumb_show",
    ]
    # list_widget = ListBlock
    show_columns = [
        "name",
        "image_show",
        "character_show",
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
        "accessories",
        "categories",
        "condition",
        "quantity",
    ]

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
appbuilder.add_view(FranchiseModelView, "Franchises")
appbuilder.add_view(FactionModelView, "Factions")
appbuilder.add_view(ToolingModelView, "Toolings")
appbuilder.add_view(AccessoryModelView, "Accessories")
appbuilder.add_view(CategoryModelView, "Categories")
appbuilder.add_view(TFWikiLinkModelView, "TFWikiLinks")

"""
    Application wide 404 error handler
"""


@appbuilder.app.errorhandler(404)
def page_not_found(e):
    return render_template(
        "404.html", base_template=appbuilder.base_template, appbuilder=appbuilder
    ), 404
