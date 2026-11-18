"""Copying ActionFigure411 links and averages in from the My Collection page."""

import json
from datetime import date
from decimal import Decimal

import pytest

from app import app as flask_app, db
from app.af411collection import (
    MAX_ROWS,
    apply_form,
    collect_bookmarklet,
    match_rows,
    money,
    parse_paste,
)
from app.models import Figure

BASE = "https://www.actionfigure411.com/transformers/"
PRIME = BASE + "masterpiece/hasbro/20th-anniversary-optimus-prime-577.php"
BOX = BASE + "war-for-cybertron-siege-series/voyager-class/seekers-3-pack-5365.php"


def _row(**kw):
    row = {
        "af": "577",
        "l": PRIME,
        "n": "20th Anniversary Optimus Prime",
        "g": "Masterpiece - Hasbro",
        "q": "1",
        "c": "L",
        "p": "",
        "v": "",
        "t": "",
        "r": "$99.99",
        "a": "$156.25",
    }
    row.update(kw)
    return row


def _paste(*rows):
    return json.dumps({"v": 1, "rows": list(rows)})


def _figure(seed, name, **kw):
    first = db.session.get(Figure, seed["figure"].id)
    fig = Figure(
        name=name,
        release_year=2004,
        character_new=first.character_new,
        faction=first.faction,
        **kw,
    )
    db.session.add(fig)
    db.session.commit()
    return fig.id


def test_money():
    assert money("$1,234.5") == Decimal("1234.50")
    assert money(12) == Decimal("12.00")
    for bad in ("", None, "n/a", "-3", "NaN", "1e99", "$100,000,000"):
        assert money(bad) is None


@pytest.mark.parametrize(
    "text,message",
    [
        ("not json", "not what the bookmarklet copies"),
        ("[]", "No figures were found"),
        (json.dumps({"v": 2, "rows": [{}]}), "No figures were found"),
        (json.dumps({"v": 1, "rows": []}), "No figures were found"),
        (_paste(*[_row()] * (MAX_ROWS + 1)), "more than"),
    ],
)
def test_a_paste_that_is_not_the_bookmarklets_is_refused(text, message):
    rows, problems = parse_paste(text)
    assert rows == [] and message in problems[0]


def test_bad_rows_are_left_out_and_reported():
    rows, problems = parse_paste(
        _paste(
            _row(),
            "not a row",
            _row(l="https://example.com/x-1.php"),
            _row(l=BASE + "masterpiece-price-guide.php"),
            _row(n=""),
        )
    )
    assert [r["name"] for r in rows] == ["20th Anniversary Optimus Prime"]
    assert len(problems) == 4 and "Row 2 is not a figure." in problems


@pytest.mark.parametrize(
    "note,ids",
    [
        ("113", [113]),
        ("tfc 113", [113]),
        ("TFC #113", [113]),
        ("199, 200 201", [199, 200, 201]),
        ("199+200/199", [199, 200]),
        ("bought at a con", []),
        ("", []),
    ],
)
def test_notes_with_figure_ids(note, ids):
    rows, _ = parse_paste(_paste(_row(t=note)))
    assert rows[0]["note_ids"] == ids


def test_a_row_matches_by_the_id_in_its_note(seed):
    rows, _ = parse_paste(_paste(_row(t=str(seed["figure"].id), n="Optimus Prime")))
    entries, missing = match_rows(rows)
    entry = entries[0]
    assert entry["figure_ids"] == [seed["figure"].id] and entry["basis"] == "Note"
    assert entry["checked"] and not entry["warnings"] and missing == []


def test_a_box_matches_every_figure_in_its_note(seed):
    a = _figure(seed, "Thundercracker")
    b = _figure(seed, "Skywarp")
    rows, _ = parse_paste(_paste(_row(l=BOX, n="Seekers 3 Pack", t="%d, %d" % (a, b))))
    entry = match_rows(rows)[0][0]
    assert entry["figure_ids"] == [a, b] and entry["checked"]
    # No "the figure is called ..." warning: a box is not one figure.
    assert not entry["warnings"]
    assert any("share this box" in n for n in entry["notes"])


def test_a_row_without_a_usable_note_matches_by_exact_name(seed):
    rows, _ = parse_paste(_paste(_row(n="optimus  PRIME")))
    entry = match_rows(rows)[0][0]
    assert entry["figure_ids"] == [seed["figure"].id] and entry["basis"] == "name"


def test_a_note_that_is_no_figures_id_is_flagged_then_the_name_is_tried(seed):
    rows, _ = parse_paste(_paste(_row(t="99999", n="Optimus Prime")))
    entry = match_rows(rows)[0][0]
    assert entry["figure_ids"] == [seed["figure"].id]
    assert (
        any("not a figure's id" in w for w in entry["warnings"])
        and not entry["checked"]
    )


