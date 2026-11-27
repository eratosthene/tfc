"""The index page's counts, against data whose totals are known."""

from decimal import Decimal

import pytest

from app import db
from app.index import MyIndexView, _by_assoc, _worth
from app.models import (
    Category,
    Character,
    Continuity,
    ContinuityFamily,
    Faction,
    Figure,
    Franchise,
    Tooling,
    figure_franchise,
)


def _add_known_data():
    g1 = Franchise(name="G1", start_year=1984)
    bw = Franchise(name="Beast Wars", start_year=1996)
    unused_franchise = Franchise(name="Unused Franchise", start_year=2020)
    auto, decep = Faction(name="Autobot"), Faction(name="Decepticon")
    unused_faction = Faction(name="Unused Faction")
    t1, t2 = Tooling(name="T1"), Tooling(name="T2")
    leader, scout = Category(name="Leader"), Category(name="Scout")
    char = Character(name="C", link="https://tfwiki.net/wiki/C")
    db.session.add_all([unused_franchise, unused_faction])

    def fig(name, faction, franchises, tooling, cats):
        return Figure(
            name=name,
            release_year=1990,
            character=char,
            faction=faction,
            franchise=franchises,
            tooling=tooling,
            categories=cats,
        )

    db.session.add_all(
        [
            fig("One", auto, [g1], [t1], [leader]),
            fig("Two", auto, [g1, bw], [t1, t2], [leader, scout]),
            fig("Three", decep, [bw], [t2], [scout]),
        ]
    )
    db.session.commit()


@pytest.fixture
def captured(monkeypatch):
    """The values the index view hands to its template."""
    got = {}
    real = MyIndexView.render_template

    def spy(self, template, **kwargs):
        got.update(kwargs)
        return real(self, template, **kwargs)

    monkeypatch.setattr(MyIndexView, "render_template", spy)
    return got


def test_index_counts_match_known_data(auth_client, captured):
    _add_known_data()
    resp = auth_client.get("/")
    assert resp.status_code == 200
    assert captured["num_figures"] == 3
    totals = lambda key, rows: {str(r[key]): r["total"] for r in rows}  # noqa: E731
    assert totals("franchise", captured["by_franchise"]) == {
        "G1": 2,
        "Beast Wars": 2,
    }
    assert totals("faction", captured["by_faction"]) == {
        "Autobot": 2,
        "Decepticon": 1,
        "Unused Faction": 0,
    }
    assert totals("tooling", captured["by_tooling"]) == {"T1": 2, "T2": 2}
    assert totals("category", captured["by_category"]) == {"Leader": 2, "Scout": 2}
    # Franchises are in start-year order, the others by name.
    assert [str(r["franchise"]) for r in captured["by_franchise"]] == [
        "G1",
        "Beast Wars",
    ]
    assert [str(r["faction"]) for r in captured["by_faction"]] == [
        "Autobot",
        "Decepticon",
        "Unused Faction",
    ]
    assert "Total number of figures: 3" in resp.get_data(as_text=True)


def test_index_with_empty_database(auth_client):
    resp = auth_client.get("/")
    assert resp.status_code == 200
    assert "Total number of figures: 0" in resp.get_data(as_text=True)


def test_index_is_public(client, seed):
    # Current behavior: Flask-AppBuilder's index view needs no login, so an
    # anonymous visitor sees the totals (but no figure details).
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Total number of figures: 1" in resp.get_data(as_text=True)


def test_by_assoc_counts_each_figure_once(seed):
    rows = _by_assoc(Franchise, figure_franchise, "franchise", [Franchise.name])
    assert [(str(r["franchise"]), r["total"]) for r in rows] == [("Generation 1", 1)]


