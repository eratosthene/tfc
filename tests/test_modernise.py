"""Rewriting old-style figure links (Name_(G1)#Anchor) to the toys page.

Real pages come from the recorded fixtures (tests/fixtures/tfwiki); the odd cases
use a small fake fetcher, so nothing here touches the network.
"""

import json
import os
import shutil

import pytest
from click.testing import CliRunner
from sqlalchemy import select

from app import app as flask_app, db
from app import modernise as cli
from app.models import Faction, Figure, FigureReference
from app.tfwiki import modernise as m
from app.tfwiki.fetcher import (
    Disabled,
    FetchError,
    Fetcher,
    PageNotFound,
    RateLimited,
)

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures", "tfwiki")
WIKI = "https://tfwiki.net/wiki/"


@pytest.fixture
def cache(tmp_path):
    folder = tmp_path / "cache"
    folder.mkdir()
    for name in os.listdir(FIXTURES):
        if name.endswith(".json"):
            shutil.copy(os.path.join(FIXTURES, name), folder)
    return str(folder)


@pytest.fixture
def recorded(cache):
    return Fetcher(cache, enabled=False)


def entry(anchor, name="A"):
    return (
        "{{anchor|%s}}\n" % anchor if anchor else ""
    ) + "<ul class=\"iconlist\">{{Bp-a1|'''%s''' (Deluxe Class, 2000)}}</ul>\n" % name


def toys(*blocks):
    return "==Toys==\n===''The Line''===\n" + "".join(blocks)


class Fake:
    """Pages by the title asked for: {title: (canonical title, wikitext) or an
    exception to raise}."""

    enabled = True

    def __init__(self, pages):
        self.pages = pages
        self.asked = []

    def cached(self, title):
        return title in self.pages

    def page(self, title, refresh=False):
        self.asked.append(title)
        found = self.pages[title]
        if isinstance(found, Exception):
            raise found
        return found


# --- which links are old style -------------------------------------------------


@pytest.mark.parametrize(
    "link, expected",
    [
        (WIKI + "Alpha_Trion_(G1)#Legacy", True),
        (WIKI + "Hi-Q#The_Transformers", True),
        (WIKI + "Metroplex_(G1)", False),  # no fragment
        (WIKI + "Alpha_Trion/toys#Legacy", False),  # already a toys page
        (WIKI + "Optimus_Prime_(G1)/Generations_toys#X", False),
        ("https://example.com/wiki/A#B", False),  # not tfwiki
        ("not a link", False),
    ],
)
def test_old_style(link, expected):
    assert m.old_style(link) is expected


# --- one link, against the recorded pages -----------------------------------


def test_the_alpha_trion_link_moves_to_the_toys_page(recorded):
    result = m.check(recorded, WIKI + "Alpha_Trion_(G1)#Legacy")
    # Legacy is a heading on the toys page, not an {{anchor}}, so it is left alone.
    assert result.status == m.HEADING
    assert result.new is None


def test_an_anchor_on_the_toys_page_is_rewritten_keeping_the_fragment(recorded):
    result = m.check(recorded, WIKI + "Alpha_Trion_(G1)#SDCC2015")
    assert result.status == m.REWRITE
    assert result.new == WIKI + "Alpha_Trion/toys#SDCC2015"


def test_a_figure_still_on_its_own_page_is_current(recorded):
    result = m.check(recorded, WIKI + "Boater#Zone")
    assert result.status == m.CURRENT and result.new is None


def test_a_fragment_the_page_does_not_have(recorded):
    assert m.check(recorded, WIKI + "Alpha_Trion_(G1)#Nonesuch").status == m.NO_FIGURE


def test_a_page_that_is_not_cached(recorded):
    result = m.check(recorded, WIKI + "Not_Cached_(G1)#Thing")
    assert result.status == m.NOT_CACHED and "not cached" in result.detail


# --- the odd cases, with a fake wiki -----------------------------------------------


def test_fragment_is_kept_exactly_as_saved():
    toys_page = toys(entry("Robots_in_Disguise_.282001.29"))
    wiki = Fake(
        {
            "Name_(G1)": ("Name (G1)", "{{main|Name (G1)/toys}}\nNo figures here.\n"),
            "Name_(G1)/toys": ("Name (G1)/toys", toys_page),
        }
    )
    link = WIKI + "Name_(G1)#Robots_in_Disguise_.282001.29"
    result = m.check(wiki, link)
    assert result.status == m.REWRITE
    assert result.new == WIKI + "Name_(G1)/toys#Robots_in_Disguise_.282001.29"


