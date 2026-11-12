"""scripts/migrate_data_model.py, on a small database seeded with the awkward cases
of the production data (see docs/proposals/data-model.md, section 5)."""

import importlib.util
import json
import os

import pytest
from sqlalchemy import select

from app import db
from app.models import (
    Accessory,
    Character,
    Continuity,
    ContinuityFamily,
    DataModelMigration,
    Faction,
    Figure,
    FigureReference,
    TFWikiLink,
)

_spec = importlib.util.spec_from_file_location(
    "migrate_data_model",
    os.path.join(os.path.dirname(__file__), "..", "scripts", "migrate_data_model.py"),
)
mdm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mdm)

WIKI = "https://tfwiki.net/wiki/"
COMMA_ACCESSORY = "Devastator components (waist, breastplate, forearms)/Trailer"


def link(name, page):
    row = TFWikiLink(name=name, link=WIKI + page)
    db.session.add(row)
    return row


@pytest.fixture
def old_data():
    """Old structures only: the figures, links and accessories, no new rows."""
    autobot = Faction(name="Autobot")
    db.session.add(autobot)
    bee = link("Bumblebee", "Bumblebee_(G1)")
    rumble = link("Rumble", "Rumble_(G1)/toys#Vintage_G1")  # fragment and suffix
    rumble_plain = link("Rumble", "Rumble_(G1)")  # the same page, a second row
    boater = link("Boater", "Boater")  # no continuity suffix
    wingspan = link("Wingspan", "Wingspan#Titans_Return")
    bee_toy = link("Bumblebee", "Bumblebee_(G1)/toys#Vintage_G1")
    prime = link("Optimus Prime", "Optimus_Prime_(G1)/toys#G1v1")
    metroplex = link("Metroplex", "Metroplex_(G1)")  # an ancestor with no #
    outside = TFWikiLink(name="Elsewhere", link="http://example.com/x")
    db.session.add(outside)
    link("Unused", "Unused_(G1)")  # referenced by nothing
    rifle = Accessory(name="Rifle")
    comma = Accessory(name=COMMA_ACCESSORY)
    star = Accessory(name="Étoile ★")
    db.session.add_all([rifle, comma, star])
    db.session.flush()

    def figure(name, character, **kw):
        fig = Figure(
            name=name, release_year=1984, faction=autobot, character=character, **kw
        )
        db.session.add(fig)
        return fig

    figure(
        "Bumblebee",
        bee,
        figure_link=bee_toy,
        history=[prime, metroplex, outside],
        packed_with=[bee_toy, boater],
        accessories=[rifle, comma, star],
    )
    figure("Rumble", rumble)
    figure("Bōater ♥", boater, accessories=[star])
    figure("Rumble again", rumble_plain)
    figure("Wingspan", wingspan)
    db.session.commit()


def run(argv):
    """Run the command in its own app context, as the real script does.

    That context has its own session, so end this one's snapshot afterwards: on
    MariaDB it would not see what the command committed.
    """
    try:
        return mdm.main(argv)
    finally:
        db.session.remove()


def snapshot():
    return mdm.checksum(db.session)


def figure_named(name):
    return db.session.scalar(select(Figure).where(Figure.name == name))


def test_character_link_strips_the_fragment_and_the_toys_suffix():
    f = mdm.character_link
    assert f(WIKI + "Rumble_(G1)/toys#Vintage_G1") == WIKI + "Rumble_(G1)"
    assert (
        f(WIKI + "Optimus_Prime_(G1)/Generations_toys#X") == WIKI + "Optimus_Prime_(G1)"
    )
    assert f(WIKI + "Wingspan#Titans_Return") == WIKI + "Wingspan"
    assert f(WIKI + "Boater") == WIKI + "Boater"


def test_continuity_name_is_the_page_suffix():
    f = mdm.continuity_name
    assert f(WIKI + "Rumble_(G1)/toys#Vintage_G1") == "G1"
    assert f(WIKI + "Bumblebee_(Cybertron_Mini-Con)") == "Cybertron Mini-Con"
    assert f(WIKI + "Fireflight_(G1") == "G1"  # a link that lost its bracket
    assert f(WIKI + "Boater") is None


