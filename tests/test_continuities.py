"""Continuity full names, and flask set-continuity-names."""

import pytest
from click.testing import CliRunner

from app import db
from app.continuities import parse_names, set_continuity_names
from app.models import Continuity


def run(text, *args):
    result = CliRunner().invoke(set_continuity_names, ["-", *args], input=text)
    db.session.expire_all()
    return result


def full_names():
    return {c.name: c.full_name for c in db.session.query(Continuity)}


@pytest.fixture
def continuities():
    db.session.add_all(
        [Continuity(name="G1"), Continuity(name="BW"), Continuity(name="RID")]
    )
    db.session.commit()


def test_parse_names_skips_comments_and_blank_lines():
    entries, problems = parse_names("# c\n\nG1 = Generation 1  # trailing\nRID=A = B\n")
    assert problems == []
    assert entries == [(3, "G1", "Generation 1"), (4, "RID", "A = B")]


@pytest.mark.parametrize("line", ["G1", "G1 =", "= Generation 1", "G1 = " + "x" * 256])
def test_parse_names_reports_a_bad_line(line):
    entries, problems = parse_names("ok = fine\n" + line + "\n")
    assert [e[1] for e in entries] == ["ok"]
    assert problems and problems[0].startswith("line 2")


def test_the_command_lists_and_saves_nothing_by_default(continuities):
    result = run("G1 = Generation 1\nBW = Beast Wars\n")
    assert result.exit_code == 0
    assert "G1: Generation 1" in result.output
    assert "2 continuities would change. Run again with --apply." in result.output
    assert full_names() == {"G1": None, "BW": None, "RID": None}


def test_apply_saves_and_a_second_run_has_nothing_to_do(continuities):
    text = "G1 = Generation 1\nBW = Beast Wars\n"
    assert "Changed 2 continuities." in run(text, "--apply").output
    assert full_names() == {"G1": "Generation 1", "BW": "Beast Wars", "RID": None}
    assert "Nothing to change." in run(text, "--apply").output


def test_a_name_that_is_already_set_is_kept_unless_overwrite(continuities):
    run("G1 = My own name\n", "--apply")
    result = run("G1 = Generation 1\nBW = Beast Wars\n", "--apply")
    assert "G1: keeps 'My own name' (use --overwrite)" in result.output
    assert full_names()["G1"] == "My own name" and full_names()["BW"] == "Beast Wars"
    run("G1 = Generation 1\n", "--apply", "--overwrite")
    assert full_names()["G1"] == "Generation 1"


@pytest.mark.parametrize(
    "text, message",
    [
        ("Nonesuch = X\n", "line 2: no continuity is called Nonesuch"),
        ("G1 = A\nG1 = B\n", "line 3: G1 is listed twice"),
        ("G1 is Generation 1\n", "line 2: write it as"),
    ],
)
def test_nothing_is_saved_if_anything_is_wrong(continuities, text, message):
    # The first line is fine; the problem is on a later one, and BW must stay empty.
    result = run("BW = Beast Wars\n" + text, "--apply")
    assert result.exit_code == 1 and "Nothing was changed" in result.output
    assert message in result.output
    assert full_names()["BW"] is None


def test_the_list_and_form_show_the_full_name(auth_client, continuities):
    db.session.query(Continuity).filter_by(
        name="G1"
    ).one().full_name = "Generation 1 (G1 era)"
    db.session.commit()
    row = db.session.query(Continuity).filter_by(name="G1").one()
    html = auth_client.get("/continuitymodelview/list/").get_data(as_text=True)
    assert "Full name" in html and "Generation 1 (G1 era)" in html
    assert "Generation 1 (G1 era)" in auth_client.get(
        "/continuitymodelview/show/%s" % row.id
    ).get_data(as_text=True)
    resp = auth_client.post(
        "/continuitymodelview/edit/%s" % row.id,
        data={"name": "G1", "full_name": "Generation One"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert full_names()["G1"] == "Generation One"
