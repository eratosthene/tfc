"""Reading figure sections out of recorded tfwiki.net pages (tests/fixtures/tfwiki).

The fixtures are real API responses recorded on 11 November 2026, so these
tests show what the parser makes of the pages in issue #53.
"""

import json
import os

import pytest

from app.tfwiki import parser
from app.tfwiki.fetcher import Fetcher, cache_name
from app.tfwiki.figure import FigureNotFound, read_figure

FIXTURES = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "tfwiki"
)
WIKI = "https://tfwiki.net/wiki/"


@pytest.fixture(scope="module")
def fetcher():
    # Fetching is off, so a test that needs a page that is not recorded fails.
    return Fetcher(FIXTURES, get=lambda url: pytest.fail("no network: " + url))


def cache_pages(folder, pages):
    """Write {title: wikitext} as cached API responses."""
    for title, text in pages.items():
        (folder / cache_name(title)).write_text(
            json.dumps({"parse": {"title": title, "wikitext": {"*": text}}})
        )


def read(fetcher, url, **kwargs):
    return read_figure(fetcher, url, **kwargs)


def only(result):
    assert len(result["candidates"]) == 1
    return result["candidates"][0]


# --- links ------------------------------------------------------------------


def test_parse_url():
    assert parser.parse_url(WIKI + "Alpha_Trion/toys#Legacy") == (
        "Alpha_Trion/toys",
        "Legacy",
    )
    assert parser.parse_url("http://www.tfwiki.net/wiki/Blaster_%28FOC%29") == (
        "Blaster_(FOC)",
        None,
    )
    assert parser.parse_url(WIKI + "Omega_Prime#Robots_in_Disguise_.282001.29")[1] == (
        "Robots_in_Disguise_.282001.29"
    )
    for bad in (
        "https://example.com/wiki/Alpha_Trion",
        "ftp://tfwiki.net/wiki/X",
        "https://tfwiki.net/",
        "https://tfwiki.net/wiki/",
        "https://tfwiki.net/mediawiki/api.php",
    ):
        with pytest.raises(parser.ParseError):
            parser.parse_url(bad)


def test_anchors_and_headings_compare_alike():
    assert (
        parser.decode_anchor("Robots_in_Disguise_.282001.29")
        == "Robots_in_Disguise_(2001)"
    )
    assert parser.norm("Robots_in_Disguise_.282001.29") == parser.norm(
        "Robots in Disguise (2001)"
    )
    assert parser.norm("Legacy ") == parser.norm("legacy")


def test_page_urls():
    assert parser.page_url("Scourge (G1)/toys", "Studio Series") == (
        WIKI + "Scourge_(G1)/toys#Studio_Series"
    )
    assert parser.page_url("Alpha Trion") == WIKI + "Alpha_Trion"


def test_character_pages():
    assert (
        parser.character_page("Optimus Prime (G1)/Generations toys")
        == "Optimus Prime (G1)"
    )
    assert parser.character_page("Alpha_Trion/toys") == "Alpha_Trion"
    assert parser.character_page("Boater") == "Boater"
    assert parser.split_title("Bumblebee (Animated)/toys") == ("Bumblebee", "Animated")
    assert parser.split_title("Boater") == ("Boater", None)
    assert parser.character("Bumblebee (Animated)/toys") == {
        "name": "Bumblebee",
        "qualifier": "Animated",
        "page": "Bumblebee (Animated)",
        "link": WIKI + "Bumblebee_(Animated)",
    }


def test_links_in_text():
    found = parser.links(
        "[[Scourge (G1)/toys#Studio Series|Scourge]] [[#Generations|here]] "
        "[[File:x.jpg|thumb]] [[:Category:Y]] [[Plain]] [[Soundwave (WFC)#Voyager]]",
        "Blaster (FOC)",
    )
    assert [(link["text"], link["url"]) for link in found] == [
        ("Scourge", WIKI + "Scourge_(G1)/toys#Studio_Series"),
        ("here", WIKI + "Blaster_(FOC)#Generations"),
        ("Plain", WIKI + "Plain"),
        ("Soundwave (WFC)", WIKI + "Soundwave_(WFC)#Voyager"),
    ]
    assert found[2]["fragment"] is None


