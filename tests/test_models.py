"""Model helpers: the TFWikiLink name parsing and the HTML the views show."""

import pytest
from flask_appbuilder.filemanager import thumbgen_filename

from app import app as flask_app, db
from app.models import (
    Accessory,
    Category,
    Character,
    Continuity,
    ContinuityFamily,
    Faction,
    Figure,
    FigureReference,
    Franchise,
    TFWikiLink,
    Tooling,
)

WIKI = "https://tfwiki.net/wiki/"

# (link, __str__, link_type) for each branch of the parsing. The qualifier keeps
# its closing parenthesis, because only "_(" is split on.
LINKS = [
    # No fragment: a character, with or without a "_(" qualifier.
    (WIKI + "Optimus_Prime", "N [character]", "Character"),
    (WIKI + "Optimus_Prime_(G1)", "N (G1) [character]", "Character (G1)"),
    (WIKI + "Prime_(Movie)_(Leader)", "N (Leader) [character]", "Character (Leader)"),
    # Fragment: a figure, plain or with a qualified page name.
    (WIKI + "Prime#Gen_1_Toy", "N @ Gen 1 Toy [figure]", "Figure (Gen 1 Toy)"),
    (WIKI + "Prime_(G1)#Gen_1", "N (G1) @ Gen 1 [figure]", "Figure (Gen 1)"),
    # A "toys" or "Generations_toys" last segment: the page before it is used.
    (WIKI + "Prime/toys#Gen_1", "N @ Gen 1 [figure]", "Figure (Gen 1)"),
    (WIKI + "Prime_(G1)/toys#Gen_1", "N (G1) @ Gen 1 [figure]", "Figure (Gen 1)"),
    (
        WIKI + "Prime/Generations_toys#Legends",
        "N @ Legends [figure]",
        "Figure (Legends)",
    ),
    (
        WIKI + "Prime_(G1)/Generations_toys#Legends",
        "N (G1) @ Legends [figure]",
        "Figure (Legends)",
    ),
]


@pytest.mark.parametrize("link,text,kind", LINKS)
def test_tfwikilink_str_and_type(link, text, kind):
    obj = TFWikiLink(name="N", link=link)
    assert str(obj) == text
    assert repr(obj) == text
    assert obj.link_type() == kind


@pytest.mark.parametrize(
    "link,search",
    [
        (WIKI + "Optimus_Prime", "_flt_0_character=7"),
        (WIKI + "Optimus_Prime_(G1)", "_flt_0_character=7"),
        (WIKI + "Prime#Toy", "_flt_0_figure_link=7"),
    ],
)
def test_tfwikilink_figure_list(link, search):
    obj = TFWikiLink(id=7, name="N", link=link)
    with flask_app.test_request_context():
        html = obj.figure_list()
    assert search in html
    assert "Search for this" in html


@pytest.mark.parametrize(
    "link,expected",
    [(WIKI + "Prime#Toy", True), (WIKI + "Prime", False)],
)
def test_tfwikilink_history_list(link, expected):
    obj = TFWikiLink(id=7, name="N", link=link)
    with flask_app.test_request_context():
        html = obj.history_list()
    if expected:
        assert "_flt_0_history=7" in html and "Ancestor" in html
    else:
        assert html == ""


@pytest.mark.parametrize(
    "cls,param",
    [
        (Franchise, "_flt_0_franchise"),
        (Faction, "_flt_0_faction"),
        (Tooling, "_flt_0_tooling"),
        (Accessory, "_flt_0_accessories"),
        (Category, "_flt_0_categories"),
    ],
)
def test_figure_list_links_to_figure_search(cls, param):
    obj = cls(id=3, name="X")
    with flask_app.test_request_context():
        html = obj.figure_list()
    assert "/figuremodelview/list/" in html
    assert "%s=3" % param in html
    assert "Search Figures" in html


@pytest.mark.parametrize("cls", [Franchise, Faction, Tooling, Accessory, Category])
def test_named_str_repr(cls):
    obj = cls(name="Thing")
    assert str(obj) == "Thing" and repr(obj) == "Thing"


@pytest.mark.parametrize(
    "cls,show_view,img_view",
    [
        (Franchise, "FranchiseModelView.show", "FranchiseModelView"),
        (Faction, "FactionModelView.show", "FactionModelView"),
    ],
)
def test_image_helpers_with_and_without_image(cls, show_view, img_view):
    empty = cls(id=4, name="X", **({"start_year": 1} if cls is Franchise else {}))
    pic = cls(
        id=4, image="a.png", name="X", **({"start_year": 1} if cls is Franchise else {})
    )
    with flask_app.test_request_context():
        assert empty.image_show() == "" and empty.image_thumb_show() == ""
        full, thumb = pic.image_show(), pic.image_thumb_show()
    assert "/%s_img/4" % cls.__name__.lower() in full
    assert "/%s_img_thumb/4" % cls.__name__.lower() in thumb
    assert "/%smodelview/show/4" % cls.__name__.lower() in full
    assert "/%smodelview/show/4" % cls.__name__.lower() in thumb