def test_accessories_join_and_split_keep_a_name_that_contains_the_separator():
    names = ["Rifle", COMMA_ACCESSORY, "Axe"]
    text = mdm.join_accessories(names)
    assert text.startswith("Rifle, Devastator components (waist, ")
    assert mdm.split_accessories(text, [COMMA_ACCESSORY]) == names
    assert mdm.split_accessories(text) != names  # without the hint it would split
    assert mdm.join_accessories([]) is None
    assert mdm.split_accessories(None) == []
    assert mdm.split_accessories(COMMA_ACCESSORY, [COMMA_ACCESSORY]) == [
        COMMA_ACCESSORY
    ]


def test_dry_run_reports_and_changes_nothing(old_data, capsys):
    before = snapshot()
    assert run(["dry-run"]) == 0
    out = capsys.readouterr().out
    assert "RESULT: ok" in out
    assert "figures: 5" in out
    assert "Boater <" + WIKI + "Boater>" in out  # needs a continuity
    assert "Unused" in out  # unreferenced
    assert "http://example.com/x" in out  # not a tfwiki link
    assert COMMA_ACCESSORY in out
    assert "Rumble_(G1)/toys#Vintage_G1" in out  # the rewritten character link
    assert snapshot() == before
    assert db.session.scalar(select(Character.id)) is None
    assert db.session.scalar(select(DataModelMigration.id)) is None
    assert figure_named("Bumblebee").link is None


def test_apply_fills_the_new_structures(old_data):
    before = snapshot()
    assert run(["apply"]) == 0
    assert snapshot() == before  # the old data is untouched

    chars = {c.link: c for c in db.session.scalars(select(Character))}
    assert sorted(chars) == [
        WIKI + "Boater",
        WIKI + "Bumblebee_(G1)",
        WIKI + "Rumble_(G1)",
        WIKI + "Wingspan",
    ]
    assert chars[WIKI + "Rumble_(G1)"].continuity.name == "G1"
    assert chars[WIKI + "Boater"].continuity is None
    assert chars[WIKI + "Wingspan"].continuity is None
    assert [c.name for c in db.session.scalars(select(Continuity))] == ["G1"]

    bee = figure_named("Bumblebee")
    assert bee.link == WIKI + "Bumblebee_(G1)/toys#Vintage_G1"
    assert bee.character_new.link == WIKI + "Bumblebee_(G1)"
    assert bee.accessories_text == "Rifle, %s, Étoile ★" % COMMA_ACCESSORY
    refs = db.session.execute(
        select(FigureReference.kind, FigureReference.name, FigureReference.link)
        .where(FigureReference.figure_id == bee.id)
        .order_by(FigureReference.kind, FigureReference.position)
    ).all()
    assert refs == [
        ("ancestor", "Optimus Prime", WIKI + "Optimus_Prime_(G1)/toys#G1v1"),
        ("ancestor", "Metroplex", WIKI + "Metroplex_(G1)"),
        ("ancestor", "Elsewhere", "http://example.com/x"),
        ("packed_with", "Bumblebee", WIKI + "Bumblebee_(G1)/toys#Vintage_G1"),
        ("packed_with", "Boater", WIKI + "Boater"),
    ]
    assert figure_named("Rumble").link is None
    assert figure_named("Rumble").accessories_text is None
    assert (
        figure_named("Rumble").character_id_new
        == figure_named("Rumble again").character_id_new
    )
    assert db.session.scalar(select(DataModelMigration.step)) == "apply"


def test_apply_refuses_a_second_run_unless_asked(old_data, capsys):
    assert run(["apply"]) == 0
    figure_named("Bumblebee").link = "edited in the new app"
    db.session.commit()
    assert run(["apply"]) == 1
    assert "pass --again" in capsys.readouterr().out
    assert figure_named("Bumblebee").link == "edited in the new app"
    assert run(["apply", "--again"]) == 0
    assert figure_named("Bumblebee").link == WIKI + "Bumblebee_(G1)/toys#Vintage_G1"
    assert db.session.query(Character).count() == 4  # nothing duplicated


def test_no_continuity_leaves_that_suffix_blank(old_data, capsys):
    assert run(["apply", "--no-continuity", "G1"]) == 0
    assert "skipped_suffixes" in capsys.readouterr().out
    assert db.session.query(Continuity).count() == 0
    assert all(c.continuity_id is None for c in db.session.scalars(select(Character)))