def test_a_parent_franchise_counts_the_figures_below_it(auth_client, captured):
    _add_known_data()
    g1 = db.session.query(Franchise).filter_by(name="G1").one()
    bw = db.session.query(Franchise).filter_by(name="Beast Wars").one()
    parent = Franchise(name="Transformers", start_year=1983)
    db.session.add(parent)
    db.session.flush()
    g1.parent = bw.parent = parent
    db.session.commit()
    resp = auth_client.get("/")
    roots = captured["by_franchise"]
    # Only the top level is listed; G1 and Beast Wars sit below Transformers.
    assert [str(r["franchise"]) for r in roots] == ["Transformers"]
    top = roots[0]
    # Two (One, Two) are in G1 and two (Two, Three) in Beast Wars; Two is in both.
    assert top["total"] == 3
    assert [(str(c["franchise"]), c["total"]) for c in top["children"]] == [
        ("G1", 2),
        ("Beast Wars", 2),
    ]
    html = resp.get_data(as_text=True)
    assert (
        'data-id="f%d" data-parent="f%d"'
        % (top["children"][0]["franchise"].id, top["franchise"].id)
        in html
    )


def test_by_continuity_groups_continuities_into_families(auth_client, captured):
    fam = ContinuityFamily(name="Aligned")
    rid = Continuity(name="RID", family=fam)
    foc = Continuity(name="FOC", family=fam)
    solo = Continuity(name="Solo")
    unused = Continuity(name="Unused", family=ContinuityFamily(name="Empty"))
    db.session.add_all([rid, foc, solo, unused])
    db.session.flush()
    chars = [
        Character(name=n, link="https://tfwiki.net/wiki/" + n, continuity=c)
        for n, c in (("A", rid), ("B", foc), ("C", solo))
    ]
    faction = Faction(name="Autobot")
    db.session.add_all(chars + [faction])
    db.session.flush()
    for name, char in (("f1", 0), ("f2", 0), ("f3", 1), ("f4", 2)):
        db.session.add(
            Figure(
                name=name,
                release_year=1990,
                character=chars[char],
                faction=faction,
            )
        )
    db.session.commit()
    resp = auth_client.get("/")
    roots = captured["by_continuity"]
    # Families and family-less continuities share the top level, by name.
    assert [(n.get("family") or n["continuity"]).name for n in roots] == [
        "Aligned",
        "Empty",
        "Solo",
    ]
    aligned = roots[0]
    assert aligned["total"] == 3
    assert [(c["continuity"].name, c["total"]) for c in aligned["children"]] == [
        ("FOC", 1),
        ("RID", 2),
    ]
    assert roots[1]["total"] == 0 and roots[1]["children"] == [
        {"continuity": unused, "total": 0, "children": []}
    ]
    assert roots[2]["total"] == 1
    assert 'data-parent="g%d"' % aligned["family"].id in resp.get_data(as_text=True)


def test_a_franchise_picture_lines_up_with_the_name_not_the_toggle(auth_client):
    _add_known_data()
    db.session.query(Franchise).filter_by(name="G1").one().image = "x.jpg"
    db.session.commit()
    page = auth_client.get("/").get_data(as_text=True)
    assert 'class="img-responsive tree-picture"' in page
    assert ".tree-picture { margin-left: 32px; }" in page
    # 32px is the toggle's width (26px) plus its right margin (6px)
    assert "width: 26px; margin-right: 6px" in page


def test_franchises_with_no_figures_are_not_listed(auth_client, captured):
    _add_known_data()
    g1 = db.session.query(Franchise).filter_by(name="G1").one()
    sold = Franchise(name="All Sold", start_year=1990)
    empty_child = Franchise(name="Empty Child", start_year=1991, parent=g1)
    empty_parent = Franchise(name="Empty Parent", start_year=1992)
    empty_grandchild = Franchise(
        name="Empty Grandchild", start_year=1993, parent=empty_parent
    )
    db.session.add_all([sold, empty_child, empty_parent, empty_grandchild])
    db.session.commit()
    html = auth_client.get("/").get_data(as_text=True)
    roots = captured["by_franchise"]
    assert [str(r["franchise"]) for r in roots] == ["G1", "Beast Wars"]
    assert roots[0]["children"] == []
    for name in ("All Sold", "Empty Child", "Empty Parent", "Empty Grandchild"):
        assert name not in html
    # The franchise list itself still has them.
    assert db.session.query(Franchise).filter_by(name="All Sold").count() == 1


