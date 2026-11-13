import io
import os
import re

import pytest
from PIL import Image

from app import app as flask_app, db
from app.models import (
    Category,
    Faction,
    Figure,
    FigureReference,
    Franchise,
    Tooling,
)


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


def test_gestalt_of_and_references(seed):
    fig = db.session.get(Figure, seed["figure"].id)
    other = Figure(
        name="Gestalt",
        release_year=1985,
        character_new=fig.character_new,
        faction=fig.faction,
        gestalt_of=[fig],
        references=[
            FigureReference(
                kind="packed_with", position=1, name="B", link="https://x/b"
            ),
            FigureReference(
                kind="packed_with", position=0, name="A", link="https://x/a"
            ),
            FigureReference(
                kind="ancestor", position=0, name="Old", link="https://x/o"
            ),
        ],
    )
    db.session.add(other)
    db.session.commit()
    db.session.expire_all()
    other = db.session.get(Figure, other.id)
    assert [f.name for f in other.gestalt_of] == ["Optimus Prime"]
    assert [(r.kind, r.name) for r in other.references] == [
        ("ancestor", "Old"),
        ("packed_with", "A"),
        ("packed_with", "B"),
    ]
    assert [r.name for r in other.ancestors] == ["Old"]
    db.session.delete(other)
    db.session.commit()
    assert db.session.query(FigureReference).count() == 2  # the seed figure's own


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
        "character_new": str(seed["character"].id),
        "faction": str(seed["faction"].id),
        "franchise": [str(seed["franchise"].id)],
        "tooling": [str(seed["tooling"].id)],
        "quantity": "2",
        "link": "https://tfwiki.net/wiki/Megatron_(G1)#Generation_1",
        "accessories_text": "Fusion cannon, Stand",
        "history_text": "Diaclone Megatron | https://tfwiki.net/wiki/Diaclone_Megatron\n",
        "packed_with_text": "",
    }
    resp = auth_client.post("/figuremodelview/add", data=data, follow_redirects=True)
    assert resp.status_code == 200
    fig = db.session.query(Figure).filter_by(name="Megatron").one()
    assert fig.quantity == 2 and fig.faction.name == "Autobot"
    assert fig.accessories_text == "Fusion cannon, Stand"
    assert [(r.kind, r.name) for r in fig.references] == [
        ("ancestor", "Diaclone Megatron")
    ]
    fig_id = fig.id
    # The edit form starts with the saved references in its text boxes.
    html = auth_client.get("/figuremodelview/edit/%s" % fig_id).get_data(as_text=True)
    assert "Diaclone Megatron | https://tfwiki.net/wiki/Diaclone_Megatron" in html

    data["name"] = "Megatron 2"
    data["history_text"] = ""
    data["packed_with_text"] = "Cannon | https://tfwiki.net/wiki/Cannon"
    resp = auth_client.post(
        "/figuremodelview/edit/%s" % fig_id, data=data, follow_redirects=True
    )
    assert resp.status_code == 200
    db.session.expire_all()
    assert db.session.get(Figure, fig_id).name == "Megatron 2"
    assert [(r.kind, r.name) for r in db.session.get(Figure, fig_id).references] == [
        ("packed_with", "Cannon")
    ]
    assert db.session.query(FigureReference).filter_by(figure_id=fig_id).count() == 1
    assert auth_client.get("/figuremodelview/show/%s" % fig_id).status_code == 200

    auth_client.get("/figuremodelview/delete/%s" % fig_id, follow_redirects=True)
    assert db.session.query(Figure).filter_by(name="Megatron 2").count() == 0


def figure_form(seed, **changes):
    data = {
        "name": "Form figure",
        "release_year": "2020",
        "character_new": str(seed["character"].id),
        "faction": str(seed["faction"].id),
        "quantity": "1",
    }
    data.update(changes)
    return data


def post_figure(auth_client, data, path="/figuremodelview/add"):
    return auth_client.post(path, data=data, follow_redirects=True).get_data(
        as_text=True
    )


def test_a_figure_needs_a_character(auth_client, seed):
    data = figure_form(seed)
    del data["character_new"]
    assert "Pick a character." in post_figure(auth_client, data)
    assert db.session.query(Figure).filter_by(name="Form figure").count() == 0


@pytest.mark.parametrize(
    "text, message",
    [
        ("no bar here", "Line 1: write it as  Name | link"),
        ("Name |", "Line 1: write it as  Name | link"),
        (
            "ok | https://x/ok\n\nName | ftp://x",
            "Line 3: the link must start with http",
        ),
        ("x" * 256 + " | https://x/a", "Line 1 is too long."),
    ],
)
def test_a_bad_reference_line_is_refused_and_nothing_is_saved(
    auth_client, seed, text, message
):
    html = post_figure(auth_client, figure_form(seed, history_text=text))
    assert message in html
    assert db.session.query(Figure).filter_by(name="Form figure").count() == 0