def test_franchise_link_show():
    assert Franchise(name="x", start_year=1).link_show() == ""
    html = Franchise(
        name="x", start_year=1, link="https://e.com/?a=1&b=<2>"
    ).link_show()
    assert 'href="https://e.com/?a=1&amp;b=&lt;2&gt;"' in html  # escaped


def test_figure_image_helpers():
    empty = Figure(id=9, name="F")
    pic = Figure(id=9, name="F", image="a.png")
    with flask_app.test_request_context():
        assert empty.image_show() == "" and empty.image_thumb_show() == ""
        full, thumb = pic.image_show(), pic.image_thumb_show()
    assert 'target="_blank"' in full and "/figure_img/9" in full
    assert "/figure_img_thumb/9" in thumb and "/figure_img/9" in thumb


def test_faction_show():
    with flask_app.test_request_context():
        assert Figure(name="F").faction_show() == ""
        plain = Figure(name="F", faction=Faction(id=2, name="A<b>")).faction_show()
        pic = Figure(
            name="F", faction=Faction(id=2, name="Auto", image="a.png")
        ).faction_show()
    assert "<p>A&lt;b&gt;</p>" in plain and "<img" not in plain
    assert (
        "<p>Auto</p>" in pic and "/faction_img_thumb/2" in pic and 'alt="Auto"' in pic
    )


def test_character_and_figure_link_show():
    fig = Figure(name="F")
    assert fig.character_show() == "" and fig.figure_link_show() == ""
    char = Character(name="Prime", link=WIKI + "Prime_(G1)")
    fig.character_new = char
    assert fig.character_show() == '<a href="%sPrime_(G1)">Prime</a>' % WIKI
    char.continuity = Continuity(name="G1")
    assert fig.character_show() == '<a href="%sPrime_(G1)">Prime (G1)</a>' % WIKI
    fig.link = WIKI + "Prime_(G1)/toys#Toy"
    assert fig.figure_link_show() == (
        '<a href="{0}Prime_(G1)/toys#Toy">{0}Prime_(G1)/toys#Toy</a>'.format(WIKI)
    )


def test_link_show_of_continuities_and_families():
    for obj in (Continuity(name="C"), ContinuityFamily(name="F")):
        assert obj.link_show() == ""
        obj.link = "https://e.com/?a=1&b=<2>"
        assert 'href="https://e.com/?a=1&amp;b=&lt;2&gt;"' in obj.link_show()


def test_link_list_show():
    a = Franchise(id=1, name="G1", start_year=1, image="a.png")
    b = Franchise(id=2, name="<G2>", start_year=2)
    fig = Figure(name="F", franchise=[a, b])
    with flask_app.test_request_context():
        html = fig.franchise_show()
        empty = Figure(name="F").franchise_show()
    assert "/franchise_img/1" in html and "/franchise_img/2" not in html
    assert "&lt;G2&gt;" in html
    assert html.index("G1") < html.index("&lt;G2")
    assert "<tr>" not in empty and "<tbody></tbody>" in empty


def test_history_and_packed_with_show():
    fig = Figure(
        name="F",
        references=[
            FigureReference(kind="ancestor", name="Old <1>", link=WIKI + "Old#A"),
            FigureReference(kind="packed_with", name="Mate", link=WIKI + "Mate"),
        ],
    )
    with flask_app.test_request_context():
        history, packed = fig.history_show(), fig.packed_with_show()
        empty = Figure(name="F").history_show()
    assert 'href="%sOld#A">Old &lt;1&gt;</a>' % WIKI in history
    assert "Mate" not in history and "Old" not in packed
    assert "_flt_0_ancestors=" in history and "Other figures" in history
    assert 'href="%sMate">Mate</a>' % WIKI in packed
    assert "Other figures" not in packed and "In collection" not in packed
    assert "<tr>" not in empty


def test_thumbgen_name_matches_views():
    # send_image relies on this naming to find a thumbnail on disk.
    assert thumbgen_filename("a_sep_b.png") == "a_sep_b_thumb.png"


def test_a_continuity_belongs_to_at_most_one_family():
    from app.models import Character, Continuity, ContinuityFamily

    aligned = ContinuityFamily(name="Aligned", link="https://tfwiki.net/wiki/Aligned")
    foc = Continuity(name="FOC", family=aligned)
    alone = Continuity(name="Boater era")
    db.session.add_all(
        [foc, alone, Character(name="Blaster", link="b", continuity=foc)]
    )
    db.session.commit()
    assert foc.family.name == "Aligned" and str(foc.family) == "Aligned"
    assert alone.family is None
