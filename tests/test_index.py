"""The index page's counts, against data whose totals are known."""

import pytest

from app import db
from app.index import MyIndexView, _by_assoc
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
            character_new=char,
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
        "Unused Franchise": 0,
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
        "Unused Franchise",
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
    assert [str(r["franchise"]) for r in roots] == ["Transformers", "Unused Franchise"]
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
                character_new=chars[char],
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
