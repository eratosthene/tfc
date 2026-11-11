"""The tfwiki.net importer, on a recorded fixture. No test touches the network."""

import json
import os
import urllib.error
import urllib.parse

import pytest

from app import app as flask_app, db, tfwiki
from app.models import Faction, Figure, Franchise, TFWikiLink

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "tfwiki")
PAGE = "Bumblebee_(G1)/toys"
OTHER = "Other_(G1)/toys"  # a second page, served from the same fixture
BODY = "Bumblebee_(G1)_toys.json"
PAGES = {PAGE: BODY, OTHER: BODY, "Gone": "missing.json"}


def fx(name):
    return open(os.path.join(FIX, name), encoding="utf-8").read()


class FakeNet:
    """Stands in for the network: returns canned bodies and records calls."""

    def __init__(self, robots="robots_open.txt"):
        self.robots = fx(robots)
        self.urls = []
        self.stamps = []  # the fake clock at each request
        self.t = 1000.0
        self.sleeps = []

    def get(self, url):
        self.urls.append(url)
        self.stamps.append(self.t)
        if url.endswith("/robots.txt"):
            return self.robots
        for key, body in PAGES.items():
            if f"page={key}" in urllib.parse.unquote(url):
                return fx(body)
        raise tfwiki.FetchError("no canned response for " + url)

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s

    def clock(self):
        return self.t

    def fetcher(self, tmp_path, **kw):
        return tfwiki.Fetcher(
            str(tmp_path),
            get=self.get,
            sleep=self.sleep,
            clock=self.clock,
            wall=lambda: 1e9,
            **kw,
        )


@pytest.fixture
def net():
    return FakeNet()


# --- fetching ---------------------------------------------------------------


def test_throttle_is_at_least_two_seconds_between_requests(net, tmp_path):
    assert tfwiki.MIN_DELAY >= 2.0
    f = net.fetcher(tmp_path, delay=0)  # a caller cannot go below the minimum
    f.wikitext(PAGE)
    f.wikitext(OTHER)
    assert len(net.stamps) == 3  # robots.txt, then two pages
    gaps = [b - a for a, b in zip(net.stamps, net.stamps[1:])]
    assert all(g >= 2.0 for g in gaps) and net.sleeps


def test_page_is_fetched_once_and_cache_is_shared(net, tmp_path):
    title, text = net.fetcher(tmp_path).wikitext(PAGE)
    assert title == "Bumblebee (G1)/toys" and "iconlist" in text
    n = len(net.urls)
    # Another process, any spelling of the title, even from a figure's "#" link:
    # all are the one cache entry, with no request.
    for spelling in ("Bumblebee (G1)/toys", PAGE, " Bumblebee_(G1)/toys "):
        net.fetcher(tmp_path).wikitext(spelling)
    assert len(net.urls) == n
    # An explicit refresh fetches again (robots.txt is still fresh in the cache).
    net.fetcher(tmp_path).wikitext(PAGE, refresh=True)
    assert len(net.urls) == n + 1


def test_robots_cache_expires(net, tmp_path):
    net.fetcher(tmp_path).wikitext(PAGE)
    os.utime(tmp_path / "robots.txt", (0, 0))  # older than the day it is good for
    net.fetcher(tmp_path).wikitext(OTHER)
    assert sum(u.endswith("/robots.txt") for u in net.urls) == 2


def test_robots_disallow_refuses_and_fetches_nothing_else(tmp_path):
    net = FakeNet(robots="robots_blocked.txt")
    with pytest.raises(tfwiki.RobotsDisallowed):
        net.fetcher(tmp_path).wikitext(PAGE)
    assert len(net.urls) == 1 and net.urls[0].endswith("/robots.txt")


def test_ignore_robots_skips_robots_txt(tmp_path):
    net = FakeNet(robots="robots_blocked.txt")
    net.fetcher(tmp_path, ignore_robots=True).wikitext(PAGE)
    assert len(net.urls) == 1 and "action=parse" in net.urls[0]