def test_an_anchor_that_differs_only_in_capitals_is_left_alone(recorded):
    result = m.check(recorded, WIKI + "Alpha_Trion_(G1)#sdcc2015")
    assert result.status == m.CASE and result.new is None


def test_spaces_and_underscores_in_an_anchor_are_the_same():
    wiki = Fake(
        {
            "Name_(G1)": ("Name (G1)", "{{main|Name (G1)/toys}}\n"),
            "Name_(G1)/toys": ("Name (G1)/toys", toys(entry("Two Words"))),
        }
    )
    assert m.check(wiki, WIKI + "Name_(G1)#Two_Words").status == m.REWRITE


def two_toys_pages(first, second):
    return Fake(
        {
            "Name_(G1)": (
                "Name (G1)",
                "{{main|Name (G1)/toys}}\n{{main|Name (G1)/Generations toys}}\n",
            ),
            "Name_(G1)/toys": ("Name (G1)/toys", toys(*first)),
            "Name_(G1)/Generations_toys": ("Name (G1)/Generations toys", toys(*second)),
        }
    )


def test_both_toys_pages_are_searched():
    wiki = two_toys_pages([entry("Other")], [entry("Wanted")])
    result = m.check(wiki, WIKI + "Name_(G1)#Wanted")
    assert result.status == m.REWRITE
    assert result.new == WIKI + "Name_(G1)/Generations_toys#Wanted"


def test_the_second_toys_page_is_read_even_when_the_first_has_the_anchor():
    wiki = two_toys_pages([entry("Wanted")], [entry("Other")])
    result = m.check(wiki, WIKI + "Name_(G1)#Wanted")
    assert result.new == WIKI + "Name_(G1)/toys#Wanted"
    assert wiki.asked == ["Name_(G1)", "Name_(G1)/toys", "Name_(G1)/Generations_toys"]


def test_an_anchor_on_both_toys_pages_is_ambiguous():
    wiki = two_toys_pages([entry("Same")], [entry("Same")])
    result = m.check(wiki, WIKI + "Name_(G1)#Same")
    assert result.status == m.AMBIGUOUS and result.new is None


def test_the_figure_reader_still_stops_at_the_first_toys_page_by_default():
    from app.tfwiki.figure import read_figure

    wiki = two_toys_pages([entry("Same")], [entry("Same")])
    result = read_figure(wiki, WIKI + "Name_(G1)#Same")
    assert [c["link"] for c in result["candidates"]] == [WIKI + "Name_(G1)/toys#Same"]
    assert "Name_(G1)/Generations_toys" not in wiki.asked


def test_checking_a_link_never_fetches_faction_symbol_templates():
    # {{Bp-pr9}} has no faction in its code, so suggestions would fetch
    # Template:Bp-pr9. Checking a link only needs the link.
    block = (
        '{{anchor|Wanted}}\n<ul class="iconlist">'
        "{{Bp-pr9|'''A''' (Deluxe Class, 2000)}}</ul>\n"
    )
    wiki = Fake(
        {
            "Name_(G1)": ("Name (G1)", "{{main|Name (G1)/toys}}\n"),
            "Name_(G1)/toys": ("Name (G1)/toys", toys(block)),
        }
    )
    assert m.check(wiki, WIKI + "Name_(G1)#Wanted").status == m.REWRITE
    assert not [t for t in wiki.asked if t.startswith("Template:")]


def test_a_figure_described_in_prose_on_its_own_page_is_current():
    page = "Intro.\n==Toys==\n===''The Line''===\n:''A prose description.''\n"
    wiki = Fake({"Name_(G1)": ("Name (G1)", page)})
    assert m.check(wiki, WIKI + "Name_(G1)#The_Line").status == m.CURRENT


def test_a_redirect_is_not_a_move_to_a_toys_page():
    wiki = Fake({"Old_Name": ("New Name (G1)", toys(entry("Thing")))})
    assert m.check(wiki, WIKI + "Old_Name#Thing").status == m.REDIRECT


def test_an_anchor_on_two_entries_is_ambiguous():
    wiki = Fake(
        {
            "Name_(G1)": ("Name (G1)", "{{main|Name (G1)/toys}}\n"),
            "Name_(G1)/toys": (
                "Name (G1)/toys",
                toys(entry("Same", "A"), entry("Same", "B")),
            ),
        }
    )
    assert m.check(wiki, WIKI + "Name_(G1)#Same").status == m.AMBIGUOUS


