"""Refresh a figure from its own tfwiki.net link, accepting or skipping each change."""

import json
import os
import re

import pytest

from app import app as flask_app, appbuilder, db
from app import pictures, refresh
from app.models import (
    Category,
    Faction,
    Figure,
    Franchise,
    Tooling,
)
from app.tfwiki.fetcher import FetchError, RateLimited, cache_name
from test_addfigure import WIKI

TOYS = WIKI + "Alpha_Trion/toys#Legacy"  # recorded; matches by heading, one figure


def figure_for(seed, link=TOYS, **changes):
    """The seed figure, pointed at a link (and changed as asked)."""
    figure = db.session.get(Figure, seed["figure"].id)
    figure.link = link
    for key, value in changes.items():
        setattr(figure, key, value)
    db.session.commit()
    return figure.id


def compare(client, pk, **data):
    return client.post("/refreshfigure/%s/compare" % pk, data=data).get_data(
        as_text=True
    )


def apply(client, pk, **data):
    data.setdefault("pick", "0")
    return client.post("/refreshfigure/%s/apply" % pk, data=data)


def choice(html, key):
    """'accept' or 'skip': the radio that is checked for this change."""
    found = re.search(r'name="choice_%s" value="(accept|skip)" checked' % key, html)
    return found.group(1) if found else None


def labels(html):
    """The field names in the diff table's rows (not its header row)."""
    body = html.split("<tbody>", 1)[-1]
    return re.findall(r"<tr>\s*<th>([^<]+)</th>", body)


def refetch(pk):
    db.session.expire_all()
    return db.session.get(Figure, pk)


# --- the comparison ------------------------------------------------------------------


def test_the_diff_lists_only_what_differs(auth_client, cached, seed):
    db.session.add(Tooling(name="Retool"))
    db.session.commit()
    pk = figure_for(seed)
    html = compare(auth_client, pk)
    assert labels(html) == [
        "Name",
        "Release year",
        "Tooling",
        "Accessories",
        "Model History",
        "Packed With",
        "Picture",
    ]  # the faction, link and franchise already agree
    assert "A Hero is Born" in html and "Rifle, Vector Sigma" in html
    assert "Scourge | " + WIKI + "Scourge_(G1)/toys#Studio_Series" in html
    assert "Legacy-toy_AlphaTrion.jpg" in html and "guessed from:" in html


def test_accept_is_only_pre_selected_where_the_figure_has_nothing_and_never_for_a_picture(
    auth_client, cached, seed
):
    pk = figure_for(seed, accessories_text=None, name="Keep me")
    html = compare(auth_client, pk)
    assert choice(html, "name") == "skip"  # the figure has a name
    assert choice(html, "accessories_text") == "accept"  # it has none
    assert choice(html, "picture") == "skip"
    assert choice(html, "history") == "skip"  # it has an ancestor already


def test_the_diff_never_proposes_to_empty_a_field_or_remove_anything(
    auth_client, cached, seed
):
    figure = db.session.get(Figure, seed["figure"].id)
    figure.link = WIKI + "Boater#Zone"  # a figure the wiki has little to say about
    figure.hasbro_id = "KEEP"
    db.session.commit()
    html = compare(auth_client, figure.id)
    assert "Hasbro ID" not in labels(html)
    assert "Franchise" not in labels(html) or "add " in html
    assert all("remove" not in row.lower() for row in labels(html))


def test_a_franchise_the_figure_has_through_a_tagged_child_is_not_proposed(
    auth_client, cached, seed
):
    legacy = Franchise(name="Legacy", start_year=2022)
    united = Franchise(name="Legacy United", start_year=2024, parent=legacy)
    db.session.add_all([legacy, united])
    db.session.commit()
    pk = figure_for(seed)
    figure = refetch(pk)
    figure.franchise = [united]
    db.session.commit()
    assert "Franchise" not in labels(compare(auth_client, pk))
    figure.franchise = []
    db.session.commit()
    html = compare(auth_client, pk)
    assert "Franchise" in labels(html) and "add Legacy" in html


