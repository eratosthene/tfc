"""The "Use this picture" button on Add from TFWiki."""

import json
import os

import pytest

from app import app as flask_app, db
from app import pictures
from app.models import Figure
from app.tfwiki.fetcher import FetchError, RateLimited, cache_name
from test_addfigure import ALPHA, WIKI, form, lookup, page_values

PICTURE_URL = WIKI + "Special:FilePath/Legacy-toy_AlphaTrion.jpg"


def press(client, seed, button="picture", **changes):
    return client.post(
        "/addfromtfwiki/" + button, data=form(seed, url=ALPHA, **changes)
    ).get_data(as_text=True)


def held(html):
    return page_values(html).get("image", "")


def exists(name):
    return os.path.exists(os.path.join(flask_app.config["IMG_UPLOAD_FOLDER"], name))


def test_the_review_offers_the_button_but_downloads_nothing(auth_client, online, seed):
    html = lookup(auth_client, ALPHA)
    assert "Use this picture" in html and "Remove this picture" not in html
    assert "Nothing is downloaded unless you press this." in html
    assert online.pictures == []


def test_the_button_downloads_the_picture_and_the_review_shows_it(
    auth_client, online, seed
):
    html = press(auth_client, seed)
    assert online.pictures == [PICTURE_URL]
    name = held(html)
    assert pictures.SAVED_NAME.match(name) and exists(name)
    assert "Downloaded and ready" in html and "Remove this picture" in html
    assert "Download it again" in html
    assert pictures.thumbnail_name(name) in html  # the preview is the saved thumbnail
    assert db.session.query(Figure).filter_by(name="Alpha Trion").count() == 0
    pictures.discard(name)


def test_what_was_typed_survives_the_button(auth_client, online, seed):
    html = press(auth_client, seed, name="Typed name", accessories_text="A, B")
    values = page_values(html)
    assert values["name"] == "Typed name" and "A, B" in values["accessories_text"]
    pictures.discard(held(html))


def test_saving_attaches_the_picture_to_the_new_figure(auth_client, online, seed):
    name = held(press(auth_client, seed))
    resp = auth_client.post("/addfromtfwiki/save", data=form(seed, image=name))
    assert resp.status_code == 302
    figure = db.session.query(Figure).filter_by(name="Alpha Trion").one()
    assert figure.image == name and pictures.in_use(name) and exists(name)
    assert (
        auth_client.get("/figuremodelview/figure_img/%s" % figure.id).status_code == 200
    )


def test_a_second_press_replaces_an_unused_picture(auth_client, online, seed):
    first = held(press(auth_client, seed))
    second = held(press(auth_client, seed, image=first))
    assert first != second and exists(second) and not exists(first)
    assert not exists(pictures.thumbnail_name(first))
    pictures.discard(second)


def test_a_failed_download_keeps_the_earlier_picture(auth_client, online, seed):
    first = held(press(auth_client, seed))
    online.picture = FetchError("boom")
    html = press(auth_client, seed, image=first)
    assert "Could not use the picture: boom" in html
    assert held(html) == first and exists(first)
    pictures.discard(first)


@pytest.mark.parametrize(
    "outcome, message",
    [
        (RateLimited("429"), "asked us to slow down"),
        ((b"not a picture", "image/jpeg"), "Could not use the picture: Invalid image"),
    ],
)
def test_other_download_problems_are_messages(
    auth_client, online, seed, outcome, message
):
    online.picture = outcome
    html = press(auth_client, seed)
    assert message in html and held(html) == ""


def test_with_fetching_off_the_button_says_so(auth_client, cached, seed):
    html = press(auth_client, seed)
    assert "Downloading from tfwiki.net is off" in html and held(html) == ""


def test_removing_a_picture_deletes_it_if_nothing_uses_it(auth_client, online, seed):
    name = held(press(auth_client, seed))
    html = press(auth_client, seed, "discard_picture", image=name)
    assert held(html) == "" and not exists(name) and "Remove this picture" not in html


def test_removing_never_deletes_a_picture_in_use(auth_client, online, seed):
    name = held(press(auth_client, seed))
    figure = db.session.get(Figure, seed["figure"].id)
    figure.image = name
    db.session.commit()
    press(auth_client, seed, "discard_picture", image=name)
    assert exists(name)
    figure.image = None
    db.session.commit()
    pictures.discard(name)


def test_saving_with_a_picture_that_is_gone_is_an_error(auth_client, online, seed):
    gone = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa_sep_gone.jpg"
    html = auth_client.post(
        "/addfromtfwiki/save", data=form(seed, image=gone)
    ).get_data(as_text=True)
    assert "downloaded picture is no longer there" in html
    assert db.session.query(Figure).filter_by(name="Alpha Trion").count() == 0


def test_a_figure_the_wiki_has_no_picture_for(
    auth_client, online, seed, tmp_path, monkeypatch
):
    page = "Mover is an [[Autobot]] from the [[Generation 1 continuity family]].\n==Toys==\n===''The Line''===\n:''Prose only.''\n"
    folder = tmp_path / "nopic"
    folder.mkdir()
    (folder / cache_name("Mover_(G1)")).write_text(
        json.dumps({"parse": {"title": "Mover (G1)", "wikitext": {"*": page}}})
    )
    monkeypatch.setitem(flask_app.config, "TFWIKI_CACHE_DIR", str(folder))
    monkeypatch.setattr(
        "app.addfigure.make_fetcher",
        lambda refreshing=False: __import__(
            "app.tfwiki.fetcher", fromlist=["Fetcher"]
        ).Fetcher(str(folder), enabled=True, get_bytes=lambda u: pytest.fail(u)),
    )
    url = WIKI + "Mover_(G1)#The_Line"
    assert "Use this picture" not in lookup(auth_client, url)
    html = auth_client.post(
        "/addfromtfwiki/picture", data=form(seed, url=url)
    ).get_data(as_text=True)
    assert "The wiki has no picture for this figure." in html


def test_the_picture_buttons_report_page_problems(auth_client, cached, seed):
    html = auth_client.post(
        "/addfromtfwiki/picture", data=form(seed, url=WIKI + "Not_Cached_Page#X")
    ).get_data(as_text=True)
    assert "not in the cache" in html
    html = auth_client.post(
        "/addfromtfwiki/picture", data=form(seed, url=ALPHA, pick="7")
    ).get_data(as_text=True)
    assert "Pick one of the figures listed." in html


def test_the_picture_buttons_need_a_token(auth_client, cached, seed, csrf_on):
    for path in ("/addfromtfwiki/picture", "/addfromtfwiki/discard_picture"):
        resp = auth_client.post(path, data=form(seed, url=ALPHA))
        assert resp.status_code == 400
        assert "This page has expired" in resp.get_data(as_text=True)


def test_the_picture_buttons_need_a_login(client, seed):
    for path in ("/addfromtfwiki/picture", "/addfromtfwiki/discard_picture"):
        resp = client.post(path, data=form(seed, url=ALPHA))
        assert resp.status_code == 302 and "/login/" in resp.headers["Location"]
