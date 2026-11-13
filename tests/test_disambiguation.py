"""A name that used to be a character page is now a disambiguation page.

``Battletrap#Power_of_the_Primes`` should become ``Battletrap_(G1)#Power_of_the_Primes``:
the section is on exactly one of the pages the disambiguation page lists. The
disambiguation text is the real page (recorded 12 November 2026); the namesake pages
are small stand-ins. Nothing here touches the network.
"""

import json

import pytest

from app import app as flask_app, db
from app import refresh
from app.models import Figure
from app.tfwiki import modernise as m
from app.tfwiki import parser
from app.tfwiki.fetcher import Disabled, Fetcher, PageNotFound, cache_name
from app.tfwiki.figure import FigureNotFound, FigureOnSeveralPages, read_figure

WIKI = "https://tfwiki.net/wiki/"
OLD = WIKI + "Battletrap#Power_of_the_Primes"
NEW = WIKI + "Battletrap_(G1)#Power_of_the_Primes"

DISAMBIGUATION = """Those named '''Battletrap''' seem to like two things: battles and traps. Perhaps they'd appear in more media if they branched out a little.

==Major Battletraps==
<center><gallery widths="250px" heights="200px">
File:ROTB-Battletrap-Render.jpg|[[Battletrap (ROTB)|''Rise of the Beasts'' Battletrap]]
</gallery></center>

==Full list of Battletraps==
{{disamb|y=[[1987]]|[[Battletrap (G1)|Battletrap]], the [[Decepticon]] [[Duocon]] from [[The Transformers (franchise)|Generation 1]].}}
{{disamb|y=[[2020]]|[[Battletrap (Cyberverse)|Battletrap]], the Decepticon soldier from ''[[Transformers: Cyberverse (franchise)|Cyberverse]]''.}}
{{disamb|y=[[2023]]|[[Battletrap (ROTB)|Battletrap]], the [[Terrorcon (ROTB)|Terrorcon]] from ''[[Transformers: Rise of the Beasts (franchise)|Rise of the Beasts]]''.}}

==Not to be confused with...==
* [[Battleslash]] and [[Roadtrap (POTP)|Roadtrap]], who sometimes combine to form Battletrap.
* [[Rattletrap]], the [[Autobot]] from ''[[Transformers Animated (franchise)|Transformers Animated]]''.


{{disambig}}
"""


def character_page(name, *toylines):
    lines = [
        "%s is a [[Decepticon]] from the [[Generation 1 continuity family]]." % name
    ]
    lines += ["==Toys=="]
    for toyline in toylines:
        lines += ["===''%s''===" % toyline, ":''A prose description of the toy.''"]
    return "\n".join(lines) + "\n"


PAGES = {
    "Battletrap_(G1)": (
        "Battletrap (G1)",
        character_page("Battletrap", "Power of the Primes"),
    ),
    "Battletrap_(Cyberverse)": (
        "Battletrap (Cyberverse)",
        character_page("Battletrap", "Cyberverse"),
    ),
    "Battletrap_(ROTB)": (
        "Battletrap (ROTB)",
        character_page("Battletrap", "Rise of the Beasts"),
    ),
}


def write(folder, requested, title, text):
    (folder / cache_name(requested)).write_text(
        json.dumps({"parse": {"title": title, "wikitext": {"*": text}}})
    )


def wiki_in(folder, pages=None, skip=()):
    """Cache the redirect, the disambiguation page and the namesakes."""
    write(folder, "Battletrap", "Battletrap (disambiguation)", DISAMBIGUATION)
    for requested, (title, text) in (pages or PAGES).items():
        if requested not in skip:
            write(folder, requested, title, text)
    return Fetcher(str(folder), get=lambda url: pytest.fail("no network: " + url))


@pytest.fixture
def folder(tmp_path):
    return tmp_path


# --- the parser's readers -------------------------------------------------------------


def test_the_namesakes_are_the_first_link_of_each_list_item():
    assert parser.is_disambiguation(DISAMBIGUATION)
    assert parser.disambiguation_targets(DISAMBIGUATION) == [
        "Battletrap_(G1)",
        "Battletrap_(Cyberverse)",
        "Battletrap_(ROTB)",
    ]  # not the gallery, and not "not to be confused with"