def test_additions_to_tooling_categories_and_franchise_and_a_changed_faction_and_link(
    auth_client, cached, seed
):
    retool = Tooling(name="Retool")
    pack = Category(name="2-pack")
    legacy = Franchise(name="Legacy", start_year=2022)
    decepticon = Faction(name="Decepticon")
    db.session.add_all([retool, pack, legacy, decepticon])
    db.session.commit()
    pk = figure_for(seed, link=WIKI + "Alpha_Trion_(G1)#Legacy", faction=decepticon)
    html = compare(auth_client, pk)
    for label in ("Faction", "Link to Figure", "Franchise", "Tooling", "Categories"):
        assert label in labels(html)
    assert "add Retool" in html and "add 2-pack" in html and "add Legacy" in html
    assert WIKI + "Alpha_Trion/toys#Legacy" in html and "from Bp-a1" in html


def test_nothing_differs_says_so(auth_client, tmp_path, monkeypatch, seed):
    page = "Mover is an [[Autobot]] from the [[Generation 1 continuity family]].\n==Toys==\n===''The Line''===\n:''Prose only.''\n"
    folder = tmp_path / "plain"
    folder.mkdir()
    (folder / cache_name("Mover_(G1)")).write_text(
        json.dumps({"parse": {"title": "Mover (G1)", "wikitext": {"*": page}}})
    )
    monkeypatch.setitem(flask_app.config, "TFWIKI_CACHE_DIR", str(folder))
    monkeypatch.setitem(flask_app.config, "TFWIKI_ENABLED", False)
    pk = figure_for(seed, link=WIKI + "Mover_(G1)#The_Line")
    html = compare(auth_client, pk)
    assert (
        "Nothing on the wiki page differs" in html and "Apply the accepted" not in html
    )


def test_refresh_fetches_and_compare_uses_the_cached_copy(auth_client, online, seed):
    pk = figure_for(seed)
    compare(auth_client, pk)
    assert "Alpha_Trion/toys" not in online.pages
    compare(auth_client, pk, refresh="1")
    assert "Alpha_Trion/toys" in online.pages


def test_refresh_with_fetching_off_says_so(auth_client, cached, seed):
    html = compare(auth_client, figure_for(seed), refresh="1")
    assert "fetching from tfwiki.net is off" in html


def test_a_figure_with_no_link_or_a_page_that_is_not_cached(auth_client, cached, seed):
    assert "This figure has no link." in compare(
        auth_client, figure_for(seed, link=None)
    )
    html = compare(auth_client, figure_for(seed, link=WIKI + "Not_Cached_Page#X"))
    assert "not in the cache" in html
    html = compare(
        auth_client, figure_for(seed, link=WIKI + "Alpha_Trion/toys#Nonesuch")
    )
    assert "No figure for #Nonesuch" in html and "<li>SDCC2015</li>" in html


def test_a_link_that_matches_several_figures_asks_which(auth_client, cached, seed):
    pk = figure_for(seed, link=WIKI + "Blackarachnia_(BW)/toys#Beast_Machines")
    html = compare(auth_client, pk)
    assert "has 2 figures under that link" in html and html.count("This one") == 2
    picked = compare(auth_client, pk, pick="1")
    assert (
        "Apply the accepted changes" in picked
        or "Nothing on the wiki page differs" in picked
    )
    assert "Pick one of the figures listed." in compare(auth_client, pk, pick="9")


def test_an_unknown_figure_is_a_404(auth_client, cached, seed):
    assert auth_client.post("/refreshfigure/9999/compare").status_code == 404


# --- applying ------------------------------------------------------------------------