@pytest.mark.parametrize(
    "error, status",
    [
        (PageNotFound("gone"), m.NO_PAGE),
        (FetchError("boom"), m.ERROR),
        (Disabled("off"), m.NOT_CACHED),
    ],
)
def test_other_problems_are_results(error, status):
    wiki = Fake({"Name_(G1)": error})
    assert m.check(wiki, WIKI + "Name_(G1)#A").status == status


def test_a_link_that_is_not_a_wiki_page_is_an_error():
    assert m.check(Fake({}), "https://example.com/x#y").status == m.ERROR


def test_rate_limiting_is_not_swallowed():
    with pytest.raises(RateLimited):
        m.check(Fake({"Name_(G1)": RateLimited("slow down")}), WIKI + "Name_(G1)#A")


# --- the fetch budget -----------------------------------------------------------------


class Counting:
    def __init__(self, cached=()):
        self.enabled = True
        self.cached_titles = set(cached)
        self.fetched = []

    def cached(self, title):
        return title in self.cached_titles

    def page(self, title, refresh=False):
        self.fetched.append(title)
        self.cached_titles.add(title)
        return title, ""


def test_the_budget_counts_only_network_fetches_and_stops_at_the_limit():
    inner = Counting(cached={"Have"})
    budget = m.Budget(inner, 2)
    budget.page("Have")
    budget.page("One")
    budget.page("Two")
    budget.page("One")  # cached by now
    assert budget.used == 2 and budget.cached("One")
    with pytest.raises(m.OutOfBudget):
        budget.page("Three")
    assert inner.fetched == ["Have", "One", "Two", "One"]


def test_the_budget_does_not_count_when_fetching_is_off():
    inner = Counting()
    inner.enabled = False
    budget = m.Budget(inner, 0)
    budget.page("X")  # the fetcher itself would refuse; the budget does not step in
    assert budget.used == 0


def test_no_limit_means_unlimited():
    budget = m.Budget(Counting(), None)
    for n in range(5):
        budget.page("P%d" % n)
    assert budget.used == 5


def test_a_spent_budget_is_a_limit_result():
    wiki = Fake({})
    budget = m.Budget(Counting(), 0)
    assert m.check(budget, WIKI + "Name_(G1)#A").status == m.LIMIT
    del wiki


# --- the command ---------------------------------------------------------------------


@pytest.fixture
def old_links(seed):
    """The seed figure gets an old-style link and two references."""
    figure = db.session.get(Figure, seed["figure"].id)
    figure.link = WIKI + "Alpha_Trion_(G1)#SDCC2015"
    db.session.add(Faction(name="Other"))
    other = Figure(
        name="Other",
        release_year=2000,
        faction=figure.faction,
        link=WIKI + "Alpha_Trion_(G1)#sdcc2015",  # differs only in case
    )
    db.session.add(other)
    db.session.flush()
    db.session.add_all(
        [
            FigureReference(
                figure_id=figure.id,
                kind="ancestor",
                name="Same",
                link=WIKI + "Alpha_Trion_(G1)#SDCC2015",
            ),
            FigureReference(
                figure_id=figure.id,
                kind="packed_with",
                name="Gone",
                link=WIKI + "Not_Cached_(G1)#Thing",
            ),
        ]
    )
    db.session.commit()
    return seed


@pytest.fixture
def cache_only(cache, monkeypatch):
    monkeypatch.setitem(flask_app.config, "TFWIKI_CACHE_DIR", cache)
    monkeypatch.setitem(flask_app.config, "TFWIKI_ENABLED", False)
    return cache


def run(*args):
    result = CliRunner().invoke(cli.modernise_links, list(args))
    db.session.expire_all()
    return result


def links_in_db():
    figures = {f.name: f.link for f in db.session.scalars(select(Figure))}
    refs = {r.name: r.link for r in db.session.scalars(select(FigureReference))}
    return figures, refs


def test_dry_run_lists_and_saves_nothing(old_links, cache_only):
    before = links_in_db()
    result = run()
    assert result.exit_code == 0, result.output
    assert (
        "Alpha_Trion_(G1)#SDCC2015\n    -> " + WIKI + "Alpha_Trion/toys#SDCC2015"
        in result.output
    )
    assert "[1 figures, 1 references]" in result.output
    assert (
        "page not in the cache" in result.output
        and "Not_Cached_(G1)#Thing" in result.output
    )
    assert (
        "the anchor differs in capital letters (left alone):\n  "
        + WIKI
        + "Alpha_Trion_(G1)#sdcc2015"
    ) in result.output
    assert "1 links would be rewritten. Run again with --apply." in result.output
    assert "pages fetched: 0" in result.output
    assert links_in_db() == before


