"""Downloading a picture from tfwiki.net and saving it like an upload."""

import io
import os
import urllib.error
import urllib.request

import pytest
from PIL import Image

from app import app as flask_app, db
from app import pictures
from app.models import Faction, Figure
from app.tfwiki import fetcher as fetcher_module
from app.tfwiki.fetcher import (
    Disabled,
    FetchError,
    Fetcher,
    PageNotFound,
    RateLimited,
    http_get_bytes,
    on_site,
)

PICTURE = {
    "file": "Legacy-toy_AlphaTrion.png",
    "url": "https://tfwiki.net/wiki/Special:FilePath/Legacy-toy_AlphaTrion.png",
}


def image_bytes(size=(400, 300), fmt="PNG", color="red"):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    return buf.getvalue()


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def wall(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def downloader(tmp_path, reply, enabled=True, clock=None):
    clock = clock or Clock()
    seen = []

    def get_bytes(url):
        seen.append(url)
        if isinstance(reply, Exception):
            raise reply
        return reply

    fetcher = Fetcher(
        str(tmp_path),
        enabled=enabled,
        get_bytes=get_bytes,
        sleep=clock.sleep,
        wall=clock.wall,
    )
    return fetcher, seen, clock


# --- the fetcher's download ---------------------------------------------------------


def test_download_is_off_unless_fetching_is_on(tmp_path):
    fetcher, seen, _ = downloader(tmp_path, (b"x", "image/png"), enabled=False)
    with pytest.raises(Disabled, match="Downloading from tfwiki.net is off"):
        fetcher.download(PICTURE["url"])
    assert seen == []


def test_download_waits_its_turn_like_a_page_does(tmp_path):
    fetcher, seen, clock = downloader(tmp_path, (b"data", "image/png"))
    assert fetcher.download("https://tfwiki.net/a.png") == (b"data", "image/png")
    fetcher.download("https://tfwiki.net/b.png")
    assert clock.slept == [pytest.approx(2.0)] and len(seen) == 2


def test_a_rate_limited_download_stops_later_requests(tmp_path):
    fetcher, _, _ = downloader(tmp_path, RateLimited("429"))
    with pytest.raises(RateLimited):
        fetcher.download("https://tfwiki.net/a.png")
    with pytest.raises(RateLimited, match="rate limited us earlier"):
        fetcher.download("https://tfwiki.net/b.png")


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://tfwiki.net/images/a.png", True),
        ("https://www.tfwiki.net/images/a.png", True),
        ("https://static.tfwiki.net/a.png", True),
        ("http://tfwiki.net/a.png", False),  # not https
        ("https://tfwiki.net.evil.example/a.png", False),
        ("https://eviltfwiki.net/a.png", False),
        ("https://example.com/a.png", False),
        ("not a url", False),
    ],
)
def test_on_site(url, expected):
    assert on_site(url) is expected


class FakeResponse:
    def __init__(self, data, kind="image/png"):
        self.data = data
        self.headers = type("H", (), {"get_content_type": lambda self_: kind})()

    def read(self, n=-1):
        return self.data[:n] if n >= 0 else self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_returning(monkeypatch, outcome):
    class Opener:
        def open(self, req, timeout=None):
            self.request = req
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    opener = Opener()
    monkeypatch.setattr(
        fetcher_module.urllib.request, "build_opener", lambda *h: opener
    )
    return opener


def test_http_get_bytes_returns_the_picture_and_says_who_is_asking(monkeypatch):
    opener = opener_returning(monkeypatch, FakeResponse(b"abc", "image/jpeg"))
    assert http_get_bytes("https://tfwiki.net/x.jpg") == (b"abc", "image/jpeg")
    assert opener.request.headers["User-agent"].startswith("tfc-importer")
    assert opener.request.headers["Accept"] == "image/*"


def test_http_get_bytes_refuses_other_sites_and_non_images_and_big_files(monkeypatch):
    with pytest.raises(FetchError, match="Only pictures from tfwiki.net"):
        http_get_bytes("https://example.com/x.jpg")
    opener_returning(monkeypatch, FakeResponse(b"<html>", "text/html"))
    with pytest.raises(FetchError, match="not a picture"):
        http_get_bytes("https://tfwiki.net/x")
    opener_returning(monkeypatch, FakeResponse(b"x" * 11, "image/png"))
    with pytest.raises(FetchError, match="larger than 0 MB"):
        http_get_bytes("https://tfwiki.net/x", limit=10)


@pytest.mark.parametrize(
    "code, error",
    [(429, RateLimited), (503, RateLimited), (404, PageNotFound), (500, FetchError)],
)
def test_http_errors_become_fetch_errors(monkeypatch, code, error):
    http = urllib.error.HTTPError("https://tfwiki.net/x", code, "m", {}, None)
    opener_returning(monkeypatch, http)
    with pytest.raises(error):
        http_get_bytes("https://tfwiki.net/x")


