"""Pointing characters at their wiki page's current name (flask modernise-characters)."""

import json

import pytest
from click.testing import CliRunner

from app import app as flask_app, db
from app import modernise as cli
from app.models import Character, Figure
from app.tfwiki import characters as c
from app.tfwiki import modernise as m
from app.tfwiki.fetcher import (
    Disabled,
    FetchError,
    Fetcher,
    PageNotFound,
    RateLimited,
)
from test_disambiguation import OLD, WIKI, wiki_in, write

BATTLETRAP = WIKI + "Battletrap"


def no_evidence():
    pytest.fail("the figures were asked about a page that is not a disambiguation page")


def folder_with(tmp_path, **extra):
    """The Battletrap pages, plus renamed and current character pages."""
    wiki_in(tmp_path)
    write(tmp_path, "Alpha_Trion_(G1)", "Alpha Trion", "Alpha Trion is a character.\n")
    write(tmp_path, "Existing_Name", "Existing Name", "A character.\n")
    write(tmp_path, "Old_Name", "Existing Name", "A character.\n")
    return Fetcher(str(tmp_path), get=lambda url: pytest.fail("no network: " + url))


# --- one character's page ---------------------------------------------------------------


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ("Alpha_Trion", "Alpha Trion", True),
        ("alpha_Trion", "Alpha_Trion", True),  # MediaWiki capitalises the first letter
        ("Alpha_Trion", "Alpha_trion", False),
        ("Alpha_Trion_(G1)", "Alpha_Trion", False),
    ],
)
def test_same_page(a, b, expected):
    assert c.same_page(a, b) is expected


def test_a_page_that_still_exists_is_current(tmp_path):
    wiki = folder_with(tmp_path)
    assert c.check(wiki, WIKI + "Existing_Name", no_evidence).status == c.CURRENT
    write(tmp_path, "Battletrap_(G1)", "Battletrap (G1)", "x")
    assert c.check(wiki, WIKI + "Battletrap_(G1)", no_evidence).status == c.CURRENT


def test_a_renamed_page_moves_to_the_current_title(tmp_path):
    result = c.check(folder_with(tmp_path), WIKI + "Alpha_Trion_(G1)", no_evidence)
    assert result.status == c.RENAMED and result.new == WIKI + "Alpha_Trion"


def test_a_disambiguation_page_is_settled_by_the_figures(tmp_path):
    wiki = folder_with(tmp_path)
    result = c.check(wiki, BATTLETRAP, lambda: ({"Battletrap_(G1)"}, set()))
    assert result.status == c.DISAMBIGUATED and result.new == WIKI + "Battletrap_(G1)"


def test_a_decision_stands_even_if_some_figure_pages_are_unread(tmp_path):
    wiki = folder_with(tmp_path)
    result = c.check(wiki, BATTLETRAP, lambda: ({"Battletrap_(ROTB)"}, {m.NOT_CACHED}))
    assert result.new == WIKI + "Battletrap_(ROTB)"


@pytest.mark.parametrize(
    "pages",
    [set(), {"Somewhere_Else"}, {"Battletrap_(G1)", "Battletrap_(ROTB)"}],
)
def test_figures_that_do_not_pick_exactly_one_namesake_leave_it_undecided(
    tmp_path, pages
):
    result = c.check(folder_with(tmp_path), BATTLETRAP, lambda: (pages, set()))
    assert result.status == c.UNDECIDED and result.new is None
    assert (
        "Battletrap (G1), Battletrap (Cyberverse), Battletrap (ROTB)" in result.detail
    )


@pytest.mark.parametrize("status", [m.NOT_CACHED, m.LIMIT])
def test_unread_figure_pages_are_reported_rather_than_guessed_around(tmp_path, status):
    result = c.check(folder_with(tmp_path), BATTLETRAP, lambda: (set(), {status}))
    assert result.status == status and result.new is None


