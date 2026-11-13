"""Add from TFWiki: paste, look up, review, save. The pages are the recorded ones in
tests/fixtures/tfwiki, so nothing here touches the network."""

import os
import re

import pytest

from app import app as flask_app, db
from app import addfigure
from app.models import (
    Category,
    Character,
    Continuity,
    Figure,
    Franchise,
    FranchiseAlias,
    Tooling,
)
from app.tfwiki.fetcher import (
    Disabled,
    FetchError,
    PageNotFound,
    RateLimited,
)

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures", "tfwiki")
WIKI = "https://tfwiki.net/wiki/"
ALPHA = WIKI + "Alpha_Trion_(G1)#Legacy"  # moved: the figure is on Alpha_Trion/toys


def lookup(client, url, **extra):
    return client.post("/addfromtfwiki/lookup", data=dict(url=url, **extra)).get_data(
        as_text=True
    )


def page_values(html):
    """The text inputs and the textareas of the review form, as posted."""
    values = {}
    for tag in re.findall(r"<input[^>]*>", html):
        name = re.search(r'name="([^"]+)"', tag)
        value = re.search(r'value="([^"]*)"', tag)
        if name and 'type="checkbox"' not in tag:
            values[name.group(1)] = value.group(1) if value else ""
    for name, body in re.findall(
        r'<textarea[^>]*name="([^"]+)"[^>]*>(.*?)</textarea>', html, re.S
    ):
        values[name] = body.replace("&#34;", '"').replace("&amp;", "&")
    return values


def form(seed, **changes):
    data = {
        "url": ALPHA,
        "pick": "0",
        "name": "Alpha Trion",
        "release_year": "2022",
        "faction": str(seed["faction"].id),
        "character_id": "",
        "character_name": "Alpha Trion",
        "character_link": WIKI + "Alpha_Trion",
        "continuity_id": "",
        "continuity_name": "",
        "link": WIKI + "Alpha_Trion/toys#Legacy",
        "history_text": "Scourge | " + WIKI + "Scourge_(G1)/toys#Studio_Series",
        "packed_with_text": "",
        "quantity": "1",
    }
    data.update(changes)
    return data


def save(client, seed, **changes):
    return client.post(
        "/addfromtfwiki/save", data=form(seed, **changes), follow_redirects=False
    )


# --- the pages ------------------------------------------------------------------


def test_the_paste_page_and_the_menu(auth_client, seed):
    html = auth_client.get("/addfromtfwiki/").get_data(as_text=True)
    assert "Add a figure from TFWiki" in html and 'name="url"' in html
    assert 'name="refresh"' in html and "Add without the wiki" in html
    assert "Add from TFWiki" in auth_client.get("/").get_data(as_text=True)


def test_anonymous_users_are_sent_to_login(client):
    for method, path in (
        ("get", "/addfromtfwiki/"),
        ("post", "/addfromtfwiki/lookup"),
        ("post", "/addfromtfwiki/save"),
    ):
        resp = getattr(client, method)(path)
        assert resp.status_code == 302 and "/login/" in resp.headers["Location"]


@pytest.mark.parametrize(
    "url, message",
    [
        ("", "Paste a tfwiki.net link."),
        ("https://example.com/wiki/X", "Not a tfwiki.net link"),
        ("not a link", "Not a tfwiki.net link"),
        (
            WIKI + "Not_Cached_Page#X",
            "not in the cache and fetching from tfwiki.net is off",
        ),
    ],
)
def test_lookup_problems(auth_client, cached, url, message):
    html = lookup(auth_client, url)
    assert message in html and "Add a figure from TFWiki" in html


def test_a_missing_figure_lists_what_the_page_has(auth_client, cached):
    html = lookup(auth_client, WIKI + "Alpha_Trion/toys#Nonesuch")
    assert "No figure for #Nonesuch" in html
    assert "<li>Legacy</li>" in html and "<li>SDCC2015</li>" in html


@pytest.mark.parametrize(
    "error, message",
    [
        (Disabled("off"), "not in the cache"),
        (RateLimited("429"), "asked us to slow down"),
        (PageNotFound("gone"), "no such page"),
        (FetchError("boom"), "boom"),
    ],
)
def test_fetch_errors_become_messages(auth_client, cached, monkeypatch, error, message):
    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr(addfigure, "read_figure", broken)
    assert message in lookup(auth_client, WIKI + "Anything#X")