def test_other_ways_of_writing_a_list_item():
    text = (
        "{{disamb|y=[[1987|'87]]|[[Same (G1)|Same]], one.}}\n"
        "{{disamb|[[No Year (G1)]], two.}}\n"
        "{{disamb|y=1990|[[Same (G1)|Same again]], a repeat.}}\n"
        "{{disamb|y=1991|[[Other#Section|x]]}}\n"
    )
    assert parser.disambiguation_targets(text) == ["Same_(G1)", "No_Year_(G1)", "Other"]
    assert parser.disambiguation_targets("Just prose with [[a link]].") == []
    assert not parser.is_disambiguation("A character page about Battletrap.")


def test_same_fragment_keeps_capitals():
    same = parser.same_fragment
    assert same("Power_of_the_Primes", "Power of the Primes")
    assert same("Robots_in_Disguise_.282001.29", "Robots in Disguise (2001)")
    assert not same("power_of_the_primes", "Power of the Primes")


# --- the figure reader ------------------------------------------------------------------


def test_a_fragment_found_on_exactly_one_listed_page_is_resolved(folder):
    found = read_figure(wiki_in(folder), OLD)
    assert found["page"] == "Battletrap (G1)" and found["moved"] is True
    assert found["disambiguated"] == "Battletrap (disambiguation)"
    (candidate,) = found["candidates"]
    assert candidate["link"] == NEW and candidate["matched_by"] == "heading"
    assert found["character"]["link"] == WIKI + "Battletrap_(G1)"


def test_the_resolved_figure_has_its_suggestions(folder):
    (candidate,) = read_figure(wiki_in(folder), OLD)["candidates"]
    assert candidate["fields"]["toyline"] == "Power of the Primes"
    (bare,) = read_figure(wiki_in(folder), OLD, fields=False)["candidates"]
    assert bare["fields"] is None and bare["link"] == NEW


def test_a_fragment_on_several_listed_pages_is_not_guessed(folder):
    pages = dict(PAGES)
    pages["Battletrap_(ROTB)"] = (
        "Battletrap (ROTB)",
        character_page("Battletrap", "Power of the Primes"),
    )
    with pytest.raises(FigureOnSeveralPages) as raised:
        read_figure(wiki_in(folder, pages), OLD)
    assert raised.value.available == ["Battletrap (G1)", "Battletrap (ROTB)"]
    assert "more than one page it lists" in str(raised.value)


def test_a_section_with_capitals_that_differ_is_not_a_match(folder):
    with pytest.raises(
        FigureNotFound, match="none of the 3 pages it lists has it"
    ) as raised:
        read_figure(wiki_in(folder), WIKI + "Battletrap#power_of_the_primes")
    assert raised.value.available == [
        "Battletrap (G1)",
        "Battletrap (Cyberverse)",
        "Battletrap (ROTB)",
    ]


def test_a_fragment_that_is_nowhere_says_the_page_is_a_disambiguation(folder):
    with pytest.raises(FigureNotFound, match="is a disambiguation page"):
        read_figure(wiki_in(folder), WIKI + "Battletrap#Nonesuch")


def test_without_a_fragment_there_is_nothing_to_look_for(folder):
    with pytest.raises(FigureNotFound, match="No figures on Battletrap"):
        read_figure(wiki_in(folder), WIKI + "Battletrap")


def test_a_namesake_page_that_is_not_cached_stops_the_answer(folder):
    with pytest.raises(Disabled):
        read_figure(wiki_in(folder, skip=("Battletrap_(ROTB)",)), OLD)


def test_a_namesake_page_that_has_been_deleted_is_skipped():
    class Wiki:
        def page(self, title, refresh=False):
            if title == "Battletrap":
                return "Battletrap (disambiguation)", DISAMBIGUATION
            if title == "Battletrap_(ROTB)":
                raise PageNotFound(title)
            if title in PAGES:
                return PAGES[title]
            raise PageNotFound(title)

    assert read_figure(Wiki(), OLD)["page"] == "Battletrap (G1)"


def test_a_namesake_that_is_itself_a_disambiguation_page_is_not_followed():
    class Wiki:
        asked = []

        def page(self, title, refresh=False):
            self.asked.append(title)
            if title == "Battletrap":
                return "Battletrap (disambiguation)", DISAMBIGUATION
            return title.replace("_", " "), "{{disamb|[[Battletrap]]}}\n{{disambig}}\n"

    wiki = Wiki()
    with pytest.raises(FigureNotFound):
        read_figure(wiki, OLD)
    assert len(wiki.asked) == 4  # the disambiguation page and its three namesakes


# --- the link updater -----------------------------------------------------------------


def test_the_link_updater_rewrites_to_the_page_that_has_the_section(folder):
    result = m.check(wiki_in(folder), OLD)
    assert result.status == m.REWRITE and result.new == NEW