def test_values_count_quantity_and_only_figures_with_an_average(auth_client, captured):
    _add_known_data()
    one, two = (
        db.session.query(Figure).filter_by(name=n).one() for n in ("One", "Two")
    )
    one.af411_average = Decimal("10.00")  # no quantity: one copy
    two.af411_average, two.quantity = Decimal("5.50"), 3
    db.session.commit()
    resp = auth_client.get("/")
    html = " ".join(resp.get_data(as_text=True).split())
    assert captured["worth"] == {"value": Decimal("26.50"), "priced": 2, "of": 3}
    assert "Total value: $26.50 <small" in html and "(2 of 3 priced)" in html
    by_name = {str(r["franchise"]): r["worth"] for r in captured["by_franchise"]}
    # Two is in both franchises, so the rows add up to more than the total.
    assert by_name["G1"] == {"value": Decimal("26.50"), "priced": 2, "of": 2}
    assert by_name["Beast Wars"] == {"value": Decimal("16.50"), "priced": 1, "of": 2}
    assert "$16.50 <small" in html and "(1 of 2 priced)" in html


def test_the_total_with_no_averages_is_a_dash(auth_client, captured):
    _add_known_data()
    html = auth_client.get("/").get_data(as_text=True)
    assert captured["worth"] == {"value": 0, "priced": 0, "of": 3}
    assert "Total value:" in html and "(0 of" not in html


def test_a_box_average_is_counted_once_for_the_figures_in_it(auth_client, captured):
    _add_known_data()
    one, two, three = (
        db.session.query(Figure).filter_by(name=n).one()
        for n in ("One", "Two", "Three")
    )
    box = "https://www.actionfigure411.com/transformers/x/box-1.php"
    # One and Two share a box worth 100; Three is a box of its own worth 7.
    one.af411_link = two.af411_link = box
    one.af411_average = two.af411_average = Decimal("100.00")
    two.quantity = 2
    three.af411_average = Decimal("7.00")
    db.session.commit()
    resp = auth_client.get("/")
    # The box once, for the most copies in it (2), plus Three.
    assert captured["worth"] == {"value": Decimal("207.00"), "priced": 3, "of": 3}
    by_name = {str(r["franchise"]): r["worth"] for r in captured["by_franchise"]}
    assert by_name["G1"] == {"value": Decimal("200.00"), "priced": 2, "of": 2}
    assert by_name["Beast Wars"] == {"value": Decimal("207.00"), "priced": 2, "of": 2}
    assert "$207.00 <small" in " ".join(resp.get_data(as_text=True).split())


def test_a_figure_with_an_average_but_no_link_is_a_box_of_its_own():
    prices = {1: (None, Decimal("10"), 1), 2: (None, Decimal("10"), 1)}
    assert _worth({1, 2}, prices) == {
        "value": Decimal("20"),
        "priced": 2,
        "of": 2,
    }


def test_gestalts_are_not_counted_in_the_totals(auth_client, captured):
    _add_known_data()
    one, two, three = (
        db.session.query(Figure).filter_by(name=n).one()
        for n in ("One", "Two", "Three")
    )
    # Two is a combiner made of One and Three, so it is not a figure of its own.
    two.gestalt_of = [one, three]
    one.af411_average = Decimal("10.00")
    two.af411_average = Decimal("30.00")
    db.session.commit()
    resp = auth_client.get("/")
    html = " ".join(resp.get_data(as_text=True).split())
    assert captured["num_figures"] == 2 and "Total number of figures: 2" in html
    assert captured["worth"] == {"value": Decimal("10.00"), "priced": 1, "of": 2}
    by_name = {str(r["franchise"]): r for r in captured["by_franchise"]}
    assert by_name["G1"]["total"] == 1  # One; Two is a gestalt
    assert by_name["Beast Wars"]["total"] == 1  # Three
    assert by_name["Beast Wars"]["worth"]["of"] == 1


def test_a_franchise_with_only_gestalts_is_not_listed(auth_client, captured):
    _add_known_data()
    one, two, three = (
        db.session.query(Figure).filter_by(name=n).one()
        for n in ("One", "Two", "Three")
    )
    two.gestalt_of = [one]
    three.gestalt_of = [one]  # Beast Wars has only Two and Three
    db.session.commit()
    auth_client.get("/")
    assert [str(r["franchise"]) for r in captured["by_franchise"]] == ["G1"]
