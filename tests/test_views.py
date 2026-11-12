"""Every view: list, show, add, edit and delete, as a logged-in user, an
anonymous one, and one whose role only allows reading."""

import io
import os

import pytest
from PIL import Image

from app import app as flask_app, appbuilder, db
from app.models import (
    Accessory,
    Category,
    Faction,
    Figure,
    Franchise,
    TFWikiLink,
    Tooling,
)

READER = "reader"
READER_PASSWORD = "reader-pass"

# view path, model, seed key, form data for add, form data for edit, field
CASES = [
    (
        "figuremodelview",
        Figure,
        "figure",
        lambda s: {
            "name": "Megatron",
            "release_year": "1984",
            "character": str(s["character"].id),
            "faction": str(s["faction"].id),
            "franchise": [str(s["franchise"].id)],
            "tooling": [str(s["tooling"].id)],
            "quantity": "2",
        },
    ),
    (
        "franchisemodelview",
        Franchise,
        "franchise",
        lambda s: {"name": "Beast Wars", "start_year": "1996", "end_year": "1999"},
    ),
    ("factionmodelview", Faction, "faction", lambda s: {"name": "Decepticon"}),
    ("toolingmodelview", Tooling, "tooling", lambda s: {"name": "Mega tooling"}),
    ("accessorymodelview", Accessory, "accessory", lambda s: {"name": "Sword"}),
    ("categorymodelview", Category, "category", lambda s: {"name": "Scout"}),
    (
        "tfwikilinkmodelview",
        TFWikiLink,
        "character",
        lambda s: {"name": "Megatron", "link": "https://tfwiki.net/wiki/Megatron"},
    ),
]
IDS = [c[0] for c in CASES]


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), "red").save(buf, "PNG")
    buf.seek(0)
    return buf


@pytest.fixture(scope="session")
def reader_user():
    """A user whose role can list and show, but not add, edit or delete."""
    sm = appbuilder.sm
    with flask_app.app_context():
        role = sm.find_role("Reader") or sm.add_role("Reader")
        for view in sm.session.query(sm.viewmenu_model).all():
            for perm in ("can_list", "can_show"):
                pv = sm.find_permission_view_menu(perm, view.name)
                if pv and pv not in role.permissions:
                    sm.add_permission_role(role, pv)
        if not sm.find_user(username=READER):
            sm.add_user(
                READER, "Read", "Only", "reader@example.com", role, READER_PASSWORD
            )
    return READER


@pytest.fixture
def reader_client(client, reader_user):
    client.post("/login/", data={"username": READER, "password": READER_PASSWORD})
    return client


@pytest.mark.parametrize("view,model,key,form", CASES, ids=IDS)
def test_list_show_contain_seed_data(auth_client, seed, view, model, key, form):
    obj = db.session.get(model, seed[key].id)
    name = obj.name
    listing = auth_client.get("/%s/list/" % view)
    assert listing.status_code == 200 and name in listing.get_data(as_text=True)
    shown = auth_client.get("/%s/show/%s" % (view, obj.id))
    assert shown.status_code == 200 and name in shown.get_data(as_text=True)


@pytest.mark.parametrize("view,model,key,form", CASES, ids=IDS)
def test_add_edit_delete(auth_client, seed, view, model, key, form):
    data = form(seed)
    before = db.session.query(model).count()
    resp = auth_client.get("/%s/add" % view)
    assert resp.status_code == 200
    resp = auth_client.post("/%s/add" % view, data=data, follow_redirects=True)
    assert resp.status_code == 200
    assert db.session.query(model).count() == before + 1
    new = db.session.query(model).filter_by(name=data["name"]).one()
    pk = new.id

    assert auth_client.get("/%s/edit/%s" % (view, pk)).status_code == 200
    data["name"] = "Renamed"
    resp = auth_client.post(
        "/%s/edit/%s" % (view, pk), data=data, follow_redirects=True
    )
    assert resp.status_code == 200
    db.session.expire_all()
    assert db.session.get(model, pk).name == "Renamed"

    resp = auth_client.get("/%s/delete/%s" % (view, pk), follow_redirects=True)
    assert resp.status_code == 200
    db.session.expire_all()
    assert db.session.get(model, pk) is None
    assert db.session.query(model).count() == before


@pytest.mark.parametrize("view,model,key,form", CASES, ids=IDS)
def test_invalid_add_is_rejected(auth_client, seed, view, model, key, form):
    before = db.session.query(model).count()
    resp = auth_client.post("/%s/add" % view, data={}, follow_redirects=True)
    assert resp.status_code == 200
    assert db.session.query(model).count() == before


@pytest.mark.parametrize("view,model,key,form", CASES, ids=IDS)
def test_anonymous_cannot_change_anything(client, seed, view, model, key, form):
    pk = seed[key].id
    before = db.session.query(model).count()
    for method, path in (
        ("get", "/%s/add" % view),
        ("post", "/%s/add" % view),
        ("get", "/%s/edit/%s" % (view, pk)),
        ("post", "/%s/edit/%s" % (view, pk)),
        ("get", "/%s/delete/%s" % (view, pk)),
    ):
        resp = getattr(client, method)(
            path, data=form(seed) if method == "post" else None
        )
        assert resp.status_code == 302, path
        assert "/login/" in resp.headers["Location"], path
    assert db.session.query(model).count() == before


