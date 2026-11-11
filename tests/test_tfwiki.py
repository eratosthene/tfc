"""The tfwiki.net importer, on synthetic fixtures. No test touches the network."""

import json
import os
import urllib.error
import urllib.parse

import pytest

from app import app as flask_app, db, tfwiki
from app.models import Faction, Figure, Franchise, TFWikiLink

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "tfwiki")


def fx(name):
    return open(os.path.join(FIX, name), encoding="utf-8").read()


class FakeNet:
    """Stands in for the network: returns canned bodies and records calls."""

    def __init__(self, robots="robots_open.txt", pages=None):
        self.robots = fx(robots)
        self.pages = pages or {}
        self.urls = []
        self.t = 0.0
        self.sleeps = []

    def get(self, url):
        self.urls.append(url)
        if url.endswith("/robots.txt"):
            return self.robots
        for key, body in self.pages.items():
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


G1 = "Optimus_Prime_(G1)"
PAGES = {G1: G1 + ".json", "Mystery": "Mystery.json", "Gone": "missing.json"}


@pytest.fixture
def net():
    return FakeNet(pages=PAGES)


# --- fetching ---------------------------------------------------------------


def test_fetch_caches_and_rate_limits(net, tmp_path):
    f = net.fetcher(tmp_path, delay=0)  # below the 1 s minimum: raised to it
    title, text = f.wikitext(G1)
    assert title == "Optimus Prime (G1)" and "toyinfobox" in text
    assert net.urls[0].endswith("/robots.txt") and "action=parse" in net.urls[1]
    f.wikitext("Mystery")
    assert net.sleeps and min(net.sleeps) > 0
    assert net.t >= tfwiki.MIN_DELAY
    n = len(net.urls)
    # A fresh fetcher reads both pages from disk, with no request at all.
    net.fetcher(tmp_path).wikitext(G1)
    assert len(net.urls) == n
    # --refresh fetches again; robots.txt is still fresh in the cache.
    f2 = net.fetcher(tmp_path)
    f2.wikitext(G1, refresh=True)
    assert len(net.urls) == n + 1


def test_robots_cache_expires(net, tmp_path):
    f = net.fetcher(tmp_path)
    f.wikitext(G1)
    robots = tmp_path / "robots.txt"
    os.utime(robots, (0, 0))  # far older than the day the cache is good for
    net.fetcher(tmp_path).wikitext("Mystery")
    assert sum(u.endswith("/robots.txt") for u in net.urls) == 2


def test_robots_disallow_refuses_and_fetches_nothing_else(tmp_path):
    net = FakeNet(robots="robots_blocked.txt", pages=PAGES)
    with pytest.raises(tfwiki.RobotsDisallowed):
        net.fetcher(tmp_path).wikitext(G1)
    assert len(net.urls) == 1 and net.urls[0].endswith("/robots.txt")


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
    assert seen["ua"] == tfwiki.USER_AGENT

    def boom(req, timeout):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(tfwiki.urllib.request, "urlopen", boom)
    with pytest.raises(tfwiki.FetchError, match="down"):
        tfwiki._http_get("https://x/")


# --- parsing and mapping ----------------------------------------------------


def sections(fragment=None):
    title, text = tfwiki.parse_response(fx(G1 + ".json"), G1)
    return title, tfwiki.split_page(title, text, fragment)


def test_split_and_map():
    title, secs = sections()
    assert [s["section"] for s in secs] == ["Generation 1", "Masterpiece"]
    assert secs[0]["fields"] == {
        "name": "Optimus Prime",
        "release_year": 1984,
        "franchise": ["Generation 1"],
        "faction": "Autobots",
        "tooling": ["Prime tooling"],
        "accessories": ["Blaster", "Axe"],
        "categories": ["Leader"],
        "exclusive_to": "Toys R Us",
        "hasbro_id": "1234",
        "takara_id": "C-001",
    }
    assert secs[1]["fields"]["release_year"] == 2003
    assert "tooling" not in secs[1]["fields"]


def test_fragment_selects_one_section_and_leading_infobox():
    _, secs = sections("Masterpiece")
    assert [s["section"] for s in secs] == ["Masterpiece"]
    text = "{{infobox toy|name=X|year=1999}}\n== A ==\n{{unrelated|a=b}}"
    secs = tfwiki.split_page("Page", text)
    assert secs == [{"section": "Page", "fields": {"name": "X", "release_year": 1999}}]


def test_template_edge_cases():
    assert tfwiki.find_templates("{{open") == []
    assert tfwiki.find_templates("no templates") == []
    ((name, fields),) = tfwiki.find_templates("{{T|a={{x|1|2}}|b=[[l|m|n]]|junk}}")
    assert name == "T" and fields["a"] == "{{x|1|2}}" and "junk" not in fields
    assert tfwiki.map_infobox({"year": "unknown"}) == {}
    assert tfwiki.is_infobox("Toy_Infobox") and not tfwiki.is_infobox("Quote")


def test_links():
    assert tfwiki.link_name("Optimus Prime (G1)") == "Optimus Prime"
    url = tfwiki.page_url("Optimus Prime (G1)")
    assert url == "https://tfwiki.net/wiki/Optimus_Prime_(G1)"
    # The URL format parses with the model's own naming.
    assert str(TFWikiLink(name="Optimus Prime", link=url)) == (
        "Optimus Prime (G1) [character]"
    )
    fig = TFWikiLink(name="Optimus Prime", link=url + "#Generation_1")
    assert str(fig) == "Optimus Prime (G1) @ Generation 1 [figure]"


