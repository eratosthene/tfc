"""Nested franchises: the tree helpers, the parent field, the descendant-aware
Figure filter and flask prune-franchises."""

import pytest
from click.testing import CliRunner
from sqlalchemy import select

from app import app as flask_app, db
from app.franchises import (
    MAX_DEPTH,
    ancestor_ids,
    check_parent,
    descendant_ids,
    descendant_levels,
    effective_franchises,
    parent_map,
    prune_franchises,
)
from app.models import Faction, Figure, Franchise, TFWikiLink


def franchise(name, parent=None):
    row = Franchise(name=name, start_year=2000, parent=parent)
    db.session.add(row)
    db.session.flush()
    return row


@pytest.fixture
def tree():
    """Transformers > Generations > Legacy > Legacy United; Transformers > Prime."""
    root = franchise("Transformers")
    generations = franchise("Generations", root)
    legacy = franchise("Legacy", generations)
    united = franchise("Legacy United", legacy)
    prime = franchise("Prime", root)
    db.session.commit()
    return dict(
        root=root, generations=generations, legacy=legacy, united=united, prime=prime
    )


def figure(name, *franchises):
    db.session.add(
        Figure(
            name=name,
            release_year=2022,
            faction=db.session.scalar(select(Faction)) or Faction(name="Autobot"),
            character=TFWikiLink(name=name, link="https://tfwiki.net/wiki/" + name),
            franchise=list(franchises),
        )
    )
    db.session.commit()
    return db.session.scalar(select(Figure).where(Figure.name == name))


def test_ancestors_and_descendants(tree):
    t = tree
    assert ancestor_ids(t["united"].id) == [
        t["legacy"].id,
        t["generations"].id,
        t["root"].id,
    ]
    assert ancestor_ids(t["root"].id) == []
    assert descendant_levels(t["generations"].id) == [
        [t["legacy"].id],
        [t["united"].id],
    ]
    assert descendant_ids(t["root"].id)[0] == t["root"].id
    assert set(descendant_ids(t["root"].id)) == {f.id for f in tree.values()}
    assert descendant_ids(t["united"].id) == [t["united"].id]


def test_a_loop_in_the_data_does_not_hang(tree):
    tree["root"].parent_id = tree["united"].id  # as if edited behind our back
    db.session.commit()
    parents = parent_map()
    assert tree["root"].id not in ancestor_ids(tree["root"].id, parents)
    assert len(descendant_ids(tree["root"].id, parents)) == 5


def test_check_parent_accepts_a_valid_move(tree):
    check_parent(tree["prime"], tree["united"])
    check_parent(tree["prime"], None)
    check_parent(Franchise(name="New"), tree["root"])


@pytest.mark.parametrize(
    "who, under", [("root", "united"), ("legacy", "legacy"), ("generations", "united")]
)
def test_check_parent_refuses_a_loop(tree, who, under):
    with pytest.raises(ValueError, match="its own ancestor"):
        check_parent(tree[who], tree[under])


def test_check_parent_refuses_a_tree_that_is_too_deep(tree):
    chain = tree["united"]
    for n in range(MAX_DEPTH - 4):  # the tree is already 4 deep
        chain = franchise("Level %d" % n, chain)
    check_parent(Franchise(name="Last fits"), chain.parent)
    with pytest.raises(ValueError, match="levels deep"):
        check_parent(Franchise(name="One too many"), chain)
    # moving a branch counts the branch's own depth too
    other = franchise("Other root")
    for n in range(5):
        other = franchise("Other %d" % n, other)
    with pytest.raises(ValueError, match="levels deep"):
        check_parent(tree["generations"], other)


def test_effective_franchises_adds_the_ancestors(tree):
    fig = figure("Optimus", tree["united"], tree["prime"])
    names = [f.name for f in effective_franchises(fig)]
    assert names == ["Legacy United", "Prime", "Legacy", "Generations", "Transformers"]
    assert [f.name for f in effective_franchises(figure("Bare"))] == []


def test_the_figure_page_lists_the_franchises_above(auth_client, tree):
    fig = figure("Optimus", tree["united"])
    html = auth_client.get("/figuremodelview/show/%s" % fig.id).get_data(as_text=True)
    assert "Legacy United" in html and "Generations" in html and "Transformers" in html