def test_verify_passes_after_apply_and_records_it(old_data, capsys):
    assert run(["verify"]) == 1  # nothing applied yet
    assert "apply has not been run" in capsys.readouterr().out
    run(["apply"])
    assert run(["verify"]) == 0
    steps = sorted(db.session.scalars(select(DataModelMigration.step)))
    assert steps == ["apply", "verify"]


@pytest.mark.parametrize(
    "damage, expected",
    [
        (lambda f: setattr(f, "link", WIKI + "Other"), "figure link"),
        (lambda f: setattr(f, "accessories_text", "Rifle"), "accessories"),
        (lambda f: setattr(f, "character_new", None), "character link"),
    ],
)
def test_verify_fails_loudly_on_a_difference(old_data, capsys, damage, expected):
    run(["apply"])
    capsys.readouterr()
    damage(figure_named("Bumblebee"))
    db.session.commit()
    assert run(["verify"]) == 1
    out = capsys.readouterr().out
    assert expected in out and "Bumblebee" in out and "FAILED" in out
    assert "verify" not in set(db.session.scalars(select(DataModelMigration.step)))


def test_verify_fails_on_changed_references_and_characters(old_data, capsys):
    run(["apply"])
    db.session.execute(
        FigureReference.__table__.delete().where(FigureReference.kind == "packed_with")
    )
    db.session.add(Character(name="Extra", link=WIKI + "Extra"))
    db.session.commit()
    assert run(["verify"]) == 1
    out = capsys.readouterr().out
    assert "packed_with rows: old 2, new 0" in out
    assert "characters:" in out


def test_apply_rolls_back_if_the_old_data_would_change(old_data, monkeypatch, capsys):
    real = mdm.write_plan

    def careless(session, plan):
        real(session, plan)
        session.execute(TFWikiLink.__table__.update().values(name="Changed"))

    monkeypatch.setattr(mdm, "write_plan", careless)
    assert run(["apply"]) == 1
    assert "the old table tf_wiki_link changed" in capsys.readouterr().out
    assert db.session.query(Character).count() == 0
    assert db.session.query(TFWikiLink).filter_by(name="Changed").count() == 0


def test_reverse_restores_the_old_structures_exactly(old_data):
    before = snapshot()
    run(["apply"])
    run(["verify"])
    assert run(["reverse"]) == 0
    assert snapshot() == before
    assert db.session.scalar(select(DataModelMigration.id)) is None


def test_reverse_after_edits_in_the_new_structures(old_data, capsys):
    run(["apply"])
    bee = figure_named("Bumblebee")
    bee.link = WIKI + "Bumblebee_(G1)/toys#G1v2"  # a different figure page
    bee.accessories_text = "Rifle, Étoile ★, Axe, " + COMMA_ACCESSORY
    other = Character(name="Rumble 2", link=WIKI + "Rumble_(Animated)")
    db.session.add(other)
    db.session.flush()
    figure_named("Rumble").character_id_new = other.id
    db.session.add_all(
        [
            FigureReference(
                figure_id=bee.id,
                kind="ancestor",
                position=3,
                name="New",
                link=WIKI + "New",
            ),
        ]
    )
    db.session.commit()
    assert run(["reverse"]) == 0
    bee = figure_named("Bumblebee")
    assert bee.figure_link.link == WIKI + "Bumblebee_(G1)/toys#G1v2"
    assert figure_named("Rumble").character.link == WIKI + "Rumble_(Animated)"
    names = [a.name for a in bee.accessories]
    assert names == ["Rifle", "Étoile ★", "Axe", COMMA_ACCESSORY]
    assert [h.name for h in bee.history][-1] == "New"


def test_reverse_refuses_a_list_the_old_tables_cannot_hold(old_data, capsys):
    run(["apply"])
    bee = figure_named("Bumblebee")
    bee.accessories_text = "Rifle, Rifle"
    db.session.add_all(
        [
            FigureReference(
                figure_id=bee.id,
                kind="ancestor",
                position=p,
                name="New",
                link=WIKI + "New",
            )
            for p in (8, 9)
        ]
    )
    db.session.commit()
    assert run(["reverse"]) == 1
    out = capsys.readouterr().out
    assert "accessory 'Rifle' listed twice" in out
    assert "ancestor 'New' listed twice" in out