def test_the_figure_reader_can_skip_suggestions_and_their_template_fetches():
    from app.tfwiki.figure import read_figure

    block = (
        '{{anchor|Wanted}}\n<ul class="iconlist">'
        "{{Bp-pr9|'''A''' (Deluxe Class, 2000)}}</ul>\n"
    )
    pages = {"Name": ("Name", "==Toys==\n===''The Line''===\n" + block)}

    class Wiki:
        def __init__(self):
            self.asked = []

        def page(self, title, refresh=False):
            self.asked.append(title)
            if title not in pages:
                raise PageNotFound(title)
            return pages[title]

    plain = Wiki()
    result = read_figure(plain, WIKI + "Name#Wanted", fields=False)
    assert result["candidates"][0]["fields"] is None
    assert plain.asked == ["Name"]
    full = Wiki()
    read_figure(full, WIKI + "Name#Wanted")
    assert "Template:Bp-pr9" in full.asked


def test_a_page_that_goes_missing_between_the_steps_is_a_message(auth_client, cached):
    html = lookup(auth_client, WIKI + "Not_Cached_Page#X", pick="0")
    assert "not in the cache" in html and "Add a figure from TFWiki" in html


def test_refresh_needs_fetching_to_be_on(auth_client, cached):
    html = lookup(auth_client, ALPHA, refresh="1")
    assert "fetching from tfwiki.net is off" in html


def test_refreshing_fetcher_ignores_the_cache_once_per_page():
    calls = []

    class Inner:
        def page(self, title, refresh=False):
            calls.append((title, refresh))
            return title, ""

    fetcher = addfigure.Refreshing(Inner())
    fetcher.page("A")
    fetcher.page("A")
    fetcher.page("B")
    assert calls == [("A", True), ("A", False), ("B", True)]


# --- the review ----------------------------------------------------------------


def test_one_candidate_goes_straight_to_the_review(auth_client, cached, seed):
    html = lookup(auth_client, ALPHA)
    assert 'action="/addfromtfwiki/save"' in html
    values = page_values(html)
    assert values["name"] == "A Hero is Born" and values["release_year"] == "2022"
    assert values["link"] == WIKI + "Alpha_Trion/toys#Legacy"
    assert (
        values["character_link"] == WIKI + "Alpha_Trion"
        and values["character_name"] == "Alpha Trion"
    )
    assert (
        "Scourge | " + WIKI + "Scourge_(G1)/toys#Studio_Series"
        in values["history_text"]
    )
    assert (
        "Orion Pax | " + WIKI + "Optimus_Prime_(G1)/Generations_toys#Legacy"
        in values["packed_with_text"]
    )
    assert values["accessories_text"].startswith("Rifle, Vector Sigma")
    assert "the link was updated to that page" in html  # it moved to Alpha_Trion/toys
    assert "from Bp-a1" in html and "guessed from:" in html  # sources are shown
    assert "Legacy-toy_AlphaTrion.jpg" in html  # the raw block and the picture
    assert '<option value="%s" selected>Autobot</option>' % seed["faction"].id in html


def test_suggestions_match_existing_tooling_categories_and_franchises(
    auth_client, cached, seed
):
    retool = Tooling(name="Retool")
    pack = Category(name="2-pack")
    legacy = Franchise(name="Legacy", start_year=2022)
    db.session.add_all([retool, pack, legacy])
    db.session.commit()
    html = lookup(auth_client, ALPHA)
    assert '<option value="%s" selected>Retool</option>' % retool.id in html
    assert '<option value="%s" selected>2-pack</option>' % pack.id in html
    assert '<option value="%s" selected>Legacy</option>' % legacy.id in html
    assert "named like Legacy" in html


def test_a_remembered_name_beats_an_exact_match(auth_client, cached, seed):
    legacy = Franchise(name="Legacy", start_year=2022)
    united = Franchise(name="Legacy United", start_year=2024)
    db.session.add_all([legacy, united])
    db.session.flush()
    db.session.add(FranchiseAlias(alias="Legacy", franchise=united))
    db.session.commit()
    html = lookup(auth_client, ALPHA)
    assert '<option value="%s" selected>Legacy United</option>' % united.id in html
    assert "remembered mapping of Legacy" in html


def test_an_unmatched_toyline_is_said_so(auth_client, cached, seed):
    assert "no franchise matches the toyline" in lookup(auth_client, ALPHA)