def test_a_network_failure_is_a_fetch_error(monkeypatch):
    opener_returning(monkeypatch, urllib.error.URLError("no route"))
    with pytest.raises(FetchError, match="no route"):
        http_get_bytes("https://tfwiki.net/x")


def test_redirects_may_not_leave_tfwiki_net():
    handler = fetcher_module._StayOnSite()
    req = urllib.request.Request("https://tfwiki.net/wiki/Special:FilePath/X.png")
    ok = handler.redirect_request(
        req, None, 302, "Found", {}, "https://tfwiki.net/images/X.png"
    )
    assert ok.full_url == "https://tfwiki.net/images/X.png"
    with pytest.raises(FetchError, match="redirected away from tfwiki.net"):
        handler.redirect_request(
            req, None, 302, "Found", {}, "https://elsewhere.example/X.png"
        )


# --- saving it ------------------------------------------------------------------------


def upload_folder():
    return flask_app.config["IMG_UPLOAD_FOLDER"]


def test_a_picture_is_saved_like_an_upload(tmp_path):
    fetcher, seen, _ = downloader(tmp_path, (image_bytes(), "image/png"))
    name = pictures.download_picture(fetcher, PICTURE)
    assert seen == [PICTURE["url"]]
    assert pictures.SAVED_NAME.match(name) and name.endswith(
        "_sep_Legacy-toy_AlphaTrion.png"
    )
    folder = upload_folder()
    assert os.path.exists(os.path.join(folder, name))
    assert os.path.exists(os.path.join(folder, pictures.thumbnail_name(name)))
    assert pictures.is_pending(name)
    pictures.discard(name)


def test_a_big_picture_is_shrunk_to_the_figure_size_and_a_jpeg_stays_a_jpeg(tmp_path):
    big = image_bytes((3000, 2000), "JPEG")
    fetcher, _, _ = downloader(tmp_path, (big, "image/jpeg"))
    name = pictures.download_picture(fetcher, dict(PICTURE, file="Big photo.jpg"))
    assert name.endswith("_sep_Big_photo.jpg")
    saved = Image.open(os.path.join(upload_folder(), name))
    assert max(saved.size) <= 2000 and saved.format == "JPEG"
    thumb = Image.open(os.path.join(upload_folder(), pictures.thumbnail_name(name)))
    assert max(thumb.size) <= 300
    pictures.discard(name)


@pytest.mark.parametrize(
    "data, file, message",
    [
        (b"this is not a picture", "x.png", "Invalid image"),
        (image_bytes(), "x.svg", "not a picture type"),
        (image_bytes(), "日本", "no usable file name"),
    ],
)
def test_what_cannot_be_kept_is_refused(tmp_path, data, file, message):
    fetcher, _, _ = downloader(tmp_path, (data, "image/png"))
    with pytest.raises(ValueError, match=message):
        pictures.download_picture(fetcher, dict(PICTURE, file=file))
    assert not [f for f in os.listdir(upload_folder()) if f.endswith("x.png")]


def test_a_picture_is_pending_until_something_uses_it(tmp_path, seed):
    fetcher, _, _ = downloader(tmp_path, (image_bytes(), "image/png"))
    name = pictures.download_picture(fetcher, PICTURE)
    assert pictures.is_pending(name) and not pictures.in_use(name)
    figure = db.session.get(Figure, seed["figure"].id)
    figure.image = name
    db.session.commit()
    assert pictures.in_use(name) and not pictures.is_pending(name)
    assert pictures.discard(name) is False  # in use: left alone
    assert os.path.exists(os.path.join(upload_folder(), name))
    figure.image = None
    db.session.commit()
    assert pictures.discard(name) is True
    assert not os.path.exists(os.path.join(upload_folder(), name))
    assert not os.path.exists(
        os.path.join(upload_folder(), pictures.thumbnail_name(name))
    )
    assert pictures.discard(name) is False  # already gone


def test_discard_only_touches_files_this_app_saved(tmp_path):
    folder = upload_folder()
    for name in ("plain.png", "../escape.png", "", None):
        assert pictures.discard(name) is False
    outside = os.path.join(folder, "plain.png")
    with open(outside, "wb") as f:
        f.write(image_bytes())
    assert pictures.discard("plain.png") is False and os.path.exists(outside)
    os.remove(outside)


def test_a_faction_picture_counts_as_in_use():
    faction = Faction(
        name="Pic", image="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa_sep_f.png"
    )
    db.session.add(faction)
    db.session.commit()
    assert pictures.in_use(faction.image)