class Broken:
    def __init__(self, error):
        self.error = error

    def page(self, title, refresh=False):
        raise self.error


@pytest.mark.parametrize(
    "error, status",
    [
        (PageNotFound("gone"), m.NO_PAGE),
        (Disabled("off"), m.NOT_CACHED),
        (m.OutOfBudget("limit"), m.LIMIT),
        (FetchError("boom"), m.ERROR),
    ],
)
def test_page_problems_are_results(error, status):
    assert c.check(Broken(error), WIKI + "Anyone", no_evidence).status == status


def test_a_link_that_is_not_a_wiki_page_is_an_error_and_rate_limiting_propagates():
    assert c.check(Broken(None), "https://example.com/x", no_evidence).status == m.ERROR
    with pytest.raises(RateLimited):
        c.check(Broken(RateLimited("429")), WIKI + "Anyone", no_evidence)


# --- the evidence from a character's figures ---------------------------------------------


def test_figure_pages_resolves_old_style_links_and_reads_toys_pages(tmp_path):
    wiki = folder_with(tmp_path)
    budget = m.Budget(wiki, None)
    pages, missing = cli.figure_pages(
        budget,
        [
            OLD,  # resolved through the disambiguation page to Battletrap (G1)
            WIKI + "Alpha_Trion/toys#Legacy",  # a toys page: its character page
            "https://example.com/not-the-wiki",  # skipped
            WIKI + "Existing_Name#Nowhere",  # no such section: skipped
        ],
    )
    assert pages == {"Battletrap_(G1)", "Alpha_Trion"} and missing == set()


def test_figure_pages_reports_pages_that_could_not_be_read(tmp_path):
    other = tmp_path / "partial"
    other.mkdir()
    wiki = wiki_in(other, skip=("Battletrap_(ROTB)",))
    pages, missing = cli.figure_pages(m.Budget(wiki, None), [OLD])
    assert pages == set() and missing == {m.NOT_CACHED}
    pages, missing = cli.figure_pages(
        m.Budget(Fetcher(str(other), enabled=True, get=lambda u: pytest.fail(u)), 0), []
    )
    assert (pages, missing) == (set(), set())


# --- conflicts ---------------------------------------------------------------------------


def test_a_rewrite_never_takes_a_link_another_character_has():
    new = WIKI + "Alpha_Trion"
    results = {
        1: m.Result(c.RENAMED, "Alpha Trion", new),
        2: m.Result(c.RENAMED, "Alpha Trion", new),  # claims the same link
        3: m.Result(c.DISAMBIGUATED, "x", WIKI + "Taken"),
        4: m.Result(c.CURRENT, "y", None),
    }
    settled = cli.settle_conflicts(results, {(WIKI + "taken").lower(): 99})
    assert settled[1].status == c.RENAMED  # the lower id gets it
    assert settled[2].status == c.CONFLICT and "character 1" in settled[2].detail
    assert settled[3].status == c.CONFLICT and "character 99" in settled[3].detail
    assert settled[4].status == c.CURRENT


def test_a_character_may_keep_its_own_link():
    new = WIKI + "Same"
    settled = cli.settle_conflicts({5: m.Result(c.RENAMED, "x", new)}, {new.lower(): 5})
    assert settled[5].status == c.RENAMED


# --- the command ---------------------------------------------------------------------------