# --- planning and saving ----------------------------------------------------


@pytest.fixture
def g1_rows():
    db.session.add(Franchise(name="generation 1", start_year=1984))
    db.session.add(Franchise(name="Masterpiece", start_year=2003))
    db.session.commit()


def test_plan_save_and_rerun(g1_rows):
    title, secs = sections()
    plan = tfwiki.plan_import(title, secs[0])
    assert plan["problems"] == [] and plan["existing"] is None
    assert "Faction Autobots" in plan["new"]
    text = tfwiki.format_diff(plan)
    assert "+ release_year: 1984" in text and "+ new row: Tooling Prime tooling" in text
    fig = tfwiki.save_import(plan)
    assert (fig.name, fig.release_year, str(fig.faction)) == (
        "Optimus Prime",
        1984,
        "Autobots",
    )
    assert [str(a) for a in fig.accessories] == ["Blaster", "Axe"]
    assert str(fig.figure_link) == "Optimus Prime (G1) @ Generation 1 [figure]"
    assert str(fig.character) == "Optimus Prime (G1) [character]"
    assert fig.franchise[0].start_year == 1984  # reused, not created

    # A re-run finds it and changes nothing.
    before = (Figure.query.count(), TFWikiLink.query.count(), Faction.query.count())
    again = tfwiki.plan_import(title, secs[0])
    assert again["existing"]
    assert "skip:" in tfwiki.format_diff(again)
    with pytest.raises(ValueError):
        tfwiki.save_import(again)
    assert before == (
        Figure.query.count(),
        TFWikiLink.query.count(),
        Faction.query.count(),
    )

    # The second section shares the character link, which is reused.
    plan2 = tfwiki.plan_import(title, secs[1])
    assert not any(
        "TFWikiLink https://tfwiki.net/wiki/Optimus_Prime_(G1)" == n
        for n in plan2["new"]
    )
    tfwiki.save_import(plan2)
    assert TFWikiLink.query.filter_by(link=plan2["character_link"]["link"]).count() == 1
    assert Faction.query.count() == 2  # "Autobots" and "Autobot" are different names


def test_manual_record_is_never_overwritten(g1_rows):
    """A hand-entered figure with the same name and year blocks the import, even
    though it has no tfwiki link of the importer's shape."""
    title, secs = sections()
    db.session.add(
        Figure(
            name="optimus prime",
            release_year=1984,
            faction=Faction(name="Autobot"),
            character=TFWikiLink(
                name="OP", link="https://tfwiki.net/wiki/Optimus_Prime"
            ),
            condition="mint",
        )
    )
    db.session.commit()
    plan = tfwiki.plan_import(title, secs[0])
    assert "exists" in plan["existing"]
    with pytest.raises(ValueError):
        tfwiki.save_import(plan)
    assert Figure.query.one().condition == "mint"


def test_unsavable_plans():
    secs = tfwiki.split_page(
        "Mystery", tfwiki.parse_response(fx("Mystery.json"), "Mystery")[1]
    )
    plan = tfwiki.plan_import("Mystery", secs[0])
    assert "no release year found" in plan["problems"]
    assert "no faction found" in plan["problems"]
    assert any("Franchise 'Nonexistent line'" in p for p in plan["problems"])
    assert "! cannot save" in tfwiki.format_diff(plan)
    with pytest.raises(ValueError):
        tfwiki.save_import(plan)


# --- the command ------------------------------------------------------------


@pytest.fixture
def runner(tmp_path, net, monkeypatch, g1_rows):
    monkeypatch.setitem(flask_app.config, "TFWIKI_CACHE_DIR", str(tmp_path))
    real = tfwiki.Fetcher
    monkeypatch.setattr(
        tfwiki,
        "Fetcher",
        lambda d: real(d, get=net.get, sleep=net.sleep, clock=net.clock),
    )
    return flask_app.test_cli_runner()


def run(runner, *args, **kw):
    return runner.invoke(args=["import-tfwiki", *args], **kw)


def test_cli_confirm_then_rerun(runner):
    res = run(runner, G1, input="y\nn\n")
    assert res.exit_code == 0, res.output
    assert "Saved 1 figure(s)." in res.output
    assert Figure.query.count() == 1
    res = run(runner, G1, input="n\n")  # figure 1 is skipped; only #2 is asked
    assert "skip:" in res.output and Figure.query.count() == 1


def test_cli_dry_run_and_yes(runner):
    res = run(runner, G1 + "#Generation_1", "--dry-run")
    assert res.exit_code == 0 and "Saved 0" in res.output and Figure.query.count() == 0
    res = run(runner, G1, "--yes")
    assert "Saved 2 figure(s)." in res.output and Figure.query.count() == 2


def test_cli_errors(runner, monkeypatch):
    res = run(runner, "Gone")
    assert res.exit_code != 0 and "doesn't exist" in res.output
    monkeypatch.setattr(tfwiki, "split_page", lambda *a: [])
    res = run(runner, G1)
    assert "No figure infobox" in res.output
    res = run(runner, "Mystery", "--yes")  # problems: listed, not saved
    assert res.exit_code != 0 or "Saved 0" in res.output


def test_cli_default_cache_dir(monkeypatch):
    from app import cli

    monkeypatch.delitem(flask_app.config, "TFWIKI_CACHE_DIR", raising=False)
    assert cli._cache_dir().endswith("tfwiki-cache")