def test_toys_pointers():
    text = "{{main|Mighty Eagle#As X}} {{main|Alpha Trion/toys}} {{Main|A/Generations_toys|B/toys#Z}} {{main|Alpha Trion/toys}}"
    assert parser.toys_pointers(text, "Alpha Trion") == [
        "Alpha_Trion/toys",
        "A/Generations_toys",
        "B/toys",
    ]


def test_clean_and_split_top_level():
    text = (
        "''[[Studio Series|SS]]'' Rifle<ref name=a>x</ref><!-- c -->{{t|u}}[[File:a.jpg|b]]"
        "<br>[http://x.y A site] <b>bold</b> [[A#b]]"
    )
    assert parser.clean(text) == "SS Rifle, A site bold A#b"
    assert parser.split_top_level("a, b (c, d), e,") == ["a", "b (c, d)", "e"]
    assert parser.split_top_level("a) b, c") == ["a) b", "c"]


# --- one entry --------------------------------------------------------------


def test_alpha_trion_legacy(fetcher):
    result = read(fetcher, WIKI + "Alpha_Trion/toys#Legacy")
    assert result["page"] == "Alpha Trion/toys" and not result["moved"]
    assert result["character"]["name"] == "Alpha Trion"
    assert result["character"]["qualifier"] is None
    assert result["character"]["link"] == WIKI + "Alpha_Trion"
    c = only(result)
    assert c["matched_by"] == "heading"
    assert c["link"] == WIKI + "Alpha_Trion/toys#Legacy"
    f = c["fields"]
    # A 2-pack: the figure's own name is the pack's, "A Hero is Born".
    assert f["name"] == "A Hero is Born" and f["is_pack"]
    assert f["release_year"] == 2022 and f["classes"] == ["2-pack"]
    assert f["faction"] == {"value": "Autobot", "source": "Bp-a1"}
    assert f["accessories"] == "Rifle, Vector Sigma, Key to Vector Sigma, stand"
    assert f["accessories_list"] == [
        "Rifle",
        "Vector Sigma",
        "Key to Vector Sigma",
        "stand",
    ]
    assert f["toyline"] == "Legacy"
    assert f["tooling"]["values"] == ["Retool"]
    assert "retool" in f["tooling"]["evidence"]
    # "a hefty retool of Scourge", not the later "retooled into Senator Ratbat".
    assert [(a["name"], a["link"]) for a in f["ancestors"]] == [
        ("Scourge", WIKI + "Scourge_(G1)/toys#Studio_Series")
    ]
    # Sold "with Orion Pax"; the Taiwanese fans' Victory Saber is not in the pack.
    assert [(p["name"], p["link"]) for p in f["packed_with"]] == [
        ("Orion Pax", WIKI + "Optimus_Prime_(G1)/Generations_toys#Legacy")
    ]
    assert f["picture"] == {
        "file": "Legacy-toy_AlphaTrion.jpg",
        "page": WIKI + "File:Legacy-toy_AlphaTrion.jpg",
        "url": WIKI + "Special:FilePath/Legacy-toy_AlphaTrion.jpg",
    }
    assert c["block"].startswith("<ul")


def test_the_old_link_is_followed_to_the_toys_page(fetcher):
    result = read(fetcher, WIKI + "Alpha_Trion_(G1)#Legacy")
    assert result["moved"] and result["page"] == "Alpha Trion/toys"
    assert only(result)["link"] == WIKI + "Alpha_Trion/toys#Legacy"


def test_faction_word_is_removed_but_a_continuity_stays(fetcher):
    blaster = only(read(fetcher, WIKI + "Blaster_(FOC)#Generations"))["fields"]
    assert blaster["name"] == "Blaster"  # "Autobot Blaster" on the page
    assert blaster["faction"] == {"value": "Autobot", "source": "name prefix"}
    assert blaster["release_year"] == 2012 and blaster["classes"] == ["Voyager"]
    assert blaster["bp_code"] is None
    assert blaster["tooling"]["values"] == ["Redeco", "Retool"]
    assert [a["link"] for a in blaster["ancestors"]] == [
        WIKI + "Soundwave_(WFC)#GenerationsVoyager"
    ]
    assert blaster["accessories"] == "rifle"
    bee = only(read(fetcher, WIKI + "Bumblebee_(Animated)/toys#Legacy"))
    assert bee["fields"]["name"] == "Animated Universe Bumblebee"
    assert bee["fields"]["accessories"] == "2 Turbo Boosters, 2 stingers"
    assert bee["fields"]["tooling"] is None and bee["fields"]["ancestors"] == []