def test_only_the_accepted_changes_are_saved(auth_client, cached, seed):
    pk = figure_for(seed)
    resp = apply(
        auth_client,
        pk,
        choice_name="accept",
        choice_release_year="accept",
        choice_history="accept",
        choice_accessories_text="skip",
        choice_packed_with="skip",
    )
    assert (
        resp.status_code == 302
        and "/figuremodelview/show/%s" % pk in resp.headers["Location"]
    )
    figure = refetch(pk)
    assert figure.name == "A Hero is Born" and figure.release_year == 2022
    assert figure.accessories_text == "Blaster, Axe"  # skipped
    ancestors = [
        (r.position, r.name) for r in figure.references if r.kind == "ancestor"
    ]
    assert ancestors == [
        (0, "Diaclone Convoy"),
        (1, "Scourge"),
    ]  # added after what was there
    assert [r.name for r in figure.references if r.kind == "packed_with"] == ["Roller"]
    shown = auth_client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "Updated A Hero is Born: name, release year, model history." in shown


def test_every_kind_of_change_can_be_applied(auth_client, cached, seed):
    retool = Tooling(name="Retool")
    pack = Category(name="2-pack")
    legacy = Franchise(name="Legacy", start_year=2022)
    decepticon = Faction(name="Decepticon")
    db.session.add_all([retool, pack, legacy, decepticon])
    db.session.commit()
    pk = figure_for(seed, link=WIKI + "Alpha_Trion_(G1)#Legacy", faction=decepticon)
    keys = (
        "name",
        "release_year",
        "faction",
        "link",
        "franchise",
        "tooling",
        "categories",
        "accessories_text",
        "history",
        "packed_with",
    )
    resp = apply(auth_client, pk, **{"choice_" + k: "accept" for k in keys})
    assert resp.status_code == 302
    figure = refetch(pk)
    assert (
        figure.faction.name == "Autobot"
        and figure.link == WIKI + "Alpha_Trion/toys#Legacy"
    )
    assert [f.name for f in figure.franchise][-1] == "Legacy"
    assert "Retool" in [t.name for t in figure.tooling] and "2-pack" in [
        c.name for c in figure.categories
    ]
    assert figure.accessories_text.startswith("Rifle, Vector Sigma")
    assert sorted(r.name for r in figure.references) == [
        "Diaclone Convoy",
        "Orion Pax",
        "Roller",
        "Scourge",
    ]


def test_ids_from_the_wiki_can_replace_the_figures(
    auth_client, tmp_path, monkeypatch, seed
):
    page = (
        "==Toys==\n===''The Line''===\n{{anchor|One}}\n"
        "<ul class=\"iconlist\">{{Bp-a1|'''Mover''' (Deluxe Class, 2001)}}</ul>\n"
        ":*''Hasbro ID number'': '''E1'''\n:*''Takara ID number'': '''T2'''\n"
    )
    folder = tmp_path / "ids"
    folder.mkdir()
    (folder / cache_name("Mover_(G1)")).write_text(
        json.dumps({"parse": {"title": "Mover (G1)", "wikitext": {"*": page}}})
    )
    monkeypatch.setitem(flask_app.config, "TFWIKI_CACHE_DIR", str(folder))
    monkeypatch.setitem(flask_app.config, "TFWIKI_ENABLED", False)
    pk = figure_for(seed, link=WIKI + "Mover_(G1)#One", hasbro_id="OLD")
    html = compare(auth_client, pk)
    assert "Hasbro ID" in labels(html) and "Takara ID" in labels(html)
    assert choice(html, "hasbro_id") == "skip" and choice(html, "takara_id") == "accept"
    apply(auth_client, pk, choice_hasbro_id="accept", choice_takara_id="accept")
    figure = refetch(pk)
    assert (figure.hasbro_id, figure.takara_id) == ("E1", "T2")


