from flask import render_template, Response
from flask_appbuilder import ModelView, expose, has_access, permission_name
from flask_appbuilder.models.mongoengine.interface import MongoEngineInterface
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


class FranchiseModelView(ModelView):
    datamodel = MongoEngineInterface(Franchise)
    base_order = ("start_year", "desc")
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
        item = self.datamodel.get(pk)
        mime_type = item.image.content_type
        return Response(item.image.read(), mimetype=mime_type, direct_passthrough=True)

    @expose("/franchise_img_thumb/<pk>")
    @has_access
    @permission_name("show_img")
    def img_thumb(self, pk):
        item = self.datamodel.get(pk)
        mime_type = item.image.content_type
        return Response(
            item.image.thumbnail.read(), mimetype=mime_type, direct_passthrough=True
        )


class FactionModelView(ModelView):
    datamodel = MongoEngineInterface(Faction)
    base_order = ("name", "desc")
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
        item = self.datamodel.get(pk)
        mime_type = item.image.content_type
        return Response(item.image.read(), mimetype=mime_type, direct_passthrough=True)

    @expose("/faction_img_thumb/<pk>")
    @has_access
    @permission_name("show_img")
    def img_thumb(self, pk):
        item = self.datamodel.get(pk)
        mime_type = item.image.content_type
        return Response(
            item.image.thumbnail.read(), mimetype=mime_type, direct_passthrough=True
        )


class ToolingModelView(ModelView):
    datamodel = MongoEngineInterface(Tooling)
    base_order = ("name", "desc")
    label_columns = {"figure_list": "Figures"}
    list_columns = ["name", "figure_list"]
    show_columns = ["name"]


class AccessoryModelView(ModelView):
    datamodel = MongoEngineInterface(Accessory)
    base_order = ("name", "desc")
    label_columns = {"figure_list": "Figures"}
    list_columns = ["name", "figure_list"]
    show_columns = ["name"]


class CategoryModelView(ModelView):
    datamodel = MongoEngineInterface(Category)
    base_order = ("name", "desc")
    label_columns = {"figure_list": "Figures"}
    list_columns = ["name", "figure_list"]
    show_columns = ["name"]


class TFWikiLinkModelView(ModelView):
    datamodel = MongoEngineInterface(TFWikiLink)
    base_order = ("name", "desc")
    label_columns = {"figure_list": "Figures", "history_list": "History"}
    list_columns = ["name", "link_type", "link", "figure_list", "history_list"]
    show_columns = ["name", "link"]


class FigureModelView(ModelView):
    datamodel = MongoEngineInterface(Figure)
    base_order = ("name", "desc")
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
        item = self.datamodel.get(pk)
        mime_type = item.image.content_type
        return Response(item.image.read(), mimetype=mime_type, direct_passthrough=True)

    @expose("/figure_img_thumb/<pk>")
    @has_access
    @permission_name("show_img")
    def img_thumb(self, pk):
        item = self.datamodel.get(pk)
        mime_type = item.image.content_type
        return Response(
            item.image.thumbnail.read(), mimetype=mime_type, direct_passthrough=True
        )


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