def test_character_with_a_qualifier_and_a_redirect(fetcher):
    result = read(fetcher, WIKI + "Bumblebee_(Animated)/toys#Legacy")
    assert result["character"]["name"] == "Bumblebee"
    assert result["character"]["qualifier"] == "Animated"
    # /toys redirects to the character page for Blackarachnia: the toys are there.
    result = read(fetcher, WIKI + "Blackarachnia_(BW)/toys#Beast_Machines")
    assert result["moved"] and result["page"] == "Blackarachnia (BW)"
    assert result["character"]["qualifier"] == "BW"
    # Two figures share that heading: both are offered, the review picks one.
    assert [c["fields"]["classes"] for c in result["candidates"]] == [
        ["Deluxe Class"],
        ["Happy Meal"],
    ]
    assert all(
        c["fields"]["faction"]["value"] == "Maximal" for c in result["candidates"]
    )


def test_a_page_with_no_suffix(fetcher):
    result = read(fetcher, WIKI + "Boater#Legacy")
    assert result["character"]["qualifier"] is None
    f = only(result)["fields"]
    assert f["name"] == "Deathsaurus" and f["release_year"] == 2023
    assert f["faction"]["value"] == "Decepticon"
    # "only available with the HasLab Deathsaurus set": HasLab is not a figure.
    assert [p["name"] for p in f["packed_with"]] == ["Deathsaurus"]


def test_a_combiner_lists_its_five_figures(fetcher):
    f = only(read(fetcher, WIKI + "Bruticus_(G1)#Age_of_the_Primes"))["fields"]
    assert f["name"] == "Bruticus" and f["release_year"] == 2025
    assert [c["name"] for c in f["components"]][:2] == [
        "1 of 5: Combaticon Vortex",
        "2 of 5: Combaticon Blast Off",
    ]
    assert f["components"][4]["link"] == WIKI + "Swindle_(G1)#Age_of_the_Primes"
    assert f["is_pack"]


def test_an_anchor_with_old_escaping_and_alternate_names(fetcher):
    result = read(fetcher, WIKI + "Omega_Prime#Robots_in_Disguise_.282001.29")
    assert len(result["candidates"]) > 3
    first = result["candidates"][0]["fields"]
    assert first["toyline"] == "Robots in Disguise (2001)"
    # "Super Fire Convoy (2000) / Optimus Prime (Super Class, 2001)"
    assert first["names"] == ["Super Fire Convoy", "Optimus Prime"]
    assert first["release_year"] == 2000
    clear = [c for c in result["candidates"] if "Clear" in c["fields"]["name"]][0]
    assert clear["fields"]["accessories"] == "Super God Sword"
    only_omega = only(read(fetcher, WIKI + "Omega_Prime#Legacy"))
    assert only_omega["fields"]["name"] == "Omega Prime"


def test_generations_toys_page_and_an_anchor(fetcher):
    c = only(read(fetcher, WIKI + "Optimus_Prime_(G1)/Generations_toys#HasbroPulse"))
    assert c["matched_by"] == "anchor"
    assert c["link"] == WIKI + "Optimus_Prime_(G1)/Generations_toys#HasbroPulse"
    f = c["fields"]
    assert f["bp_code"] == "multi" and f["faction"] is None  # no side: left to the user
    assert f["name"] == "A Hero Is Born"


def test_a_symbol_class_is_looked_up_and_may_name_no_known_faction(tmp_path, fetcher):
    # megatronusbp is Bp-pr12's class: a side the app does not know.
    f = only(read(fetcher, WIKI + "The_Fallen/toys#Age_of_the_Primes"))["fields"]
    assert f["bp_code"] == "pr12" and f["faction"] is None
    assert f["symbol_class"] == "megatronusbp"
    assert f["takara_id"] == "AOTP-06"