def test_reverse_refuses_a_figure_with_no_character_or_a_too_long_accessory(
    old_data, capsys
):
    run(["apply"])
    before = snapshot()
    figure_named("Rumble").character_id_new = None
    db.session.commit()
    assert run(["reverse"]) == 1
    assert "has no character" in capsys.readouterr().out
    assert snapshot() == before  # rolled back
    figure_named("Rumble").character_id_new = figure_named("Wingspan").character_id_new
    figure_named("Wingspan").accessories_text = "x" * 61
    db.session.commit()
    assert run(["reverse"]) == 1
    assert "too long" in capsys.readouterr().out


def test_missing_uploads_are_reported_not_changed(old_data, capsys):
    figure_named("Rumble").image = "gone_sep_rumble.png"
    db.session.commit()
    assert run(["dry-run"]) == 0
    assert (
        "figure %s: gone_sep_rumble.png" % figure_named("Rumble").id
        in capsys.readouterr().out
    )
    assert figure_named("Rumble").image == "gone_sep_rumble.png"


def test_json_report_is_written(old_data, tmp_path):
    path = tmp_path / "report.json"
    assert run(["dry-run", "--json", str(path)]) == 0
    data = json.loads(path.read_text())
    assert data["problems"] == []
    assert data["report"]["figures"] == 5
    assert data["report"]["unreferenced"][0]["name"] == "Unused"


def test_an_empty_database_is_fine(capsys):
    assert run(["dry-run"]) == 0
    assert "figures: 0" in capsys.readouterr().out


@pytest.fixture
def two_continuities(old_data):
    """Adds a character from another continuity, so there are G1 and Animated."""
    animated = link("Bumblebee", "Bumblebee_(Animated)")
    db.session.add(
        Figure(
            name="Animated Bumblebee",
            release_year=2008,
            faction=db.session.scalar(select(Faction)),
            character=animated,
        )
    )
    db.session.commit()


def families():
    return {
        c.name: c.family.name if c.family else None
        for c in db.session.scalars(select(Continuity))
    }


def test_family_groups_the_continuities_it_lists(two_continuities, capsys):
    assert run(["dry-run", "--family", "Generation 1=G1"]) == 0
    out = capsys.readouterr().out
    assert "Generation 1" in out and "continuities_without_family" in out
    assert db.session.query(ContinuityFamily).count() == 0  # dry-run saved nothing
    assert (
        run(["apply", "--family", "Generation 1=G1", "--family", "Aligned=Animated"])
        == 0
    )
    assert families() == {"G1": "Generation 1", "Animated": "Aligned"}
    assert db.session.query(ContinuityFamily).count() == 2


def test_a_continuity_left_out_of_every_family_has_none(two_continuities):
    assert run(["apply", "--family", "Generation 1=G1"]) == 0
    assert families() == {"G1": "Generation 1", "Animated": None}


def test_apply_again_keeps_a_family_set_by_hand(two_continuities):
    run(["apply", "--family", "Generation 1=G1"])
    other = ContinuityFamily(name="Mine")
    db.session.add(other)
    db.session.flush()
    db.session.scalar(
        select(Continuity).where(Continuity.name == "G1")
    ).family_id = other.id
    db.session.commit()
    assert run(["apply", "--again", "--family", "Generation 1=G1,Animated"]) == 0
    assert families() == {
        "G1": "Mine",
        "Animated": "Generation 1",
    }  # only the empty one is filled
    assert (
        db.session.query(ContinuityFamily).filter_by(name="Generation 1").count() == 1
    )


@pytest.mark.parametrize(
    "args, message",
    [
        (["--family", "Aligned=Nowhere"], "which no character's page has"),
        (
            ["--family", "G1 stuff=G1", "--no-continuity", "G1"],
            "--no-continuity leaves out",
        ),
        (["--family", "A=G1", "--family", "B=G1"], "'G1' is in both 'A' and 'B'"),
    ],
)
def test_a_family_listing_that_cannot_be_applied_is_a_problem(
    two_continuities, capsys, args, message
):
    assert run(["apply"] + args) == 1
    assert message in capsys.readouterr().out
    assert db.session.query(ContinuityFamily).count() == 0
    assert db.session.query(Character).count() == 0  # rolled back


@pytest.mark.parametrize("spec", ["Aligned", "=G1", "Aligned=", "Aligned= , "])
def test_a_badly_formed_family_is_refused(old_data, spec, capsys):
    with pytest.raises(SystemExit) as stop:
        run(["dry-run", "--family", spec])
    assert stop.value.code == 2
    assert "NAME=SUFFIX" in capsys.readouterr().err