@pytest.mark.parametrize("view,model,key,form", CASES, ids=IDS)
def test_read_only_role_can_view_but_not_change(
    reader_client, seed, view, model, key, form
):
    pk = seed[key].id
    before = db.session.query(model).count()
    assert reader_client.get("/%s/list/" % view).status_code == 200
    assert reader_client.get("/%s/show/%s" % (view, pk)).status_code == 200
    for method, path in (
        ("get", "/%s/add" % view),
        ("post", "/%s/add" % view),
        ("get", "/%s/edit/%s" % (view, pk)),
        ("get", "/%s/delete/%s" % (view, pk)),
    ):
        resp = getattr(reader_client, method)(
            path, data=form(seed) if method == "post" else None
        )
        # FAB 5.2.2+ answers a logged-in user who is not allowed with 403
        # (earlier ones redirected, as for an anonymous user); the page itself
        # is never shown.
        assert resp.status_code == 403, path
    db.session.expire_all()
    assert db.session.query(model).count() == before
    assert db.session.get(model, pk) is not None


def test_figure_list_shows_relations(auth_client, seed):
    html = auth_client.get("/figuremodelview/list/").get_data(as_text=True)
    for text in ("Optimus Prime", "Autobot", "Generation 1", "Leader", "1984"):
        assert text in html


def test_figure_show_renders_helpers(auth_client, seed):
    html = auth_client.get("/figuremodelview/show/%s" % seed["figure"].id).get_data(
        as_text=True
    )
    assert "https://tfwiki.net/wiki/Optimus_Prime" in html
    assert "Generation_1" in html or "Generation 1" in html
    assert "Prime tooling" in html and "Blaster" in html


def test_figure_with_no_optional_fields_shows(auth_client, seed):
    fig = db.session.get(Figure, seed["figure"].id)
    other = Figure(
        name="Bare", release_year=2000, character=fig.character, faction=fig.faction
    )
    db.session.add(other)
    db.session.commit()
    assert auth_client.get("/figuremodelview/show/%s" % other.id).status_code == 200


def test_tfwikilink_list_shows_link_type_and_search_links(auth_client, seed):
    html = auth_client.get("/tfwikilinkmodelview/list/").get_data(as_text=True)
    assert "Character" in html and "Figure (Generation 1)" in html
    assert "Search for this Character" in html and "Search for this Ancestor" in html


# Image views ---------------------------------------------------------------


def _faction_with_image(auth_client, name="Maximal"):
    auth_client.post(
        "/factionmodelview/add",
        data={"name": name, "image": (_png(), "logo.png")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    return db.session.query(Faction).filter_by(name=name).one()


@pytest.mark.parametrize(
    "view,model,field,extra",
    [
        ("franchisemodelview", Franchise, "franchise", {"start_year": "1990"}),
        ("factionmodelview", Faction, "faction", {}),
        ("figuremodelview", Figure, "figure", None),
    ],
)
def test_image_routes_serve_and_404(auth_client, seed, view, model, field, extra):
    if extra is None:  # figure: needs its required fields, so attach to the seed
        fig = db.session.get(Figure, seed["figure"].id)
        folder = flask_app.config["IMG_UPLOAD_FOLDER"]
        Image.new("RGB", (50, 50), "blue").save(os.path.join(folder, "fig.png"))
        fig.image = "fig.png"
        db.session.commit()
        pk = fig.id
    else:
        auth_client.post(
            "/%s/add" % view,
            data=dict(extra, name="Pic", image=(_png(), "p.png")),
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        pk = db.session.query(model).filter_by(name="Pic").one().id
    base = "/%s/%s_img" % (view, field)
    assert auth_client.get("%s/%s" % (base, pk)).status_code == 200
    assert auth_client.get("%s_thumb/%s" % (base, pk)).status_code == 200
    assert auth_client.get("%s/99999" % base).status_code == 404
    assert auth_client.get("%s_thumb/99999" % base).status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/franchisemodelview/franchise_img/%s",
        "/franchisemodelview/franchise_img_thumb/%s",
        "/factionmodelview/faction_img/%s",
        "/factionmodelview/faction_img_thumb/%s",
        "/figuremodelview/figure_img/%s",
        "/figuremodelview/figure_img_thumb/%s",
    ],
)
def test_item_without_image_is_404(auth_client, seed, path):
    key = path.split("/")[2].replace("_img_thumb", "").replace("_img", "")
    pk = seed[key].id
    assert auth_client.get(path % pk).status_code == 404


def test_image_routes_need_login(client, seed):
    resp = client.get("/factionmodelview/faction_img/%s" % seed["faction"].id)
    assert resp.status_code == 302 and "/login/" in resp.headers["Location"]


def test_thumbnail_falls_back_to_original(auth_client):
    faction = _faction_with_image(auth_client)
    folder = flask_app.config["IMG_UPLOAD_FOLDER"]
    base, ext = os.path.splitext(faction.image)
    os.remove(os.path.join(folder, base + "_thumb" + ext))
    resp = auth_client.get("/factionmodelview/faction_img_thumb/%s" % faction.id)
    assert resp.status_code == 200
    with open(os.path.join(folder, faction.image), "rb") as fh:
        assert resp.data == fh.read()


def test_list_views_with_images_show_picture_links(auth_client):
    faction = _faction_with_image(auth_client, "Pic Faction")
    html = auth_client.get("/factionmodelview/list/").get_data(as_text=True)
    assert "/factionmodelview/faction_img_thumb/%s" % faction.id in html
    html = auth_client.get("/factionmodelview/show/%s" % faction.id).get_data(
        as_text=True
    )
    assert "/factionmodelview/faction_img/%s" % faction.id in html


def test_the_new_data_model_columns_stay_out_of_the_forms():
    """They are filled by scripts/migrate_data_model.py until the cutover."""
    from app.views import FigureModelView, FranchiseModelView

    for view, new in (
        (FigureModelView, {"link", "accessories_text", "character_new"}),
        (FranchiseModelView, {"parent", "parent_id"}),
    ):
        for columns in (view.add_columns, view.edit_columns, view.search_columns):
            assert not new & set(columns)