def test_a_symbol_class_names_a_faction():
    recorded = Fetcher(FIXTURES, get=lambda url: pytest.fail(url))
    # Bp-a1 is recorded: autobotg1 -> Autobot, for a code with no letter mapping.
    from app.tfwiki import figure

    assert figure._symbol(recorded, "a1", ("Autobot",)) == ("autobotg1", "Autobot")
    assert figure._symbol(recorded, "pr12", ("Autobot",)) == ("megatronusbp", None)
    assert figure._symbol(recorded, "zzz", ("Autobot",)) == (None, None)


def test_a_faction_is_found_from_the_symbol_when_the_code_gives_none(tmp_path):
    cache_pages(
        tmp_path,
        {
            "Toy": "==Toys==\n===T===\n<ul>{{Bp-zz9|'''Thing''' (Deluxe, 2020)}}</ul>\n",
            "Template:Bp-zz9": '<li class="decepticong2">{{{1}}}</li>',
        },
    )
    f = only(read(Fetcher(str(tmp_path)), WIKI + "Toy#T"))["fields"]
    assert f["faction"] == {
        "value": "Decepticon",
        "source": "symbol class decepticong2",
    }


def test_figure_not_found_lists_what_is_there(fetcher, tmp_path):
    cache_pages(tmp_path, {"Empty": "Just prose."})
    with pytest.raises(FigureNotFound) as info:
        read(fetcher, WIKI + "Alpha_Trion/toys#Nothing")
    assert "#Nothing" in str(info.value) and "Legacy" in info.value.available
    with pytest.raises(FigureNotFound, match="No figures on Empty") as info:
        read(Fetcher(str(tmp_path)), WIKI + "Empty")
    assert info.value.available == []
    with pytest.raises(parser.ParseError):
        read(fetcher, "https://example.com/wiki/X")


def test_without_a_fragment_every_figure_is_a_candidate(fetcher):
    result = read(fetcher, WIKI + "Alpha_Trion/toys")
    assert len(result["candidates"]) > 3
    first = result["candidates"][0]
    assert first["matched_by"] is None and "#" in first["link"]


# --- details ----------------------------------------------------------------


def test_faction_helpers():
    assert parser.strip_faction_prefix("Autobot Blaster") == ("Blaster", "Autobot")
    assert parser.strip_faction_prefix("decepticon  Soundwave") == (
        "Soundwave",
        "Decepticon",
    )
    assert parser.strip_faction_prefix("Animated Universe Bumblebee") == (
        "Animated Universe Bumblebee",
        None,
    )
    assert parser.strip_faction_prefix("Autobot") == ("Autobot", None)
    assert parser.strip_faction_prefix("Wasp Hunter", ("Wasp",)) == ("Hunter", "Wasp")
    assert parser.faction_from_code("a1") == "Autobot"
    assert parser.faction_from_code("p1") == "Predacon"
    assert parser.faction_from_code("a1d1") is None
    assert parser.faction_from_code("multi") is None
    assert parser.faction_from_code(None) is None
    assert (
        parser.bullet_class('<includeonly><li class="autobotg1">{{{1}}}') == "autobotg1"
    )
    assert parser.bullet_class("nothing") is None
    assert (
        parser.faction_from_class("autobotg1", ("Autobot", "Decepticon")) == "Autobot"
    )
    assert parser.faction_from_class("megatronusbp", ("Autobot",)) is None
    assert parser.faction_from_class(None) is None


def test_years_and_classes():
    assert parser.year_and_class("Deluxe Class, [[2024]]") == (2024, ["Deluxe Class"])
    assert parser.year_and_class("[[2025]]–[[2026]]") == (2025, [])
    assert parser.year_and_class("Mini, <s>1984</s>, 1985/1986") == (1985, ["Mini"])
    assert parser.year_and_class("?") == (None, [])
    assert parser.year_and_class("[[May 25]], [[2013]]") == (2013, ["May 25"])


def test_bullet_fields_accept_both_layouts():
    fields = parser.bullet_fields(
        [
            ("Takara ID number:", " '''D-69''', '''C-56'''"),
            ("hasbro id", " A1234"),
            ("Accessories:", " rifle, [[Key (x)|key]] (a, b)"),
            ("Accessories", " ignored second"),
            ("Series / Number:", " '''1 / 004'''"),
            ("Hasbro ID number", ""),
        ]
    )
    assert fields == {
        "takara_id": "D-69, C-56",
        "hasbro_id": "A1234",
        "accessories": "rifle, key (a, b)",
        "accessories_list": ["rifle", "key (a, b)"],
    }