def test_several_figures_under_one_link_are_offered_one_by_one(
    auth_client, cached, seed
):
    url = WIKI + "Blackarachnia_(BW)/toys#Beast_Machines"
    html = lookup(auth_client, url)
    assert "has 2 figures under that link" in html and html.count("Use this one") == 2
    chosen = lookup(auth_client, url, pick="1")
    assert 'action="/addfromtfwiki/save"' in chosen
    assert page_values(chosen)["pick"] == "1"
    assert "Pick one of the figures listed." in lookup(auth_client, url, pick="9")


def test_an_existing_character_is_selected_and_not_offered_as_new(
    auth_client, cached, seed
):
    char = Character(name="Alpha Trion", link=WIKI + "Alpha_Trion")
    db.session.add(char)
    db.session.commit()
    html = lookup(auth_client, ALPHA)
    assert '<option value="%s" selected>Alpha Trion</option>' % char.id in html
    assert "already in the collection and is used as it is" in html


def test_a_character_saved_under_the_pasted_pages_link_is_found(
    auth_client, cached, seed
):
    # The wiki's page is now Alpha_Trion; the saved character still has the old link.
    char = Character(name="Alpha Trion", link=WIKI + "Alpha_Trion_(G1)")
    db.session.add(char)
    db.session.commit()
    html = lookup(auth_client, ALPHA)
    assert '<option value="%s" selected>Alpha Trion</option>' % char.id in html
    assert "matched by the link you pasted" in html


def test_a_section_without_a_figure_line_offers_the_characters_name(
    auth_client, tmp_path, monkeypatch, seed
):
    import json

    from app.tfwiki.fetcher import cache_name

    page = (
        "Mover is an [[Autobot]] from the [[Generation 1 continuity family]].\n"
        "==Toys==\n===''The Line''===\n"
        ":''A prose description of the toy.''\n"
    )
    folder = tmp_path / "prose"
    folder.mkdir()
    (folder / cache_name("Mover_(G1)")).write_text(
        json.dumps({"parse": {"title": "Mover (G1)", "wikitext": {"*": page}}})
    )
    monkeypatch.setitem(flask_app.config, "TFWIKI_CACHE_DIR", str(folder))
    monkeypatch.setitem(flask_app.config, "TFWIKI_ENABLED", False)
    html = lookup(auth_client, WIKI + "Mover_(G1)#The_Line")
    values = page_values(html)
    assert values["name"] == "Mover" and values["release_year"] == ""
    assert "A prose description of the toy." in html
    assert '<option value="%s" selected>Autobot</option>' % seed["faction"].id in html


def test_a_known_continuity_is_selected_for_a_new_character(auth_client, cached, seed):
    html = lookup(
        auth_client, WIKI + "Blackarachnia_(BW)/toys#Beast_Machines", pick="0"
    )
    assert "which is not a continuity yet" in html
    db.session.add(Continuity(name="BW"))
    db.session.commit()
    html = lookup(
        auth_client, WIKI + "Blackarachnia_(BW)/toys#Beast_Machines", pick="0"
    )
    assert re.search(r'<option value="\d+" selected>BW</option>', html)


def test_the_character_pages_lead_sentence_is_a_hint(auth_client, cached, seed):
    html = lookup(auth_client, WIKI + "Boater#Zone")
    assert (
        "Boater is an Autobot Micromaster from the Victory era of the Generation 1 continuity family"
        in html
    )


def test_the_lead_sentence_fills_in_a_missing_faction(seed):
    result = {
        "asked": "X",
        "character": {"name": "X", "qualifier": None, "page": "X", "link": WIKI + "X"},
        "candidates": [
            {
                "link": WIKI + "X/toys#Y",
                "fields": {
                    "name": "X",
                    "release_year": 2000,
                    "faction": None,
                    "toyline": None,
                    "anchors": [],
                    "tooling": None,
                    "classes": [],
                    "accessories": "",
                    "ancestors": [],
                    "packed_with": [],
                    "picture": None,
                },
            }
        ],
    }
    lead = {
        "faction": "Autobot",
        "sentence": "X is an Autobot from the G1 continuity family.",
    }
    guess = addfigure.suggest(result, 0, lead)
    assert guess["values"]["faction"] == seed["faction"].id
    assert "from the character page" in guess["notes"]["faction"]
    assert addfigure.suggest(result, 0, None)["values"]["faction"] == ""