def test_accepting_nothing_changes_nothing(auth_client, cached, seed):
    pk = figure_for(seed)
    before = refetch(pk).name
    resp = apply(auth_client, pk)
    assert (
        resp.status_code == 302
        and "/figuremodelview/edit/%s" % pk in resp.headers["Location"]
    )
    assert refetch(pk).name == before
    assert "Nothing was accepted" in auth_client.get(resp.headers["Location"]).get_data(
        as_text=True
    )


def test_apply_when_the_page_has_gone_or_the_pick_is_wrong(auth_client, cached, seed):
    pk = figure_for(seed, link=WIKI + "Not_Cached_Page#X")
    html = apply(auth_client, pk, choice_name="accept").get_data(as_text=True)
    assert "not in the cache" in html
    pk = figure_for(seed)
    html = apply(auth_client, pk, pick="9", choice_name="accept").get_data(as_text=True)
    assert "Pick one of the figures listed." in html
    assert refetch(pk).name != "A Hero is Born"


# --- the picture -----------------------------------------------------------------------


def exists(name):
    return os.path.exists(os.path.join(flask_app.config["IMG_UPLOAD_FOLDER"], name))


def test_an_accepted_picture_is_downloaded_and_attached(auth_client, online, seed):
    pk = figure_for(seed)
    resp = apply(auth_client, pk, choice_picture="accept")
    assert resp.status_code == 302
    assert online.pictures == [WIKI + "Special:FilePath/Legacy-toy_AlphaTrion.jpg"]
    figure = refetch(pk)
    assert pictures.SAVED_NAME.match(figure.image) and exists(figure.image)
    assert auth_client.get("/figuremodelview/figure_img/%s" % pk).status_code == 200


def test_a_skipped_picture_downloads_nothing(auth_client, online, seed):
    apply(auth_client, figure_for(seed), choice_name="accept", choice_picture="skip")
    assert online.pictures == []


def test_replacing_a_picture_keeps_the_old_file(auth_client, online, seed):
    pk = figure_for(seed)
    old = pictures.download_picture(
        refresh.make_fetcher(),
        {"file": "Old.jpg", "url": WIKI + "Special:FilePath/Old.jpg"},
    )
    figure = refetch(pk)
    figure.image = old
    db.session.commit()
    html = compare(auth_client, pk)
    assert "the old file is kept on disk" in html
    apply(auth_client, pk, choice_picture="accept")
    assert refetch(pk).image != old and exists(old)


@pytest.mark.parametrize(
    "outcome, message",
    [
        (FetchError("boom"), "Could not use the picture: boom"),
        (RateLimited("429"), "asked us to slow down"),
        ((b"junk", "image/jpeg"), "Could not use the picture: Invalid image"),
    ],
)
def test_a_failed_download_saves_nothing_and_keeps_the_choices(
    auth_client, online, seed, outcome, message
):
    online.picture = outcome
    pk = figure_for(seed)
    html = apply(
        auth_client, pk, choice_picture="accept", choice_name="accept"
    ).get_data(as_text=True)
    assert message in html and "Nothing was saved." in html
    assert choice(html, "picture") == "accept" and choice(html, "name") == "accept"
    figure = refetch(pk)
    assert figure.name == "Optimus Prime" and figure.image is None


def test_a_picture_with_fetching_off_is_refused_without_saving(
    auth_client, cached, seed
):
    pk = figure_for(seed)
    html = apply(
        auth_client, pk, choice_picture="accept", choice_name="accept"
    ).get_data(as_text=True)
    assert "Downloading from tfwiki.net is off" in html and "Nothing was saved." in html
    assert refetch(pk).name == "Optimus Prime"


# --- who may, and the Edit page ---------------------------------------------------------


def test_applying_needs_permission_to_edit_figures(
    auth_client, cached, seed, monkeypatch
):
    real = appbuilder.sm.has_access
    monkeypatch.setattr(
        appbuilder.sm,
        "has_access",
        lambda permission, view: False
        if (permission, view) == ("can_edit", "FigureModelView")
        else real(permission, view),
    )
    pk = figure_for(seed)
    assert apply(auth_client, pk, choice_name="accept").status_code == 403
    assert refetch(pk).name == "Optimus Prime"