def test_rate_limit_stops_everything(net, tmp_path):
    def limited(url):
        raise tfwiki.RateLimited("429")

    f = tfwiki.Fetcher(
        str(tmp_path),
        get=limited,
        sleep=net.sleep,
        clock=net.clock,
        ignore_robots=True,
    )
    with pytest.raises(tfwiki.RateLimited):
        f.wikitext(PAGE)
    calls = []
    f._get = calls.append
    with pytest.raises(tfwiki.RateLimited, match="earlier"):
        f.wikitext(OTHER)
    assert calls == []


def test_api_errors(net, tmp_path):
    with pytest.raises(tfwiki.FetchError, match="doesn't exist"):
        net.fetcher(tmp_path).wikitext("Gone")
    with pytest.raises(tfwiki.FetchError, match="not JSON"):
        tfwiki.parse_response("<html>", "p")
    with pytest.raises(tfwiki.FetchError, match="unexpected"):
        tfwiki.parse_response(json.dumps({"parse": {}}), "p")
    with pytest.raises(tfwiki.FetchError, match="unexpected"):
        tfwiki.parse_response("[]", "p")
    with pytest.raises(tfwiki.FetchError, match="MediaWiki error"):
        tfwiki.parse_response(json.dumps({"error": {}}), "p")


def test_http_get(monkeypatch):
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return "héllo".encode()

    seen = {}

    def fake(req, timeout):
        seen["ua"] = req.get_header("User-agent")
        return Resp()

    monkeypatch.setattr(tfwiki.urllib.request, "urlopen", fake)
    assert tfwiki._http_get("https://x/") == "héllo"
    assert "github.com/eratosthene/tfc" in seen["ua"]  # an identifying agent

    def boom(req, timeout):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(tfwiki.urllib.request, "urlopen", boom)
    with pytest.raises(tfwiki.FetchError, match="down"):
        tfwiki._http_get("https://x/")


@pytest.mark.parametrize(
    "code,kind", [(429, "RateLimited"), (503, "RateLimited"), (404, "FetchError")]
)
def test_http_status_errors(monkeypatch, code, kind):
    def boom(req, timeout):
        raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)

    monkeypatch.setattr(tfwiki.urllib.request, "urlopen", boom)
    with pytest.raises(tfwiki.FetchError) as e:
        tfwiki._http_get("https://x/")
    assert type(e.value).__name__ == kind


# --- parsing and mapping ----------------------------------------------------


def sections(fragment=None):
    title, text = tfwiki.parse_response(fx(BODY), PAGE)
    return title, tfwiki.split_page(title, text, fragment)


def test_split_and_map():
    title, secs = sections()
    assert title == "Bumblebee (G1)/toys"
    assert [s["fragment"] for s in secs] == [
        "Nameless",  # before any heading
        "Generation_1",
        "Goldbug",
        "Hero_Set",
        "Generation_2",
        "Go-Bot",
    ]
    by = {s["fragment"]: s["fields"] for s in secs}
    assert by["Generation_1"] == {
        "name": "Bumblebee",
        "release_year": 1984,
        "categories": ["Mini Vehicle"],
        "faction": "Autobot",
        "takara_id": "11, C-56",
        "franchise": ["The Transformers"],
    }
    assert by["Goldbug"]["takara_id"] == "C-97"  # label with a trailing colon
    assert by["Goldbug"]["release_year"] == 1987
    assert by["Go-Bot"]["accessories"] == ["Rifle"]
    assert by["Go-Bot"]["franchise"] == ["Generation 2"]
    assert "faction" not in by["Hero_Set"]  # Bp-a1d1: both sides
    assert "franchise" not in by["Nameless"] and "release_year" not in by["Nameless"]
    assert secs[1]["section"] == "Bumblebee (The Transformers)"
    assert secs[0]["section"] == "Nameless (no toyline)"


def test_fragment_selects_one_figure():
    assert [s["fragment"] for s in sections("Go-Bot")[1]] == ["Go-Bot"]
    assert [s["fragment"] for s in sections("generation 2")[1]] == ["Generation_2"]
    assert sections("Nope")[1] == []


