import io
import os

from PIL import Image

from app import app as flask_app, db
from app.models import Faction, Figure, Franchise, Tooling


def _png(color="red", size=(400, 300)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    buf.seek(0)
    return buf


def test_list_order_is_kept(seed):
    a = Franchise(name="A", start_year=1990)
    b = Franchise(name="B", start_year=1991)
    c = Franchise(name="C", start_year=1992)
    fig = db.session.get(Figure, seed["figure"].id)
    fig.franchise = [c, a, b]
    db.session.commit()
    db.session.expire_all()
    assert [f.name for f in db.session.get(Figure, fig.id).franchise] == [
        "C",
        "A",
        "B",
    ]
    fig.franchise = [b, c]
    db.session.commit()
    db.session.expire_all()
    assert [f.name for f in db.session.get(Figure, fig.id).franchise] == [
        "B",
        "C",
    ]


def test_gestalt_of_and_packed_with(seed):
    q = db.session.query
    fig = q(Figure).get(seed["figure"].id)
    other = Figure(
        name="Gestalt",
        release_year=1985,
        character=fig.character,
        faction=fig.faction,
        gestalt_of=[fig],
        packed_with=[fig.figure_link, fig.character],
    )
    db.session.add(other)
    db.session.commit()
    db.session.expire_all()
    other = db.session.get(Figure, other.id)
    assert [f.name for f in other.gestalt_of] == ["Optimus Prime"]
    assert [str(x) for x in other.packed_with][0].endswith("[figure]")


def test_index_counts_include_zero(auth_client, seed):
    db.session.add_all([Tooling(name="Unused"), Faction(name="Decepticon")])
    db.session.commit()
    resp = auth_client.get("/")
    html = resp.get_data(as_text=True)
    assert "Unused" in html and "Decepticon" in html
    assert "Total number of figures: 1" in html


def test_relationship_filter(auth_client, seed):
    fid = seed["franchise"].id
    resp = auth_client.get("/figuremodelview/list/?_flt_0_franchise=%s" % fid)
    assert resp.status_code == 200
    assert "Optimus Prime" in resp.get_data(as_text=True)
    resp = auth_client.get(
        "/figuremodelview/list/?_flt_0_faction=%s" % seed["faction"].id
    )
    assert "Optimus Prime" in resp.get_data(as_text=True)


def test_image_upload_serve_and_delete(auth_client):
    resp = auth_client.post(
        "/factionmodelview/add",
        data={"name": "Maximal", "image": (_png(), "logo.png")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    faction = db.session.query(Faction).filter_by(name="Maximal").one()
    folder = flask_app.config["IMG_UPLOAD_FOLDER"]
    assert faction.image and os.path.exists(os.path.join(folder, faction.image))
    base, ext = os.path.splitext(faction.image)
    thumb = base + "_thumb" + ext
    assert os.path.exists(os.path.join(folder, thumb))
    assert Image.open(os.path.join(folder, thumb)).size[0] <= 100

    full = auth_client.get("/factionmodelview/faction_img/%s" % faction.id)
    small = auth_client.get("/factionmodelview/faction_img_thumb/%s" % faction.id)
    assert full.status_code == small.status_code == 200
    assert full.mimetype == "image/png"
    assert len(small.data) < len(full.data)
    assert auth_client.get("/factionmodelview/faction_img/9999").status_code == 404

    path = os.path.join(folder, faction.image)
    auth_client.get("/factionmodelview/delete/%s" % faction.id, follow_redirects=True)
    assert db.session.query(Faction).count() == 0
    assert not os.path.exists(path)
    assert not os.path.exists(os.path.join(folder, thumb))


def test_add_edit_delete_figure(auth_client, seed):
    data = {
        "name": "Megatron",
        "release_year": "1984",
        "character": str(seed["character"].id),
        "faction": str(seed["faction"].id),
        "franchise": [str(seed["franchise"].id)],
        "tooling": [str(seed["tooling"].id)],
        "quantity": "2",
    }
    resp = auth_client.post("/figuremodelview/add", data=data, follow_redirects=True)
    assert resp.status_code == 200
    fig = db.session.query(Figure).filter_by(name="Megatron").one()
    assert fig.quantity == 2 and fig.faction.name == "Autobot"
    fig_id = fig.id

    data["name"] = "Megatron 2"
    resp = auth_client.post(
        "/figuremodelview/edit/%s" % fig_id, data=data, follow_redirects=True
    )
    assert resp.status_code == 200
    db.session.expire_all()
    assert db.session.get(Figure, fig_id).name == "Megatron 2"
    assert auth_client.get("/figuremodelview/show/%s" % fig_id).status_code == 200

    auth_client.get("/figuremodelview/delete/%s" % fig_id, follow_redirects=True)
    assert db.session.query(Figure).filter_by(name="Megatron 2").count() == 0


def test_delete_link_in_use_is_refused(auth_client, seed):
    resp = auth_client.get(
        "/tfwikilinkmodelview/delete/%s" % seed["character"].id,
        follow_redirects=True,
    )
    assert resp.status_code == 200
    db.session.expire_all()
    assert db.session.query(Figure).count() == 1