def test_part_of_a_notes_ids_missing_is_flagged(seed):
    rows, _ = parse_paste(_paste(_row(t="%d, 99999" % seed["figure"].id)))
    entry = match_rows(rows)[0][0]
    assert entry["figure_ids"] == [seed["figure"].id]
    assert any("No figure has the id 99999" in w for w in entry["warnings"])


def test_a_name_two_figures_share_lists_the_candidates(seed):
    other = _figure(seed, "Optimus Prime")
    rows, _ = parse_paste(_paste(_row(n="Optimus Prime")))
    entry = match_rows(rows)[0][0]
    assert entry["figure_ids"] == [] and not entry["checked"]
    assert sorted(i for i, _n in entry["candidate_names"]) == sorted(
        [seed["figure"].id, other]
    )


def test_a_row_nothing_matches_is_listed_unchecked(seed):
    rows, _ = parse_paste(_paste(_row(n="Nothing Like It")))
    entry = match_rows(rows)[0][0]
    assert entry["figure_ids"] == [] and entry["candidates"] == []


def test_checks_a_person_should_look_at(seed):
    pk = seed["figure"].id
    second = _figure(seed, "Second", af411_link=BASE + "old-1.php")
    rows, _ = parse_paste(
        _paste(
            # A different name from the figure's, and two pages for one figure.
            _row(t=str(pk), n="Some Other Name"),
            _row(l=BOX, n="Box", t=str(pk)),
            # A figure that already has another link.
            _row(t=str(second), n="Second"),
        )
    )
    entries, _ = match_rows(rows)
    warnings = [w for e in entries for w in e["warnings"]]
    assert any("is called" in w for w in warnings)
    assert any("More than one ActionFigure411 page" in w for w in warnings)
    assert any("already has a different link" in w for w in warnings)
    assert not any(e["checked"] for e in entries)


def test_averages_worth_a_second_look(seed):
    rows, _ = parse_paste(
        _paste(
            _row(a="$99.99"),
            _row(l=BOX, n="B", a="$400.00"),
            _row(l=BASE + "c-3.php", n="C", a="$10.00"),
            _row(l=BASE + "d-4.php", n="D", a="$120.00"),
            _row(l=BASE + "e-5.php", n="E", a=""),
        )
    )
    notes = [e["notes"] for e in match_rows(rows)[0]]
    assert "retail price" in notes[0][0] and "far from" in notes[1][0]
    assert "far from" in notes[2][0] and notes[3] == [] and notes[4] == []


def test_the_figures_not_in_the_paste_are_listed(seed):
    other = _figure(seed, "Zed")
    rows, _ = parse_paste(_paste(_row(t=str(seed["figure"].id))))
    assert match_rows(rows)[1] == [(other, "Zed")]


def _form(**kw):
    form = {
        "count": "1",
        "use0": "1",
        "name0": "Seekers 3 Pack",
        "figure0": "",
        "link0": BOX,
        "average0": "124.25",
    }
    form.update(kw)
    return form


def test_apply_saves_the_link_and_average_on_every_figure_of_a_box(seed):
    a, b = _figure(seed, "A", af411_skipped=True), _figure(seed, "B")
    changed, problems = apply_form(_form(figure0="%d, %d" % (a, b)))
    assert (changed, problems) == (2, [])
    db.session.expire_all()
    for pk in (a, b):
        fig = db.session.get(Figure, pk)
        assert fig.af411_link == BOX and fig.af411_skipped is False
        assert fig.af411_average == Decimal("124.25")
        assert fig.af411_average_on == date.today()


def test_apply_without_an_average_keeps_the_old_one(seed):
    a = _figure(seed, "A", af411_average=Decimal("5.00"))
    apply_form(_form(figure0=str(a), average0=""))
    db.session.expire_all()
    fig = db.session.get(Figure, a)
    assert fig.af411_link == BOX and fig.af411_average == Decimal("5.00")


def test_apply_skips_rows_that_are_not_ticked(seed):
    a = _figure(seed, "A")
    assert apply_form(_form(figure0=str(a), use0="")) == (0, [])
    db.session.expire_all()
    assert db.session.get(Figure, a).af411_link is None


@pytest.mark.parametrize(
    "kw,message",
    [
        ({"figure0": ""}, "no figure has the id"),
        ({"figure0": "99999"}, "no figure has the id"),
        ({"link0": "https://example.com/x-1.php"}, "must be a page on"),
        ({"link0": ""}, "no address"),
        ({"count": "x"}, None),
    ],
)
def test_apply_reports_a_row_it_cannot_save(seed, kw, message):
    a = _figure(seed, "A")
    form = _form(figure0=str(a))
    form.update(kw)
    changed, problems = apply_form(form)
    db.session.expire_all()
    assert changed == 0 and db.session.get(Figure, a).af411_link is None
    if message:
        assert message in problems[0]
    else:
        assert problems == []