# --- saving --------------------------------------------------------------------------


def test_saving_creates_the_figure_and_what_is_new(auth_client, cached, seed):
    resp = save(auth_client, seed, continuity_id="new", continuity_name="G1")
    assert (
        resp.status_code == 302 and "/figuremodelview/show/" in resp.headers["Location"]
    )
    fig = db.session.query(Figure).filter_by(name="Alpha Trion").one()
    assert fig.link == WIKI + "Alpha_Trion/toys#Legacy" and fig.release_year == 2022
    assert (
        fig.character_new.name == "Alpha Trion"
        and fig.character_new.link == WIKI + "Alpha_Trion"
    )
    assert fig.character_new.continuity.name == "G1"
    assert [(r.kind, r.name) for r in fig.references] == [("ancestor", "Scourge")]
    assert db.session.query(Continuity).filter_by(name="G1").count() == 1


def test_saving_again_reuses_the_character_and_continuity_and_changes_nothing_else(
    auth_client, cached, seed
):
    save(auth_client, seed, continuity_id="new", continuity_name="G1")
    fig = db.session.query(Figure).filter_by(name="Alpha Trion").one()
    fig.condition = "edited by hand"
    db.session.commit()
    resp = save(
        auth_client,
        seed,
        name="Second",
        continuity_id="new",
        continuity_name="G1",
        add_copy="1",
    )
    assert resp.status_code == 302
    assert db.session.query(Character).filter_by(link=WIKI + "Alpha_Trion").count() == 1
    assert db.session.query(Continuity).filter_by(name="G1").count() == 1
    db.session.expire_all()
    assert (
        db.session.query(Figure).filter_by(name="Alpha Trion").one().condition
        == "edited by hand"
    )
    assert (
        db.session.query(Figure)
        .filter_by(link=WIKI + "Alpha_Trion/toys#Legacy")
        .count()
        == 2
    )


def test_a_second_copy_needs_a_tick(auth_client, cached, seed):
    save(auth_client, seed)
    html = save(auth_client, seed, name="Again").get_data(as_text=True)
    assert "A figure with this link is already in the collection" in html
    assert "add another copy" in html and 'name="add_copy"' in html
    assert db.session.query(Figure).filter_by(name="Again").count() == 0
    assert "Nothing existing is changed" in html


def test_an_existing_character_can_be_chosen(auth_client, cached, seed):
    char = db.session.get(Character, seed["character"].id)
    resp = save(
        auth_client,
        seed,
        character_id=str(char.id),
        character_name="",
        character_link="",
    )
    assert resp.status_code == 302
    assert (
        db.session.query(Figure).filter_by(name="Alpha Trion").one().character_new.id
        == char.id
    )


def test_the_chosen_franchise_tooling_and_categories_are_saved(
    auth_client, cached, seed
):
    resp = save(
        auth_client,
        seed,
        franchise=[str(seed["franchise"].id)],
        tooling=[str(seed["tooling"].id)],
        categories=[str(seed["category"].id)],
        accessories_text="Rifle, Stand",
        hasbro_id="F1234",
        takara_id="T9",
        exclusive_to="Shop",
        condition="Mint",
        packed_with_text="Mate | " + WIKI + "Mate",
    )
    assert resp.status_code == 302
    fig = db.session.query(Figure).filter_by(name="Alpha Trion").one()
    assert [f.name for f in fig.franchise] == ["Generation 1"]
    assert [t.name for t in fig.tooling] == ["Prime tooling"]
    assert [c.name for c in fig.categories] == ["Leader"]
    assert (
        fig.accessories_text,
        fig.hasbro_id,
        fig.takara_id,
        fig.exclusive_to,
        fig.condition,
    ) == (
        "Rifle, Stand",
        "F1234",
        "T9",
        "Shop",
        "Mint",
    )
    assert sorted((r.kind, r.name) for r in fig.references) == [
        ("ancestor", "Scourge"),
        ("packed_with", "Mate"),
    ]