def test_the_buttons_need_a_token(auth_client, cached, seed, csrf_on):
    pk = figure_for(seed)
    assert auth_client.post("/refreshfigure/%s/compare" % pk).status_code == 400
    assert (
        auth_client.post(
            "/refreshfigure/%s/apply" % pk, data={"choice_name": "accept"}
        ).status_code
        == 400
    )
    assert refetch(pk).name == "Optimus Prime"


def test_the_buttons_need_a_login(client, cached, seed):
    pk = figure_for(seed)
    for path in ("compare", "apply"):
        resp = client.post("/refreshfigure/%s/%s" % (pk, path))
        assert resp.status_code == 302 and "/login/" in resp.headers["Location"]


def test_the_edit_page_has_the_refresh_panel(auth_client, cached, seed):
    pk = figure_for(seed)
    html = auth_client.get("/figuremodelview/edit/%s" % pk).get_data(as_text=True)
    assert "Refresh from TFWiki" in html and "Compare with the cached copy" in html
    assert 'action="/refreshfigure/%s/compare"' % pk in html and TOYS in html
    assert 'name="refresh" value="1"' in html


def test_the_edit_page_for_a_figure_with_no_link_says_how_to_get_the_button(
    auth_client, cached, seed
):
    pk = figure_for(seed, link=None)
    html = auth_client.get("/figuremodelview/edit/%s" % pk).get_data(as_text=True)
    assert (
        "Save a tfwiki.net link on this figure" in html
        and "Refresh from TFWiki" not in html
    )


# --- the small rules -------------------------------------------------------------------


def test_same_link_ignores_spelling_but_not_the_fragment():
    same = refresh.same_link
    assert same(WIKI + "A_B#C", WIKI + "A%20B#C")
    assert same("https://www.tfwiki.net/wiki/A#C", WIKI + "A#C")
    assert not same(WIKI + "A#C", WIKI + "A#D")
    assert not same(WIKI + "A#C", WIKI + "B#C")
    assert same("not a link", "not a link") and not same("not a link", "other")


def test_same_text_ignores_spacing():
    assert refresh.same_text("A,  B\n", "A, B") and refresh.same_text(None, "")
    assert not refresh.same_text("A, B", "A, C")


@pytest.mark.parametrize(
    "mine, wiki, expected",
    [
        ("Dreadwind", "Dreadwind & Smokejumper", True),
        ("Beastbox", "Squawktalk / Beastbox", True),
        ("War Breakdown", "War Breakdown and Vehicon 2-Pack", True),
        ("Buzzsaw", "Bumblebee Cassette Pack", False),  # not one of its parts
        ("Apex Bomber", "Powermaster Optimus Prime with Apex Armor", False),
        ("Optimus", "Optimus Prime", False),  # a fuller name, not a pack
        ("", "A & B", False),
        ("Dread", "Dreadwind & Smokejumper", False),  # whole words only
    ],
)
def test_a_pack_name_that_contains_the_figures_name_is_not_a_rename(
    mine, wiki, expected
):
    assert refresh.is_part_of_pack(mine, wiki) is expected


def test_pack_names_and_capital_letters_do_not_make_noise(auth_client, cached, seed):
    pk = figure_for(
        seed,
        name="Orion Pax",
        accessories_text="rifle, vector sigma, key to vector sigma, STAND",
    )
    # The wiki's name for the figure is "A Hero is Born" (a pack name), which does not
    # contain "Orion Pax", so the rename is still proposed; the accessories differ
    # only in capitals, so they are not.
    html = compare(auth_client, pk)
    assert "Name" in labels(html) and "Accessories" not in labels(html)
    figure = refetch(pk)
    figure.name = "A Hero is Born"
    db.session.commit()
    assert "Name" not in labels(compare(auth_client, pk))