def test_two_rows_cannot_give_one_figure_two_links(seed):
    a = _figure(seed, "A")
    form = {
        "count": "2",
        "use0": "1",
        "name0": "One",
        "figure0": str(a),
        "link0": BOX,
        "average0": "",
        "use1": "1",
        "name1": "Two",
        "figure1": str(a),
        "link1": PRIME,
        "average1": "",
    }
    changed, problems = apply_form(form)
    assert changed == 1 and "another row already set a different link" in problems[0]
    db.session.expire_all()
    assert db.session.get(Figure, a).af411_link == BOX


def test_the_bookmarklet_is_safe_in_a_bookmark_address():
    code = collect_bookmarklet()
    assert code.startswith("javascript:(function(){")
    assert "\n" not in code and "%" not in code


# --- the pages ------------------------------------------------------------


def test_the_import_page_offers_the_bookmarklet(auth_client, seed):
    html = auth_client.get("/af411-import/").get_data(as_text=True)
    assert 'href="javascript:(function(){' in html and "Paste here" in html


def test_the_queue_links_to_the_import(auth_client, seed):
    html = auth_client.get("/af411-queue/").get_data(as_text=True)
    assert "/af411-import/" in html


def test_a_bad_paste_shows_what_is_wrong(auth_client, seed):
    html = auth_client.post("/af411-import/preview", data={"data": "nope"}).get_data(
        as_text=True
    )
    assert "not what the bookmarklet copies" in html and "Paste here" in html


def test_the_preview_shows_matches_and_checks(auth_client, seed):
    pk = seed["figure"].id
    text = _paste(
        _row(t=str(pk), n="Optimus Prime"),
        _row(l=BOX, n="Mystery", t="", a="$124.25"),
        _row(l=BASE + "x-9.php", n="Other", t="", a="$10.00"),
        "bad row",
    )
    other = _figure(seed, "Other")
    _figure(seed, "Other")  # a second "Other": a name two figures share
    html = auth_client.post("/af411-import/preview", data={"data": text}).get_data(
        as_text=True
    )
    assert "3 rows read" in html and "(by Note)" in html
    assert "No figure matched." in html and "More than one figure has this name" in html
    assert "not in this list" in html and "Row 4 is not a figure." in html
    assert str(other) in html and "$156.25" in html and "retail $99.99" in html


def test_apply_from_the_page(auth_client, seed):
    pk = seed["figure"].id
    resp = auth_client.post(
        "/af411-import/apply",
        data=_form(figure0=str(pk), name0="Optimus Prime", link0=PRIME),
        follow_redirects=True,
    )
    assert "Saved the ActionFigure411 link and average on 1 figures" in resp.get_data(
        as_text=True
    )
    db.session.expire_all()
    assert db.session.get(Figure, pk).af411_link == PRIME


def test_apply_with_nothing_ticked_and_with_a_bad_row(auth_client, seed):
    html = auth_client.post(
        "/af411-import/apply", data=_form(use0=""), follow_redirects=True
    ).get_data(as_text=True)
    assert "Nothing was ticked" in html
    html = auth_client.post(
        "/af411-import/apply", data=_form(figure0="99999"), follow_redirects=True
    ).get_data(as_text=True)
    assert "no figure has the id" in html and "Nothing was ticked" not in html


def test_the_import_forms_need_the_csrf_token(auth_client, seed, csrf_on):
    for path in ("preview", "apply"):
        resp = auth_client.post("/af411-import/" + path, data=_form(figure0="1"))
        assert resp.status_code == 302
    assert "had expired" in auth_client.get(
        "/af411-import/", follow_redirects=True
    ).get_data(as_text=True)


def test_someone_who_cannot_edit_figures_cannot_apply(auth_client, seed, monkeypatch):
    sm = flask_app.appbuilder.sm
    real = sm.has_access

    def deny_edit(permission, view, *args, **kwargs):
        if (permission, view) == ("can_edit", "FigureModelView"):
            return False
        return real(permission, view, *args, **kwargs)

    monkeypatch.setattr(sm, "has_access", deny_edit)
    pk = seed["figure"].id
    resp = auth_client.post(
        "/af411-import/apply", data=_form(figure0=str(pk), link0=PRIME)
    )
    assert resp.status_code == 403
    db.session.expire_all()
    assert db.session.get(Figure, pk).af411_link is None


def test_the_import_needs_a_login(client, seed):
    assert client.get("/af411-import/").status_code == 302


def test_the_figure_page_shows_the_average(auth_client, seed):
    pk = seed["figure"].id
    html = auth_client.get("/figuremodelview/show/%d" % pk).get_data(as_text=True)
    assert "ActionFigure411 average" in html and "$156.25" not in html
    fig = db.session.get(Figure, pk)
    fig.af411_average, fig.af411_average_on = Decimal("156.25"), date(2026, 11, 18)
    db.session.commit()
    html = auth_client.get("/figuremodelview/show/%d" % pk).get_data(as_text=True)
    assert "$156.25 (copied 2026-11-18)" in html
    fig.af411_average_on = None
    db.session.commit()
    html = auth_client.get("/figuremodelview/show/%d" % pk).get_data(as_text=True)
    assert "$156.25" in html and "(copied" not in html