def test_item_details():
    f = tfwiki._item_fields("multi", "'''Pack''' (4-pack, <s>2015</s> 2016)")
    assert f == {"name": "Pack", "release_year": 2016, "categories": ["4-pack"]}
    assert tfwiki._item_fields("d1", "Bare") == {
        "name": "Bare",
        "faction": "Decepticon",
    }
    bullets = [
        ("Hasbro ID number", "'''A1''', B2"),
        ("Series", "x"),
        ("Accessories", '"Gun", Axe'),
    ]
    assert tfwiki._bullet_fields(bullets) == {
        "hasbro_id": "A1, B2",
        "accessories": ["Gun", "Axe"],
    }
    assert tfwiki._bullet_fields([("Takara ID number", "")]) == {}
    assert tfwiki.clean("a<ref>r</ref> [[X|y]] {{t}}<br>b") == "a y\nb"


def test_links():
    assert tfwiki.character_title("Bumblebee (G1)/toys") == "Bumblebee (G1)"
    assert tfwiki.character_title("Prime/Generations_toys") == "Prime"
    assert tfwiki.link_name("Bumblebee (G1)/toys") == "Bumblebee"
    url = tfwiki.page_url("Bumblebee (G1)/toys")
    assert url == "https://tfwiki.net/wiki/Bumblebee_(G1)/toys"
    # The URL format parses with the model's own naming.
    fig = TFWikiLink(name="Bumblebee", link=url + "#Go-Bot")
    assert str(fig) == "Bumblebee (G1) @ Go-Bot [figure]"
    char = TFWikiLink(name="Bumblebee", link=tfwiki.page_url("Bumblebee (G1)"))
    assert str(char) == "Bumblebee (G1) [character]"


# --- planning and saving ----------------------------------------------------


@pytest.fixture
def franchises():
    db.session.add(Franchise(name="the transformers", start_year=1984))
    db.session.add(Franchise(name="Generation 2", start_year=1993))
    db.session.commit()


def plan_for(fragment):
    title, secs = sections(fragment)
    return title, secs[0], tfwiki.plan_import(title, secs[0])


def test_plan_save_and_rerun(franchises):
    title, sec, plan = plan_for("Generation_1")
    assert plan["problems"] == [] and plan["existing"] is None
    assert "Faction Autobot" in plan["new"]
    text = tfwiki.format_diff(plan)
    assert "+ release_year: 1984" in text and "+ new row: Category Mini Vehicle" in text
    fig = tfwiki.save_import(plan)
    assert (fig.name, fig.release_year, str(fig.faction)) == (
        "Bumblebee",
        1984,
        "Autobot",
    )
    assert fig.takara_id == "11, C-56"
    assert str(fig.figure_link) == "Bumblebee (G1) @ Generation 1 [figure]"
    assert str(fig.character) == "Bumblebee (G1) [character]"
    assert fig.franchise[0].start_year == 1984  # reused, not created

    # A re-run finds it and changes nothing.
    def counts():
        return tuple(m.query.count() for m in (Figure, TFWikiLink, Faction))

    before = counts()
    again = tfwiki.plan_import(title, sec)
    assert again["existing"] and "skip:" in tfwiki.format_diff(again)
    with pytest.raises(ValueError):
        tfwiki.save_import(again)
    assert counts() == before

    # A second figure of the same character reuses the character link.
    _, _, plan2 = plan_for("Go-Bot")
    assert not any(
        n == f"TFWikiLink {plan2['character_link']['link']}" for n in plan2["new"]
    )
    fig2 = tfwiki.save_import(plan2)
    assert [str(a) for a in fig2.accessories] == ["Rifle"]
    assert fig2.character.id == fig.character.id
    assert TFWikiLink.query.count() == 3


def test_manual_record_is_never_overwritten(franchises):
    """A hand-entered figure with the same name and year blocks the import, even
    though it has no tfwiki link of the importer's shape."""
    db.session.add(
        Figure(
            name="bumblebee",
            release_year=1984,
            faction=Faction(name="Autobot"),
            character=TFWikiLink(
                name="B", link="https://tfwiki.net/wiki/Bumblebee_(G1)"
            ),
            condition="mint",
        )
    )
    db.session.commit()
    _, _, plan = plan_for("Generation_1")
    assert "exists" in plan["existing"]
    with pytest.raises(ValueError):
        tfwiki.save_import(plan)
    assert Figure.query.one().condition == "mint"