@pytest.fixture
def people(tmp_path, monkeypatch, seed):
    """Characters in the states the command handles, and a cache to match."""
    folder_with(tmp_path)
    monkeypatch.setitem(flask_app.config, "TFWIKI_CACHE_DIR", str(tmp_path))
    monkeypatch.setitem(flask_app.config, "TFWIKI_ENABLED", False)
    faction = db.session.get(Figure, seed["figure"].id).faction
    made = {}
    for key, name, link, figures in (
        ("battletrap", "Battletrap", BATTLETRAP, [OLD]),
        ("alpha", "Alpha Trion", WIKI + "Alpha_Trion_(G1)", []),
        ("current", "Existing", WIKI + "Existing_Name", []),
        ("conflict", "Old", WIKI + "Old_Name", []),  # redirects to Existing_Name, taken
        ("outside", "Elsewhere", "https://example.com/x", []),
        ("uncached", "Ghost", WIKI + "Not_Cached", []),
    ):
        person = Character(name=name, link=link)
        db.session.add(person)
        db.session.flush()
        for n, figure_link in enumerate(figures):
            db.session.add(
                Figure(
                    name="%s %d" % (name, n),
                    release_year=2020,
                    faction=faction,
                    link=figure_link,
                    character_new=person,
                )
            )
        made[key] = person.id
    db.session.commit()
    return made


def run(*args):
    result = CliRunner().invoke(cli.modernise_characters, list(args))
    db.session.expire_all()
    return result


def link_of(pk):
    return db.session.get(Character, pk).link


def test_dry_run_lists_what_it_would_do_and_saves_nothing(people):
    result = run()
    assert result.exit_code == 0, result.output
    out = result.output
    # The five made here, and the seed's own Optimus Prime (a page that is not cached).
    assert "6 characters with a wiki link; pages fetched: 0" in out
    assert "Alpha Trion (character %d)" % people["alpha"] in out
    assert "-> " + WIKI + "Alpha_Trion   [renamed; 0 figures]" in out
    assert "-> " + WIKI + "Battletrap_(G1)   [disambiguated; 1 figures]" in out
    assert "the new link belongs to another character already (left alone):" in out
    assert (
        "page not in the cache" in out
        and "Ghost (character %d)" % people["uncached"] in out
    )
    assert "already current" in out and "Elsewhere" not in out
    assert "2 character links would be rewritten. Run again with --apply." in out
    assert link_of(people["battletrap"]) == BATTLETRAP


def test_apply_rewrites_only_the_settled_ones(people):
    result = run("--apply")
    assert "Rewrote 2 character links." in result.output
    assert link_of(people["battletrap"]) == WIKI + "Battletrap_(G1)"
    assert link_of(people["alpha"]) == WIKI + "Alpha_Trion"
    assert link_of(people["conflict"]) == WIKI + "Old_Name"  # left alone
    assert link_of(people["current"]) == WIKI + "Existing_Name"
    assert link_of(people["outside"]) == "https://example.com/x"
    assert "Nothing to rewrite." in run("--apply").output


def test_the_report_can_be_written_as_json(people, tmp_path):
    path = tmp_path / "characters.json"
    run("--json", str(path))
    report = json.loads(path.read_text())
    entry = report[str(people["battletrap"])]
    assert entry["status"] == "disambiguated" and entry["figures"] == 1
    assert entry["new"] == WIKI + "Battletrap_(G1)" and entry["link"] == BATTLETRAP
    assert report[str(people["conflict"])]["status"] == "conflict"
    assert str(people["outside"]) not in report


def test_fetch_needs_the_setting_and_the_gap_cannot_be_shortened(people):
    assert run("--fetch").exit_code != 0
    assert (
        "A gap under 2 seconds is not allowed; using 2." in run("--delay", "0.5").output
    )


def test_a_rate_limited_run_stops_and_says_so(people, tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()

    def limited(url):
        raise RateLimited("429")

    monkeypatch.setitem(flask_app.config, "TFWIKI_ENABLED", True)
    monkeypatch.setattr(
        cli,
        "build_fetcher",
        lambda fetch, delay=None: Fetcher(
            str(empty), enabled=fetch, get=limited, sleep=lambda s: None
        ),
    )
    result = run("--fetch")
    assert "asked us to slow down; stopped" in result.output
    assert "not looked at (fetch limit reached)" in result.output
    assert link_of(people["alpha"]) == WIKI + "Alpha_Trion_(G1)"


def test_a_run_without_fetching_never_uses_the_network(people, monkeypatch):
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
