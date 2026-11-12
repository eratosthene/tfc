"""The tfwiki.net fetcher: opt-in, cached, throttled, and stops when asked to."""

import io
import json
import os
import urllib.error
import urllib.parse

import pytest

from app.tfwiki import fetcher as fetcher_module
from app.tfwiki.fetcher import (
    Disabled,
    FetchError,
    Fetcher,
    PageNotFound,
    RateLimited,
    cache_name,
    fetcher_from_config,
    http_get,
    normalize_title,
    parse_response,
)

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures", "tfwiki")


def response(title="Some Page", text="wikitext"):
    return json.dumps({"parse": {"title": title, "wikitext": {"*": text}}})


class Clock:
    """A fake wall clock whose sleep moves it forward."""

    def __init__(self, now=1000.0):
        self.now = now
        self.slept = []

    def wall(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class Net:
    """A fake network that records its requests."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def make(tmp_path, *replies, enabled=True, clock=None, **kwargs):
    clock = clock or Clock()
    net = Net(*replies)
    f = Fetcher(
        str(tmp_path),
        enabled=enabled,
        get=net,
        sleep=clock.sleep,
        wall=clock.wall,
        **kwargs,
    )
    return f, net, clock


def test_titles_and_cache_names():
    assert normalize_title("  Alpha  Trion/toys ") == "Alpha_Trion/toys"
    name = cache_name("Alpha Trion/toys")
    assert name == cache_name("Alpha_Trion/toys")
    assert "/" not in name and name.endswith(".json")
    assert cache_name("A/B") != cache_name("A_B")  # distinct titles stay distinct


def test_parse_response():
    assert parse_response(response("T", "x"), "t") == ("T", "x")
    with pytest.raises(FetchError, match="not JSON"):
        parse_response("<html>", "t")
    missing = json.dumps({"error": {"code": "missingtitle", "info": "gone"}})
    with pytest.raises(PageNotFound):
        parse_response(missing, "t")
    other = json.dumps({"error": {"code": "x", "info": "Bad title"}})
    with pytest.raises(FetchError, match="Bad title"):
        parse_response(other, "t")
    with pytest.raises(FetchError, match="unexpected"):
        parse_response(json.dumps({"parse": {}}), "t")
    with pytest.raises(FetchError, match="unexpected"):
        parse_response(json.dumps([1]), "t")


def test_nothing_is_fetched_unless_enabled(tmp_path):
    f, net, _ = make(tmp_path, enabled=False)
    with pytest.raises(Disabled, match="TFWIKI_ENABLED"):
        f.page("Alpha Trion/toys")
    assert net.urls == []
    assert not f.cached("Alpha Trion/toys")


def test_cached_pages_are_readable_when_disabled():
    f = Fetcher(FIXTURES, get=lambda url: pytest.fail("no network"))
    assert f.cached("Alpha_Trion/toys")
    title, text = f.page("Alpha_Trion/toys")
    assert title == "Alpha Trion/toys" and "Legacy" in text


def test_a_page_is_fetched_once_and_cached(tmp_path):
    f, net, _ = make(tmp_path, response("Alpha Trion/toys", "hello"))
    assert f.page("Alpha Trion/toys") == ("Alpha Trion/toys", "hello")
    assert f.page("Alpha_Trion/toys") == ("Alpha Trion/toys", "hello")
    assert len(net.urls) == 1
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(net.urls[0]).query)
    assert query["page"] == ["Alpha_Trion/toys"]
    assert query["action"] == ["parse"] and query["redirects"] == ["1"]
    assert net.urls[0].startswith("https://tfwiki.net/mediawiki/api.php?")
    assert f.cached("Alpha Trion/toys")


def test_refresh_fetches_again(tmp_path):
    f, net, _ = make(tmp_path, response("P", "one"), response("P", "two"))
    assert f.page("P")[1] == "one"
    assert f.page("P", refresh=True)[1] == "two"
    assert f.page("P")[1] == "two"
    assert len(net.urls) == 2


def test_a_bad_response_is_not_cached(tmp_path):
    missing = json.dumps({"error": {"code": "missingtitle", "info": "x"}})
    f, net, _ = make(tmp_path, missing, response("P", "ok"))
    with pytest.raises(PageNotFound):
        f.page("P")
    assert not f.cached("P")
    assert f.page("P")[1] == "ok"


def test_requests_are_at_least_two_seconds_apart(tmp_path):
    f, net, clock = make(tmp_path, response("A"), response("B"), response("C"))
    f.page("A")
    assert clock.slept == []  # the first request waits for nothing
    clock.now += 0.5
    f.page("B")
    assert clock.slept == [pytest.approx(1.5)]
    clock.now += 10
    f.page("C")
    assert clock.slept == [pytest.approx(1.5)]  # long enough since the last one


def test_the_delay_cannot_be_set_below_two_seconds(tmp_path):
    f, net, clock = make(tmp_path, response("A"), response("B"), delay=0)
    f.page("A")
    f.page("B")
    assert clock.slept == [pytest.approx(2.0)]


def test_two_fetchers_share_one_gap(tmp_path):
    """Two gunicorn workers keep the same cache folder, so they share the gap."""
    clock = Clock()
    one = Fetcher(
        str(tmp_path), True, get=Net(response("A")), sleep=clock.sleep, wall=clock.wall
    )
    two = Fetcher(
        str(tmp_path), True, get=Net(response("B")), sleep=clock.sleep, wall=clock.wall
    )
    one.page("A")
    two.page("B")
    assert clock.slept == [pytest.approx(2.0)]


def test_a_429_or_503_stops_fetching_for_a_while(tmp_path):
    clock = Clock()
    f, net, _ = make(
        tmp_path,
        RateLimited("429"),
        response("A", "late"),
        clock=clock,
        halt_seconds=3600,
    )
    with pytest.raises(RateLimited):
        f.page("A")
    # No retry, however it is asked, and no request is made.
    clock.now += 60
    with pytest.raises(RateLimited, match="not retrying"):
        f.page("A")
    assert len(net.urls) == 1
    clock.now += 3600
    assert f.page("A")[1] == "late"
    assert len(net.urls) == 2


def test_other_errors_do_not_halt(tmp_path):
    f, net, _ = make(tmp_path, FetchError("down"), response("A", "ok"))
    with pytest.raises(FetchError, match="down"):
        f.page("A")
    assert f.page("A")[1] == "ok"


def test_unreadable_throttle_files_are_ignored(tmp_path):
    (tmp_path / "last-request").write_text("not a number")
    f, net, clock = make(tmp_path, response("A"))
    assert f.page("A")[1] == "wikitext"
    assert clock.slept == []


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_http_get_sends_an_honest_user_agent(monkeypatch):
    seen = {}

    def urlopen(req, timeout):
        seen["ua"] = req.get_header("User-agent")
        seen["timeout"] = timeout
        return FakeResponse("héllo".encode())

    monkeypatch.setattr(fetcher_module.urllib.request, "urlopen", urlopen)
    assert http_get("https://tfwiki.net/x") == "héllo"
    assert "github.com/eratosthene/tfc" in seen["ua"] and seen["timeout"] == 30


@pytest.mark.parametrize("code", [429, 503])
def test_http_get_stops_on_rate_limiting(monkeypatch, code):
    def urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, code, "no", {}, None)

    monkeypatch.setattr(fetcher_module.urllib.request, "urlopen", urlopen)
    with pytest.raises(RateLimited, match=str(code)):
        http_get("https://tfwiki.net/x")


def test_http_get_other_failures(monkeypatch):
    def urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "no", {}, None)

    monkeypatch.setattr(fetcher_module.urllib.request, "urlopen", urlopen)
    with pytest.raises(FetchError, match="HTTP 404") as info:
        http_get("https://tfwiki.net/x")
    assert not isinstance(info.value, RateLimited)

    def down(req, timeout):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(fetcher_module.urllib.request, "urlopen", down)
    with pytest.raises(FetchError, match="no route"):
        http_get("https://tfwiki.net/x")


def test_fetcher_from_config(tmp_path):
    f = fetcher_from_config({})
    assert f.enabled is False and f.cache_dir == "tfwiki-cache"
    f = fetcher_from_config(
        {"TFWIKI_ENABLED": True, "TFWIKI_CACHE_DIR": str(tmp_path)}, get=Net()
    )
    assert f.enabled is True and f.cache_dir == str(tmp_path)