def test_filtering_by_a_franchise_includes_the_ones_below(auth_client, tree):
    rows = {
        figure("Legacy figure", tree["united"]).id: "Legacy figure",
        figure("Prime figure", tree["prime"]).id: "Prime figure",
        figure("Untagged").id: "Untagged",
    }

    def names(franchise_id):
        # The page also lists every figure in its search form, so look for the
        # row links.
        html = auth_client.get(
            "/figuremodelview/list/?_flt_0_franchise=%s" % franchise_id
        ).get_data(as_text=True)
        return {n for i, n in rows.items() if "/figuremodelview/show/%s" % i in html}

    assert names(tree["generations"].id) == {"Legacy figure"}
    assert names(tree["root"].id) == {"Legacy figure", "Prime figure"}
    assert names(tree["united"].id) == {"Legacy figure"}
    assert names(tree["prime"].id) == {"Prime figure"}
    assert names("not-a-number") == set()


def test_the_franchise_list_search_link_uses_the_same_filter(auth_client, tree):
    figure("Legacy figure", tree["united"])
    html = auth_client.get("/franchisemodelview/list/").get_data(as_text=True)
    assert "_flt_0_franchise=%s" % tree["root"].id in html


def edit(auth_client, row, **data):
    data.setdefault("name", row.name)
    data.setdefault("start_year", "2000")
    return auth_client.post(
        "/franchisemodelview/edit/%s" % row.id, data=data, follow_redirects=True
    ).get_data(as_text=True)


def test_set_a_parent_in_the_franchise_form(auth_client, tree):
    html = edit(auth_client, tree["prime"], parent=str(tree["generations"].id))
    assert "Changed Record" in html or "Prime" in html
    assert db.session.get(Franchise, tree["prime"].id).parent.name == "Generations"
    edit(auth_client, tree["prime"], parent="")
    assert db.session.get(Franchise, tree["prime"].id).parent is None


def test_the_form_refuses_a_loop(auth_client, tree):
    html = edit(auth_client, tree["root"], parent=str(tree["united"].id))
    assert "its own ancestor" in html
    assert db.session.get(Franchise, tree["root"].id).parent is None


def test_adding_under_a_parent_and_the_depth_limit(auth_client, tree):
    resp = auth_client.post(
        "/franchisemodelview/add",
        data={"name": "Kids", "start_year": "2020", "parent": str(tree["prime"].id)},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert (
        db.session.scalar(select(Franchise).where(Franchise.name == "Kids")).parent.name
        == "Prime"
    )
    deep = tree["united"]
    for n in range(MAX_DEPTH - 4):
        deep = franchise("Level %d" % n, deep)
    db.session.commit()
    html = auth_client.post(
        "/franchisemodelview/add",
        data={"name": "Too deep", "start_year": "2020", "parent": str(deep.id)},
        follow_redirects=True,
    ).get_data(as_text=True)
    assert "levels deep" in html
    assert (
        db.session.scalar(select(Franchise).where(Franchise.name == "Too deep")) is None
    )


def test_deleting_a_franchise_with_children_is_refused(auth_client, tree):
    html = auth_client.post(
        "/franchisemodelview/delete/%s" % tree["generations"].id, follow_redirects=True
    ).get_data(as_text=True)
    assert "still has sub-franchises" in html
    assert db.session.get(Franchise, tree["generations"].id) is not None
    auth_client.post(
        "/franchisemodelview/delete/%s" % tree["prime"].id, follow_redirects=True
    )
    assert db.session.get(Franchise, tree["prime"].id) is None


def run(*args):
    return CliRunner().invoke(prune_franchises, list(args))


def test_prune_lists_and_changes_nothing_by_default(tree):
    both = figure("Both", tree["generations"], tree["united"], tree["prime"])
    figure("Fine", tree["united"], tree["prime"])
    result = run()
    assert result.exit_code == 0
    assert (
        "Both (figure %s): drop Generations, already covered by Legacy United" % both.id
        in result.output
    )
    assert "1 tags would be removed. Run again with --apply." in result.output
    assert [f.name for f in db.session.get(Figure, both.id).franchise][:1] == [
        "Generations"
    ]


def test_prune_apply_removes_the_covered_tags_and_keeps_order(tree):
    both = figure(
        "Both", tree["root"], tree["generations"], tree["united"], tree["prime"]
    )
    result = run("--apply")
    assert "Removed 2 tags." in result.output  # root and generations
    db.session.expire_all()
    assert [f.name for f in db.session.get(Figure, both.id).franchise] == [
        "Legacy United",
        "Prime",
    ]
    assert "Nothing to prune." in run("--apply").output


def test_prune_with_nothing_to_do(tree):
    assert "Nothing to prune." in run().output
    assert flask_app.cli.get_command(None, "prune-franchises") is not None