def test_unsavable_plans(franchises):
    _, _, plan = plan_for("Nameless")
    assert plan["problems"] == ["no release year found"]
    _, _, plan = plan_for("Hero_Set")
    assert plan["problems"] == ["no faction found"]
    assert "! cannot save" in tfwiki.format_diff(plan)
    with pytest.raises(ValueError):
        tfwiki.save_import(plan)
    # An unknown franchise is reported, never created.
    _, _, plan = plan_for("Go-Bot")
    assert plan["problems"] == []
    db.session.delete(Franchise.query.filter_by(name="Generation 2").one())
    db.session.commit()
    _, _, plan = plan_for("Go-Bot")
    assert any("Franchise 'Generation 2'" in p for p in plan["problems"])


# --- the command ------------------------------------------------------------


@pytest.fixture
def runner(tmp_path, net, monkeypatch, franchises):
    monkeypatch.setitem(flask_app.config, "TFWIKI_CACHE_DIR", str(tmp_path))
    real = tfwiki.Fetcher
    monkeypatch.setattr(
        tfwiki,
        "Fetcher",
        lambda d, **kw: real(d, get=net.get, sleep=net.sleep, clock=net.clock, **kw),
    )
    return flask_app.test_cli_runner()


def run(runner, *args, **kw):
    return runner.invoke(args=["import-tfwiki", *args], **kw)


def test_cli_confirm_then_rerun(runner, net):
    res = run(runner, PAGE + "#Generation_1", input="y\n")
    assert res.exit_code == 0, res.output
    assert "Saved 1 figure(s)." in res.output and Figure.query.count() == 1
    n = len(net.urls)
    res = run(runner, PAGE + "#Generation_1")  # cached page, nothing to ask
    assert "skip:" in res.output and Figure.query.count() == 1
    # A different figure on the same page needs no new request.
    res = run(runner, PAGE + "#Go-Bot", input="n\n")
    assert "Saved 0 figure(s)." in res.output and len(net.urls) == n


def test_cli_dry_run_yes_and_overrides(runner):
    res = run(runner, PAGE + "#Generation_1", "--dry-run")
    assert res.exit_code == 0 and "Saved 0" in res.output and Figure.query.count() == 0
    res = run(
        runner, PAGE, "--yes", "--faction", "Autobot", "--franchise", "Generation 2"
    )
    # Every figure imports under the one franchise; the one with no year does not.
    assert "Saved 5 figure(s)." in res.output, res.output
    assert Figure.query.count() == 5
    assert {str(f.faction) for f in Figure.query} == {"Autobot"}


def test_cli_errors(runner, monkeypatch):
    res = run(runner, "Gone")
    assert res.exit_code != 0 and "doesn't exist" in res.output
    monkeypatch.setattr(tfwiki, "split_page", lambda *a: [])
    res = run(runner, PAGE)
    assert "No figure found" in res.output


def test_cli_ignore_robots_option_and_config(runner, monkeypatch):
    seen = []
    real = tfwiki.Fetcher

    def spy(d, **kw):
        seen.append(kw.get("ignore_robots"))
        return real(d, **kw)

    monkeypatch.setattr(tfwiki, "Fetcher", spy)
    run(runner, PAGE, "--dry-run")
    run(runner, PAGE, "--dry-run", "--ignore-robots")
    monkeypatch.setitem(flask_app.config, "TFWIKI_IGNORE_ROBOTS", True)
    res = run(runner, PAGE, "--dry-run")
    assert seen == [False, True, True] and "Ignoring robots.txt" in res.output


def test_cli_default_cache_dir(monkeypatch):
    from app import cli

    monkeypatch.delitem(flask_app.config, "TFWIKI_CACHE_DIR", raising=False)
    assert cli._cache_dir().endswith("tfwiki-cache")