def test_the_old_layout_and_pictures():
    text = (
        "==Fiction==\nprose\n==Toys==\n===''Generations''===\n[[File:First.jpg|thumb]]\n"
        "*'''Autobot Blaster''' (Voyager, 2012)\n**''Series / Number:'' '''1 / 004'''\n"
        "**''Accessories:'' rifle\n: A [[redeco]] and [[retool]] of ''X'' [[Soundwave (WFC)#G|Soundwave]].\n"
        "{{--}}\n{{anchor|Jp}}\n"
        "<gallery>\nFile:Gallery.jpg|caption\n</gallery>\n"
        "*'''Blaster & Steeljaw''' ([[May 25]], [[2013]])\n"
        "====''Sub''====\n*'''Third''' (2014)\n==Notes==\n*'''Not a toy''' (2000)\n"
    )
    found = parser.entries(text, "Blaster (FOC)")
    assert [e["header"].split("'''")[1] for e in found] == [
        "Autobot Blaster",
        "Blaster & Steeljaw",
        "Third",
    ]
    assert found[0]["picture"] == "First.jpg" and found[0]["heading"] == "Generations"
    assert found[1]["anchors"] == ["Jp"] and found[1]["picture"] == "Gallery.jpg"
    assert found[2]["subheading"] == "Sub"
    assert parser.matches(found[1], "jp") == "anchor"
    assert parser.matches(found[2], "sub") == "heading"
    assert parser.matches(found[0], "nothing") is None
    assert parser.picture(None) is None


def test_a_page_without_a_toys_heading_is_read_whole():
    found = parser.entries("===T===\n<ul>{{Bp-d1|'''X''' (2001)}}</ul>\n", "X/toys")
    assert len(found) == 1 and found[0]["picture"] is None
    # A page with several ==Toys== style headings keeps the first section only.
    found = parser.entries(
        "==Toys==\n*'''A''' (2000)\n==Other==\n*'''B''' (2001)\n", "X"
    )
    assert len(found) == 1


def test_descendants_and_unrelated_links_are_not_ancestors():
    entry = {
        "paragraphs": [
            "This mold was also retooled into [[Ratbat (G1)/toys#Legacy|Senator Ratbat]].",
            "Compatible with [[Rifle (G1)#Legacy|a rifle]].",
            "A [[reissue]] of [[Prowl (G1)#Siege|Prowl]] packed with [[Prowl (G1)#Siege|Prowl]] "
            "and [[Hasbro Pulse#Haslab|HasLab]], [[Kup (G1)#X|Kup]], [[Kup (G1)#X|Kup]].",
        ]
    }
    tooling, ancestors = parser.history(entry, "Prowl (G1)")
    assert tooling["values"] == ["Reissue"]
    assert [a["name"] for a in ancestors] == ["Prowl"]
    got = parser.packed_with(entry, "Prowl (G1)", (WIKI + "Prowl_(G1)#Siege",))
    assert [p["name"] for p in got] == ["Kup"]
    # A keyword with "of" but no figure link after it still suggests the tooling.
    assert parser.history({"paragraphs": ["A retool of the old mold."]}, "X") == (
        {"values": ["Retool"], "evidence": "A retool of the old mold."},
        [],
    )
    assert parser.history({"paragraphs": ["Nothing here."]}, "X") == (None, [])


def test_the_year_may_be_on_a_later_name():
    header = "'''Go Foo''' / '''Foo''' (Super Class, 2001)"
    entry = {
        "header": header,
        "code": "a1",
        "bullets": [],
        "paragraphs": [],
        "components": [],
        "heading": "",
        "anchors": [],
        "picture": None,
    }
    f = parser.figure_fields(entry, "Foo")
    assert f["release_year"] == 2001 and f["names"] == ["Go Foo", "Foo"]
    entry["header"] = "'''Foo''' (?) / '''Bar''' (?)"
    assert parser.figure_fields(entry, "Foo")["release_year"] is None