def test_a_bad_reference_on_edit_keeps_the_saved_ones(auth_client, seed):
    path = "/figuremodelview/edit/%s" % seed["figure"].id
    html = post_figure(
        auth_client, figure_form(seed, name="Optimus Prime", history_text="oops"), path
    )
    assert "write it as" in html
    db.session.expire_all()
    fig = db.session.get(Figure, seed["figure"].id)
    assert sorted(r.name for r in fig.references) == ["Diaclone Convoy", "Roller"]


def test_the_same_link_on_two_figures_saves_with_a_warning(auth_client, seed):
    link = "https://tfwiki.net/wiki/Optimus_Prime_(G1)#Generation_1"
    html = post_figure(auth_client, figure_form(seed, link=link))
    assert "Another figure already has this link" in html
    assert db.session.query(Figure).filter_by(link=link).count() == 2
    # A figure keeps its own link without a warning.
    path = "/figuremodelview/edit/%s" % seed["figure"].id
    other = db.session.query(Figure).filter_by(name="Form figure").one()
    assert "Another figure" not in post_figure(
        auth_client,
        figure_form(seed, name="Optimus Prime", link="https://x/unique"),
        path,
    )
    assert other.link == link


@pytest.mark.parametrize("category", ["Combiner", "Duocon", "Duobot"])
def test_gestalt_without_a_combining_category_warns(auth_client, seed, category):
    data = figure_form(seed, gestalt_of=[str(seed["figure"].id)])
    assert "Combiner, Duocon, Duobot categories" in post_figure(auth_client, data)
    db.session.add(Category(name=category))
    db.session.commit()
    chosen = db.session.query(Category).filter_by(name=category).one()
    data = figure_form(
        seed,
        name="Second",
        gestalt_of=[str(seed["figure"].id)],
        categories=[str(chosen.id)],
    )
    assert "categories is" not in post_figure(auth_client, data)


def test_delete_a_character_in_use_is_refused(auth_client, seed):
    resp = auth_client.get(
        "/charactermodelview/delete/%s" % seed["character"].id,
        follow_redirects=True,
    )
    assert resp.status_code == 200
    db.session.expire_all()
    assert db.session.query(Figure).count() == 1


def test_filters_by_character_continuity_family_and_ancestor(auth_client, seed):
    other = db.session.query(Figure).filter_by(name="Optimus Prime").one()
    db.session.add(
        Figure(
            name="Elsewhere",
            release_year=2000,
            faction=other.faction,
            character_new=None,
        )
    )
    db.session.commit()

    def names(query):
        html = auth_client.get("/figuremodelview/list/?" + query).get_data(as_text=True)
        return {
            n
            for n in ("Optimus Prime", "Elsewhere")
            if "/figuremodelview/show/%s"
            % db.session.query(Figure).filter_by(name=n).one().id
            in html
        }

    assert names("_flt_0_character_new=%s" % seed["character"].id) == {"Optimus Prime"}
    assert names("_flt_0_continuity=%s" % seed["continuity"].id) == {"Optimus Prime"}
    assert names("_flt_0_family=%s" % seed["family"].id) == {"Optimus Prime"}
    assert names("_flt_0_ancestors=https://tfwiki.net/wiki/Diaclone_Convoy") == {
        "Optimus Prime"
    }
    assert names("_flt_0_ancestors=https://tfwiki.net/wiki/Nobody") == set()
    assert names(
        "_flt_2_accessories_text=Axe"
    )  # index 2 is "contains" == {"Optimus Prime"}


def test_the_figure_page_marks_figures_in_the_collection(auth_client, seed):
    db.session.add(
        Figure(
            name="The Ancestor",
            release_year=1983,
            faction=db.session.query(Faction).one(),
            link="https://tfwiki.net/wiki/Diaclone_Convoy",
        )
    )
    db.session.commit()
    html = auth_client.get("/figuremodelview/show/%s" % seed["figure"].id).get_data(
        as_text=True
    )
    assert "In collection" in html
    assert "Other figures from this ancestor" in html
    assert "_flt_0_ancestors=https://tfwiki.net/wiki/Diaclone_Convoy" in html
    # Pack-mates are links and "In collection" only.
    assert html.count("Other figures from this ancestor") == 1


