"""Price-check links, and finding characters with several figures."""

from urllib.parse import parse_qs, urlparse

from app import db
from app.models import Character, Figure
from app.pricecheck import price_check_links


def _figure(seed, **kw):
    fig = db.session.get(Figure, seed["figure"].id)
    other = Figure(
        name=kw.pop("name", "Second"),
        release_year=2000,
        character=kw.pop("character", fig.character),
        faction=fig.faction,
        **kw,
    )
    db.session.add(other)
    db.session.commit()
    return other


def test_links_search_each_site_for_the_figure(seed):
    fig = db.session.get(Figure, seed["figure"].id)
    links = dict(price_check_links(fig))
    ebay = urlparse(links["eBay sold listings"])
    assert ebay.netloc == "www.ebay.com"
    q = parse_qs(ebay.query)
    # The franchise leads the name, and only sold, completed listings are asked for.
    assert q["_nkw"] == ["transformers Generation 1 Optimus Prime"]
    assert q["LH_Sold"] == ["1"] and q["LH_Complete"] == ["1"]
    assert parse_qs(urlparse(links["Transformerland"]).query)["search"] == [
        "Optimus Prime"
    ]
    assert parse_qs(urlparse(links["ActionFigure411 (eBay averages)"]).query)[
        "term"
    ] == ["Optimus Prime"]


def test_franchise_is_not_repeated_when_the_name_has_it(seed):
    fig = db.session.get(Figure, seed["figure"].id)
    fig.name = "Generation 1 Optimus Prime & Co"
    ebay = dict(price_check_links(fig))["eBay sold listings"]
    assert parse_qs(urlparse(ebay).query)["_nkw"] == [
        "transformers Generation 1 Optimus Prime & Co"
    ]


def test_figure_without_a_franchise_still_gets_links(seed):
    other = _figure(seed, name="Plain")
    assert len(price_check_links(other)) == 3


def test_figure_page_shows_the_links(auth_client, seed):
    html = auth_client.get("/figuremodelview/show/%s" % seed["figure"].id).get_data(
        as_text=True
    )
    assert "LH_Sold=1" in html and "transformerland.com/store/search.php" in html
    assert "actionfigure411.com/common/search-results.php" in html


def test_character_figure_count_adds_quantities(seed):
    _figure(seed, quantity=3)
    _figure(seed, name="No quantity", quantity=None)
    char = db.session.get(Character, seed["character"].id)
    # The seeded figure's default of 1, plus 3, plus one for the empty quantity.
    assert char.figure_count == 5


def test_characters_with_several_figures_can_be_listed(auth_client, seed):
    from app.models import Continuity

    lone = Character(
        name="Lone Wolf",
        link="https://tfwiki.net/wiki/Lone_Wolf",
        continuity=db.session.get(Continuity, seed["continuity"].id),
    )
    db.session.add(lone)
    db.session.commit()
    _figure(seed, character=lone, name="Only one")
    _figure(seed, name="Second Prime")
    # Its own page, on the Characters menu, shows only characters with 2 or more.
    html = auth_client.get("/characters-with-several-figures/list/").get_data(
        as_text=True
    )
    assert "Optimus Prime" in html
    assert "Lone Wolf" not in html
    everything = auth_client.get("/charactermodelview/list/").get_data(as_text=True)
    assert "Lone Wolf" in everything


def test_a_saved_actionfigure411_page_replaces_the_search(auth_client, seed):
    page = "https://www.actionfigure411.com/transformers/studio-series/leader-class/x-9419.php"
    fig = db.session.get(Figure, seed["figure"].id)
    fig.af411_link = page
    db.session.commit()
    links = dict(price_check_links(db.session.get(Figure, seed["figure"].id)))
    assert links["ActionFigure411 (eBay averages)"] == page
    html = auth_client.get("/figuremodelview/show/%s" % seed["figure"].id).get_data(
        as_text=True
    )
    assert page in html and "search-results.php" not in html


def test_the_actionfigure411_link_is_saved_from_the_form_and_checked(auth_client, seed):
    fig = db.session.get(Figure, seed["figure"].id)
    data = {
        "name": fig.name,
        "character": str(fig.character_id),
        "faction": str(fig.faction_id),
        "franchise": [str(f.id) for f in fig.franchise],
        "release_year": str(fig.release_year),
    }
    good = "https://www.actionfigure411.com/transformers/x-1.php"
    url = "/figuremodelview/edit/%s" % seed["figure"].id
    auth_client.post(url, data=dict(data, af411_link=" " + good + " "))
    db.session.expire_all()
    assert db.session.get(Figure, seed["figure"].id).af411_link == good
    # Another site is refused and the saved link stays.
    auth_client.post(url, data=dict(data, af411_link="https://example.com/x"))
    db.session.expire_all()
    assert db.session.get(Figure, seed["figure"].id).af411_link == good
    # An empty box clears it.
    auth_client.post(url, data=dict(data, af411_link=""))
    db.session.expire_all()
    assert db.session.get(Figure, seed["figure"].id).af411_link is None


def test_a_figure_with_no_name_has_no_links():
    assert price_check_links(Figure(name="  ")) == []