# --- the lead sentence of a character page -----------------------------------------------


@pytest.mark.parametrize(
    "page, expected",
    [
        ("Omega_Prime", {"family": "Robots in Disguise", "faction": "Autobot"}),
        ("Bruticus_(G1)", {"family": "Generation 1", "faction": "Decepticon"}),
        (
            "Blaster_(FOC)",
            {"family": "Aligned", "faction": "Autobot", "portion": "Fall of Cybertron"},
        ),
        # The link target has "Fight! Super..." in it: that "!" does not end a sentence.
        (
            "Boater",
            {"family": "Generation 1", "faction": "Autobot", "portion": "Victory"},
        ),
    ],
)
def test_the_lead_sentence_of_recorded_pages(fetcher, page, expected):
    found = parser.lead(fetcher.page(page)[1])
    assert {k: v for k, v in found.items() if k != "sentence"} == expected
    assert found["sentence"].startswith(":") and " is a" in found["sentence"]
    assert "continuity family" in found["sentence"]


def test_a_page_that_only_mentions_a_family_later_has_no_lead(fetcher):
    # Alpha Trion's page names the Aligned family in a paragraph about his history.
    assert parser.lead(fetcher.page("Alpha_Trion_(G1)")[1]) is None
    assert parser.lead(fetcher.page("Alpha_Trion/toys")[1]) is None


def test_lead_on_small_texts():
    lead = parser.lead
    assert lead("") is None
    assert lead("Bare [[continuity family]] link.") is None
    found = lead(
        "Earlier text. X is a [[Thing]] from the [[Foo continuity family]]. More."
    )
    assert found == {
        "sentence": "X is a Thing from the Foo continuity family.",
        "family": "Foo",
    }
    assert (
        lead("X is an [[Autobot]] from the [[Foo continuity family|Foo]].")["faction"]
        == "Autobot"
    )
    assert "faction" not in lead(
        "X is an [[Autobot]] from the [[Foo continuity family]].", ("Maximal",)
    )
    assert lead("X was mentioned in the [[Foo continuity family]].") is None


@pytest.mark.parametrize(
    "line, expected",
    [
        # Real sentences from pages in the cache.
        (
            ":''The Air Warriors are [[Decepticon]]s from the [[Generation 1 continuity family]].''",
            {"family": "Generation 1", "faction": "Decepticon"},
        ),
        (
            ":''Blaster is an evil [[Autobot]] from the [[Transformers: Shattered Glass (franchise)|Shattered Glass]] [[continuity family]].''",
            {"family": "Shattered Glass", "faction": "Autobot"},
        ),
        (
            ":''Buzzsaw is a [[Decepticon]] from the [[Transformers: Revenge of the Fallen (franchise)|Revenge of the Fallen]] portion of the [[Live-action film series|live-action film]] [[continuity family]].''",
            {
                "family": "live-action film",
                "faction": "Decepticon",
                "portion": "Revenge of the Fallen",
            },
        ),
        (
            ":''8-Trax is an [[Autobot]] from [[Stranger Things]] (via [[Transformers Collaborative|Collaborative]]).''",
            None,
        ),
    ],
)
def test_lead_sentences_from_the_wild(line, expected):
    found = parser.lead(line)
    if expected is None:
        assert found is None
    else:
        assert {k: v for k, v in found.items() if k != "sentence"} == expected


# --- toylines described in prose (no figure line) ----------------------------------------


PROSE_PAGE = """Intro.
==Toys==
===''Line A''===
[[File:A-toy.jpg|thumb]]
:''Part of the second wave of A toys, this is a [[redeco]] of [[Other (G1)/toys#A|Other]].''
:''Hasbro ID number'': '''E1234'''
===''Line B''===
{{anchor|BOne}}
<ul class="iconlist">{{Bp-a1|'''Bee''' (Deluxe Class, 2001)}}</ul>
:*''Accessories'': Rifle
====Sub heading====
:A paragraph under B.
===''Line C''===
{{-}}
===''Line D''===
:''A prose line at the end.''
==Other section==
Text.
"""