def test_empty_link_and_accessories_are_saved_as_none(auth_client, seed):
    post_figure(auth_client, figure_form(seed, link="  ", accessories_text=" "))
    fig = db.session.query(Figure).filter_by(name="Form figure").one()
    assert fig.link is None and fig.accessories_text is None
    path = "/figuremodelview/edit/%s" % fig.id
    post_figure(
        auth_client,
        figure_form(seed, link=" https://x/y ", accessories_text=" A, B "),
        path,
    )
    db.session.expire_all()
    fig = db.session.get(Figure, fig.id)
    assert fig.link == "https://x/y" and fig.accessories_text == "A, B"


def test_two_figures_can_be_added_with_a_blank_legacy_id(auth_client, seed):
    # The form sends "" for the empty legacy_id box, and the column is unique.
    link = "https://tfwiki.net/wiki/Same#Link"
    for name in ("First", "Second"):
        html = post_figure(
            auth_client, figure_form(seed, name=name, link=link, legacy_id="")
        )
        assert "Duplicate entry" not in html
    figures = db.session.query(Figure).filter(Figure.name.in_(["First", "Second"]))
    assert [f.legacy_id for f in figures] == [None, None]
    assert figures.count() == 2


def test_other_forms_also_accept_a_blank_legacy_id_twice(auth_client):
    for name in ("One", "Two"):
        auth_client.post(
            "/factionmodelview/add",
            data={"name": name, "legacy_id": ""},
            follow_redirects=True,
        )
    assert (
        db.session.query(Faction).filter(Faction.name.in_(["One", "Two"])).count() == 2
    )


def test_the_figure_page_has_continuity_and_family_sections(auth_client, seed):
    html = auth_client.get("/figuremodelview/show/%s" % seed["figure"].id).get_data(
        as_text=True
    )
    assert re.search(r"<th[^>]*>\s*Continuity\s*</th>", html)
    assert re.search(r"<th[^>]*>\s*Continuity Family\s*</th>", html)
    assert "/continuitymodelview/show/%s" % seed["continuity"].id in html
    assert "/continuityfamilymodelview/show/%s" % seed["family"].id in html


def test_the_figure_form_drop_downs_are_in_name_order(auth_client, seed):
    from app.models import Character

    db.session.add_all(
        Character(name=n, link="https://tfwiki.net/wiki/" + n)
        for n in ("Zed", "Alpha", "Mid")
    )
    db.session.commit()
    html = auth_client.get("/figuremodelview/add").get_data(as_text=True)
    from app.models import Continuity

    continuity = db.session.get(Continuity, seed["continuity"].id).name
    names = ["Alpha", "Mid", "Optimus Prime (%s)" % continuity, "Zed"]
    positions = [html.index(">%s</option>" % n) for n in names]
    assert positions == sorted(positions)


def test_the_character_drop_down_shows_each_characters_continuity(auth_client, seed):
    from app.models import Character, Continuity

    prime = Continuity(name="Prime")
    db.session.add_all(
        [
            prime,
            Character(name="Arcee", link="https://tfwiki.net/wiki/Arcee_(G1)"),
            Character(
                name="Arcee",
                link="https://tfwiki.net/wiki/Arcee_(Prime)",
                continuity=prime,
            ),
        ]
    )
    db.session.commit()
    for path in ("add", "edit/%s" % seed["figure"].id):
        html = auth_client.get("/figuremodelview/" + path).get_data(as_text=True)
        assert ">Arcee</option>" in html  # no continuity: just the name
        assert ">Arcee (Prime)</option>" in html


def test_the_reference_boxes_are_full_width_and_tall(auth_client, seed):
    html = auth_client.get("/figuremodelview/add").get_data(as_text=True)
    for field in ("history_text", "packed_with_text"):
        tag = re.search(r'<textarea[^>]*name="%s"[^>]*>' % field, html).group(0)
        assert 'class="form-control"' in tag and 'rows="8"' in tag


def test_the_menu_groups_the_lookup_lists(auth_client, seed):
    page = auth_client.get("/").get_data(as_text=True)
    nav = page.split("navbar", 1)[1]
    for entry in ("Figures", "Add from TFWiki", "Characters", "Classification"):
        assert entry in nav
    for group, members in (
        ("Classification", ("Franchises", "Factions", "Toolings", "Categories")),
        ("Characters", ("Characters", "Continuities", "Continuity Families")),
    ):
        menu = flask_app.appbuilder.menu.find(group)
        assert [m.name for m in menu.childs] == list(members)


def test_the_menu_order(auth_client, seed):
    names = [m.name for m in flask_app.appbuilder.menu.get_list()]
    ours = [n for n in names if n != "Security"]
    assert ours == ["Figures", "Add from TFWiki", "Characters", "Classification"]
