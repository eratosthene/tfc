"""Each list view opens in its default order, and clicking a column header
still re-sorts it. Rows are inserted out of order on purpose."""

import re

import pytest

from app import db
from app.models import (
    Accessory,
    Category,
    Faction,
    Figure,
    Franchise,
    TFWikiLink,
    Tooling,
)

VIEWS = {
    "figuremodelview": "Fig",
    "franchisemodelview": "Fra",
    "factionmodelview": "Fac",
    "toolingmodelview": "Too",
    "accessorymodelview": "Acc",
    "categorymodelview": "Cat",
    "tfwikilinkmodelview": "Wik",
}


def _names(prefix, letters="BCA"):
    # Inserted B, C, A so neither id order nor reverse id order is sorted.
    return ["%s %s" % (prefix, c) for c in letters]


def _insert_out_of_order():
    # Franchise start years are out of order too, and their names run the
    # opposite way, so sorting by name would give the wrong answer.
    for name, year in zip(_names("Fra", "ABC"), (1990, 2010, 1984)):
        db.session.add(Franchise(name=name, start_year=year))
    for model, prefix in (
        (Faction, "Fac"),
        (Tooling, "Too"),
        (Accessory, "Acc"),
        (Category, "Cat"),
    ):
        db.session.add_all(model(name=n) for n in _names(prefix))
    links = [TFWikiLink(name=n, link="https://x.test/" + n) for n in _names("Wik")]
    db.session.add_all(links)
    faction = Faction(name="Zeta faction")
    franchise = Franchise(name="Zeta franchise", start_year=3000)
    db.session.add_all([faction, franchise])
    for n in _names("Fig"):
        db.session.add(
            Figure(
                name=n,
                release_year=1984,
                character=links[0],
                faction=faction,
                franchise=[franchise],
            )
        )
    db.session.commit()


def _order(client, view, query=""):
    """Plain-text name cells with this view's prefix, in page order."""
    html = client.get("/%s/list/%s" % (view, query)).get_data(as_text=True)
    prefix = VIEWS[view]
    # Table cells only: the page also embeds the names in filter drop-downs.
    cells = re.findall(r"<td>\s*(%s \w)\s*</td>" % prefix, html)
    return list(dict.fromkeys(cells))


@pytest.fixture
def unsorted(auth_client):
    _insert_out_of_order()
    return auth_client


@pytest.mark.parametrize(
    "view,expected",
    [
        ("figuremodelview", ["Fig A", "Fig B", "Fig C"]),
        ("franchisemodelview", ["Fra C", "Fra A", "Fra B"]),  # 1984, 1990, 2010
        ("factionmodelview", ["Fac A", "Fac B", "Fac C"]),
        ("toolingmodelview", ["Too A", "Too B", "Too C"]),
        ("accessorymodelview", ["Acc A", "Acc B", "Acc C"]),
        ("categorymodelview", ["Cat A", "Cat B", "Cat C"]),
        ("tfwikilinkmodelview", ["Wik A", "Wik B", "Wik C"]),
    ],
)
def test_default_order(unsorted, view, expected):
    assert _order(unsorted, view) == expected


def test_clicking_a_column_still_sorts(unsorted):
    # FAB's own sort parameters: order_column_<view id>, order_direction_<id>.
    q = "?_oc_FactionModelView=name&_od_FactionModelView=desc"
    assert _order(unsorted, "factionmodelview", q) == ["Fac C", "Fac B", "Fac A"]
    q = "?_oc_FranchiseModelView=start_year&_od_FranchiseModelView=desc"
    assert _order(unsorted, "franchisemodelview", q) == ["Fra B", "Fra A", "Fra C"]