def test_the_fragment_is_kept_exactly_as_saved_through_a_disambiguation(folder):
    pages = dict(PAGES)
    pages["Battletrap_(G1)"] = (
        "Battletrap (G1)",
        character_page("Battletrap", "Robots in Disguise (2001)"),
    )
    result = m.check(
        wiki_in(folder, pages), WIKI + "Battletrap#Robots_in_Disguise_.282001.29"
    )
    assert result.new == WIKI + "Battletrap_(G1)#Robots_in_Disguise_.282001.29"


def test_the_link_updater_leaves_a_link_alone_when_several_pages_have_it(folder):
    pages = dict(PAGES)
    pages["Battletrap_(Cyberverse)"] = (
        "Battletrap (Cyberverse)",
        character_page("Battletrap", "Power of the Primes"),
    )
    result = m.check(wiki_in(folder, pages), OLD)
    assert result.status == m.SEVERAL_PAGES and result.new is None
    assert "Battletrap (Cyberverse), Battletrap (G1)" in result.detail


def test_the_link_updater_reports_a_disambiguation_with_no_match_and_an_uncached_page(
    folder,
):
    assert m.check(wiki_in(folder), WIKI + "Battletrap#Nonesuch").status == m.NO_FIGURE
    other = folder / "without_g1"
    other.mkdir()
    assert (
        m.check(wiki_in(other, skip=("Battletrap_(G1)",)), OLD).status == m.NOT_CACHED
    )


# --- Add from TFWiki and the Edit page's refresh ------------------------------------------


@pytest.fixture
def battletrap_cache(folder, monkeypatch):
    wiki_in(folder)
    monkeypatch.setitem(flask_app.config, "TFWIKI_CACHE_DIR", str(folder))
    monkeypatch.setitem(flask_app.config, "TFWIKI_ENABLED", False)
    return folder


def test_add_from_tfwiki_follows_the_disambiguation(
    auth_client, battletrap_cache, seed
):
    html = auth_client.post("/addfromtfwiki/lookup", data={"url": OLD}).get_data(
        as_text=True
    )
    assert 'action="/addfromtfwiki/save"' in html
    assert "the link was updated to that page" in html
    assert 'value="%s"' % NEW in html


def test_add_from_tfwiki_says_when_several_pages_have_it(
    auth_client, folder, monkeypatch, seed
):
    pages = dict(PAGES)
    pages["Battletrap_(ROTB)"] = (
        "Battletrap (ROTB)",
        character_page("Battletrap", "Power of the Primes"),
    )
    wiki_in(folder, pages)
    monkeypatch.setitem(flask_app.config, "TFWIKI_CACHE_DIR", str(folder))
    monkeypatch.setitem(flask_app.config, "TFWIKI_ENABLED", False)
    html = auth_client.post("/addfromtfwiki/lookup", data={"url": OLD}).get_data(
        as_text=True
    )
    assert "more than one page it lists" in html
    assert "<li>Battletrap (G1)</li>" in html and "<li>Battletrap (ROTB)</li>" in html


def test_the_edit_pages_refresh_proposes_the_new_link(
    auth_client, battletrap_cache, seed
):
    figure = db.session.get(Figure, seed["figure"].id)
    figure.link = OLD
    db.session.commit()
    html = auth_client.post("/refreshfigure/%s/compare" % figure.id).get_data(
        as_text=True
    )
    assert "Link to Figure" in html and NEW in html
    assert "the figure is on Battletrap (G1)" in html
    resp = auth_client.post(
        "/refreshfigure/%s/apply" % figure.id,
        data={"pick": "0", "choice_link": "accept"},
    )
    assert resp.status_code == 302
    db.session.expire_all()
    assert db.session.get(Figure, figure.id).link == NEW


def test_modernise_links_command_lists_the_disambiguation_rewrite(
    auth_client, battletrap_cache, seed
):
    from click.testing import CliRunner

    from app import modernise as cli

    figure = db.session.get(Figure, seed["figure"].id)
    figure.link = OLD
    db.session.commit()
    result = CliRunner().invoke(cli.modernise_links, [])
    assert result.exit_code == 0, result.output
    assert OLD + "\n    -> " + NEW in result.output
    assert "1 links would be rewritten" in result.output
    CliRunner().invoke(cli.modernise_links, ["--apply"])
    db.session.expire_all()
    assert db.session.get(Figure, figure.id).link == NEW
    assert refresh.same_link(NEW, db.session.get(Figure, figure.id).link)