def test_apply_rewrites_exact_matches_only(old_links, cache_only):
    result = run("--apply")
    assert "Rewrote 1 figure links and 1 references." in result.output
    figures, refs = links_in_db()
    new = WIKI + "Alpha_Trion/toys#SDCC2015"
    assert figures["Optimus Prime"] == new and refs["Same"] == new
    # Same link in another case, and an uncached one, are untouched.
    assert figures["Other"] == WIKI + "Alpha_Trion_(G1)#sdcc2015"
    assert refs["Gone"] == WIKI + "Not_Cached_(G1)#Thing"


def test_a_second_run_finds_nothing_more_to_rewrite(old_links, cache_only):
    run("--apply")
    again = run("--apply")
    assert "Nothing to rewrite." in again.output


def test_the_json_report(old_links, cache_only, tmp_path):
    path = tmp_path / "report.json"
    run("--json", str(path))
    report = json.loads(path.read_text())
    entry_ = report[WIKI + "Alpha_Trion_(G1)#SDCC2015"]
    assert entry_["status"] == "rewrite" and entry_["figures"] == 1
    assert entry_["new"] == WIKI + "Alpha_Trion/toys#SDCC2015"
    assert report[WIKI + "Not_Cached_(G1)#Thing"]["status"] == "not_cached"


def test_fetch_needs_the_setting(old_links, cache_only):
    result = run("--fetch")
    assert result.exit_code != 0 and "TFWIKI_ENABLED" in result.output


def test_the_command_never_fetches_without_the_flag(old_links, cache_only, monkeypatch):
    flask_app.config["TFWIKI_ENABLED"] = True
    seen = []
    real = cli.build_fetcher

    def watching(fetch, delay=None):
        fetcher = real(fetch, delay)
        seen.append((fetch, fetcher.enabled))
        return fetcher

    monkeypatch.setattr(cli, "build_fetcher", watching)
    run()
    assert seen == [(False, False)]


def test_fetch_fetches_what_is_missing_up_to_the_limit(
    old_links, tmp_path, monkeypatch
):
    replies = {}
    asked = []

    def get(url):
        asked.append(url)
        return json.dumps(
            {"parse": {"title": "Not Cached (G1)", "wikitext": {"*": "No toys."}}}
        )

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setitem(flask_app.config, "TFWIKI_CACHE_DIR", str(empty))
    monkeypatch.setitem(flask_app.config, "TFWIKI_ENABLED", True)
    monkeypatch.setattr(
        cli,
        "build_fetcher",
        lambda fetch, delay=None: Fetcher(
            str(empty),
            enabled=fetch,
            get=get,
            sleep=lambda s: None,
            wall=lambda: 1000.0,
        ),
    )
    result = run("--fetch", "--limit", "1")
    assert "pages fetched: 1" in result.output
    assert len(asked) == 1
    assert "not looked at (fetch limit reached)" in result.output
    assert replies == {}


def test_rate_limiting_stops_the_run(old_links, tmp_path, monkeypatch):
    def get(url):
        raise RateLimited("429")

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setitem(flask_app.config, "TFWIKI_ENABLED", True)
    monkeypatch.setattr(
        cli,
        "build_fetcher",
        lambda fetch, delay=None: Fetcher(
            str(empty), enabled=fetch, get=get, sleep=lambda s: None
        ),
    )
    result = run("--fetch")
    assert "asked us to slow down; stopped" in result.output
    assert "not looked at" in result.output


def test_the_gap_between_requests_can_be_lengthened_but_not_shortened(
    old_links, cache_only, monkeypatch
):
    gaps = []
    real = cli.build_fetcher

    def watching(fetch, delay=None):
        fetcher = real(fetch, delay)
        gaps.append(fetcher._throttle.delay)
        return fetcher

    monkeypatch.setattr(cli, "build_fetcher", watching)
    run()
    assert run("--delay", "7.5").exit_code == 0
    result = run("--delay", "0.5")
    assert "A gap under 2 seconds is not allowed; using 2." in result.output
    flask_app.config["TFWIKI_DELAY"] = 4
    run()
    run("--delay", "10")
    assert gaps == [2.0, 7.5, 2.0, 4.0, 10.0]