def test_the_franchise_mapping_is_remembered_when_asked(auth_client, cached, seed):
    save(
        auth_client,
        seed,
        franchise=[str(seed["franchise"].id)],
        remember="1",
        alias="Legacy",
    )
    alias = db.session.query(FranchiseAlias).one()
    assert alias.alias == "Legacy" and alias.franchise.name == "Generation 1"
    # Not twice, and not when two franchises are chosen.
    save(
        auth_client,
        seed,
        name="B",
        add_copy="1",
        franchise=[str(seed["franchise"].id)],
        remember="1",
        alias="Legacy",
    )
    other = Franchise(name="Other", start_year=2000)
    db.session.add(other)
    db.session.commit()
    save(
        auth_client,
        seed,
        name="C",
        add_copy="1",
        franchise=[str(seed["franchise"].id), str(other.id)],
        remember="1",
        alias="Two",
    )
    assert db.session.query(FranchiseAlias).count() == 1
    save(
        auth_client,
        seed,
        name="D",
        add_copy="1",
        franchise=[str(seed["franchise"].id)],
        alias="Unticked",
    )
    assert db.session.query(FranchiseAlias).count() == 1


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"name": ""}, "Give the figure a name"),
        ({"name": "x" * 256}, "Give the figure a name"),
        ({"release_year": ""}, "release year must be a year"),
        ({"release_year": "1500"}, "release year must be a year"),
        ({"faction": ""}, "Choose a faction."),
        ({"faction": "9999"}, "Choose a faction."),
        ({"quantity": "many"}, "quantity must be a whole number"),
        ({"link": "https://example.com/x"}, "Link to Figure: Not a tfwiki.net link"),
        ({"link": WIKI + "A#" + "x" * 500}, "Link to Figure is too long"),
        ({"history_text": "no bar"}, "Model History: Line 1: write it as"),
        (
            {"packed_with_text": "A | ftp://x"},
            "Packed With: Line 1: the link must start with http",
        ),
        ({"character_name": ""}, "A new character needs a name"),
        ({"character_link": "https://example.com/c"}, "A new character needs a name"),
        ({"character_id": "9999"}, "Choose a character."),
        ({"continuity_id": "9999"}, "Choose a continuity."),
    ],
)
def test_a_bad_form_is_shown_again_and_nothing_is_saved(
    auth_client, cached, seed, changes, message
):
    figures, characters = (
        db.session.query(Figure).count(),
        db.session.query(Character).count(),
    )
    html = save(auth_client, seed, **changes).get_data(as_text=True)
    assert message in html and 'class="alert alert-danger"' in html
    assert db.session.query(Figure).count() == figures
    assert db.session.query(Character).count() == characters
    assert db.session.query(Continuity).count() == 1  # only the seed's


def test_a_bad_form_keeps_what_was_typed(auth_client, cached, seed):
    html = save(
        auth_client,
        seed,
        name="Typed name",
        release_year="nope",
        accessories_text="A, B",
    ).get_data(as_text=True)
    values = page_values(html)
    assert values["name"] == "Typed name" and values["release_year"] == "nope"
    assert "A, B" in values["accessories_text"]


def test_the_figure_made_here_opens_on_its_page(auth_client, cached, seed):
    resp = auth_client.post(
        "/addfromtfwiki/save", data=form(seed), follow_redirects=True
    )
    html = resp.get_data(as_text=True)
    assert "Added Alpha Trion." in html and "Scourge" in html


# --- CSRF ------------------------------------------------------------------------


def token(html):
    return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1)


def test_the_forms_carry_a_token_and_a_post_without_one_is_refused(
    auth_client, cached, seed, csrf_on
):
    html = auth_client.get("/addfromtfwiki/").get_data(as_text=True)
    assert 'name="csrf_token"' in html
    for path in ("/addfromtfwiki/lookup", "/addfromtfwiki/save"):
        resp = auth_client.post(path, data=form(seed))
        assert resp.status_code == 400
        assert "This page has expired" in resp.get_data(as_text=True)
    assert db.session.query(Figure).filter_by(name="Alpha Trion").count() == 0


def test_a_post_with_the_token_works(auth_client, cached, seed, csrf_on):
    page = auth_client.get("/addfromtfwiki/").get_data(as_text=True)
    resp = auth_client.post(
        "/addfromtfwiki/lookup", data={"url": ALPHA, "csrf_token": token(page)}
    )
    assert resp.status_code == 200
    review = resp.get_data(as_text=True)
    assert 'action="/addfromtfwiki/save"' in review
    done = auth_client.post(
        "/addfromtfwiki/save", data=form(seed, csrf_token=token(review))
    )
    assert done.status_code == 302
    assert db.session.query(Figure).filter_by(name="Alpha Trion").count() == 1