def test_a_toyline_with_no_figure_line_is_one_entry_for_its_section():
    found = parser.entries(PROSE_PAGE, "Mover (G1)")
    assert [(e["heading"], bool(e["header"])) for e in found] == [
        ("Line A", False),  # prose only: a section entry
        ("Line B", True),  # a real figure line: no section entry for B as well
        ("Line D", False),
    ]  # Line C has nothing but a spacer, so it is skipped
    section = found[0]
    assert section["code"] is None and section["anchors"] == []
    assert section["bullets"] == [("Hasbro ID number", "'''E1234'''")]
    assert section["paragraphs"] and section["picture"] == "A-toy.jpg"
    assert "A-toy.jpg" in "\n".join(section["lines"])


def test_a_section_entry_makes_fields_without_a_name():
    section = parser.entries(PROSE_PAGE, "Mover (G1)")[0]
    fields = parser.figure_fields(section, "Mover (G1)")
    assert fields["name"] == "" and fields["release_year"] is None
    assert fields["hasbro_id"] == "E1234" and fields["toyline"] == "Line A"
    assert fields["tooling"]["values"] == ["Redeco"]


def test_a_link_to_a_prose_toyline_matches_by_heading():
    section = parser.entries(PROSE_PAGE, "Mover (G1)")[0]
    assert parser.matches(section, "Line_A") == "heading"
    assert parser.matches(section, "Line B") is None


# --- a toys page whose toylines are level-2 headings (no ==Toys== heading) -----------------

# The shape of Hot Rod (G1)/toys: every toyline is its own ==heading==, and some figures
# are old-style "*'''Name''' (...)" lines.
LEVEL_TWO_PAGE = """Intro text.
==''The Transformers''==
*'''Hot Rod''' (Original, 1986)
**''Accessories:'' Rifle
==''Vintage G1''==
[[File:Walmart-Vintage-G1-Hot-Rod.jpg|thumb|Till all are bought!]]
*'''Hot Rod''' (Walmart exclusive reissue, 2018)
**''Accessories:'' 2 photon lasers
:In a very unexpected turn, the toy was reissued as a [[Walmart]] exclusive.
{{--}}
==''Studio Series''==
<ul class="iconlist">{{Bp-a1|'''Autobot Hot Rod''' (Voyager Class, [[2020]]-[[2021]])}}</ul>
:*''Hasbro ID number'': '''86-04'''
==Notes==
Nothing here is a figure.
"""


def test_level_two_toylines_are_the_headings_on_a_page_with_no_toys_heading():
    found = parser.entries(LEVEL_TWO_PAGE, "Hot Rod (G1)/toys")
    assert [e["heading"] for e in found] == [
        "The Transformers",
        "Vintage G1",
        "Studio Series",
    ]
    assert [e["header"].split(" (")[0] for e in found] == [
        "'''Hot Rod'''",
        "'''Hot Rod'''",
        "'''Autobot Hot Rod'''",
    ]
    vintage = found[1]
    assert parser.matches(vintage, "Vintage_G1") == "heading"
    assert vintage["picture"] == "Walmart-Vintage-G1-Hot-Rod.jpg"
    fields = parser.figure_fields(vintage, "Hot Rod (G1)/toys")
    assert fields["name"] == "Hot Rod" and fields["release_year"] == 2018
    assert (
        fields["toyline"] == "Vintage G1" and fields["accessories"] == "2 photon lasers"
    )
    assert fields["classes"] == ["Walmart exclusive reissue"]


def test_without_a_toys_heading_prose_sections_are_not_figures():
    page = "==Biography==\n===Early life===\nSome prose.\n:''A quote.''\n==Notes==\nMore prose.\n"
    assert parser.entries(page, "Someone") == []


def test_a_link_to_a_level_two_toyline_finds_the_figure(tmp_path):
    cache_pages(tmp_path, {"Hot_Rod_(G1)/toys": LEVEL_TWO_PAGE})
    fetcher = Fetcher(str(tmp_path), get=lambda url: pytest.fail("no network: " + url))
    result = read_figure(fetcher, WIKI + "Hot_Rod_(G1)/toys#Vintage_G1")
    (candidate,) = result["candidates"]
    assert candidate["matched_by"] == "heading"
    assert candidate["link"] == WIKI + "Hot_Rod_(G1)/toys#Vintage_G1"
    assert candidate["fields"]["release_year"] == 2018
