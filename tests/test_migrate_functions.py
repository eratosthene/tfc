"""The helper functions of scripts/migrate_mongo_to_sql.py, on small in-memory
inputs. (tests/test_migrate_mongo.py runs the whole script against a real
MongoDB; these need neither Mongo nor a server, only pymongo to import.)
"""

import hashlib
import importlib.util
import io
import os
from types import SimpleNamespace

import pytest

pytest.importorskip("pymongo")

from bson import DBRef, ObjectId  # noqa: E402
from PIL import Image  # noqa: E402

from app import app as flask_app  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "migrate_mongo_to_sql_fn",
    os.path.join(os.path.dirname(__file__), "..", "scripts", "migrate_mongo_to_sql.py"),
)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def _id():
    return ObjectId()


def _png(fmt="PNG", mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, (40, 30), "red").save(buf, fmt)
    return buf.getvalue()


def _data(**docs):
    """A ``data`` mapping like read_mongo's, from {key: [documents]}."""
    out = {}
    for key, spec in mig.SPECS.items():
        out[key] = mig.Data(spec, spec["collections"][0], docs.get(key, []), None)
    return out


def test_oid_accepts_ids_refs_and_none():
    i = _id()
    assert mig.oid(i) == str(i)
    assert mig.oid(DBRef("faction", i)) == str(i)
    assert mig.oid(None) is None


@pytest.mark.parametrize(
    "doc,expected",
    [
        ({}, None),
        ({"image": None}, None),
        ({"image": "abc"}, "abc"),
        ({"image": {"grid_id": "g"}}, "g"),
        ({"image": {"_id": "i"}}, "i"),
        ({"image": {}}, None),
    ],
)
def test_image_id(doc, expected):
    assert mig.image_id(doc) == expected


def test_sha256():
    assert mig.sha256(b"abc") == hashlib.sha256(b"abc").hexdigest()


def test_run_collects_problems_and_warnings():
    run = mig.Run()
    run.problem("p")
    run.warn("w")
    assert run.problems == ["p"] and run.warnings == ["w"] and run.mismatches == []


def test_data_valid_excludes_bad_documents():
    a, b = _id(), _id()
    d = mig.Data(mig.SPECS["faction"], "faction", [{"_id": a}, {"_id": b}], None)
    d.bad[str(a)] = "why"
    assert d.valid == {str(b)}


def test_list_targets_keeps_order_drops_missing_and_repeats():
    a, b, gone = _id(), _id(), _id()
    data = _data(tooling=[{"_id": a, "name": "A"}, {"_id": b, "name": "B"}])
    doc = {"tooling": [b, gone, a, b, DBRef("tooling", a)]}
    assert mig.list_targets(doc, "tooling", "tooling", data) == [str(b), str(a)]
    assert mig.list_targets({}, "tooling", "tooling", data) == []


def test_check_documents_flags_bad_values_and_dangling_references():
    fac, link = _id(), _id()
    ok_fig, no_char, bad_year, long_name = _id(), _id(), _id(), _id()
    data = _data(
        faction=[{"_id": fac, "name": "Autobot"}],
        tf_wiki_link=[
            {"_id": link, "name": "Prime", "link": "https://tfwiki.net/wiki/Prime"}
        ],
        franchise=[{"_id": _id(), "name": "Nameless year"}],  # start_year missing
        tooling=[{"_id": _id(), "name": "x" * 100}],  # longer than the column
        figure=[
            {
                "_id": ok_fig,
                "name": "OK",
                "release_year": "1984",
                "faction": fac,
                "character": link,
                "figure_link": _id(),  # points at nothing: a warning only
                "history": [link, link, _id()],  # repeat and dangling: warnings
            },
            {"_id": no_char, "name": "NC", "release_year": 1, "faction": fac},
            {
                "_id": bad_year,
                "name": "BY",
                "release_year": "soon",
                "faction": fac,
                "character": link,
            },
            {
                "_id": long_name,
                "name": "L",
                "release_year": 1,
                "faction": _id(),  # required but not in faction
                "character": link,
            },
        ],
    )
    run = mig.Run()
    mig.check_documents(data, run)
    bad = data["figure"].bad
    assert set(bad) == {str(no_char), str(bad_year), str(long_name)}
    assert "character is missing" in bad[str(no_char)]
    assert "not a number" in bad[str(bad_year)]
    assert "is not in" in bad[str(long_name)]
    assert len(data["franchise"].bad) == 1 and len(data["tooling"].bad) == 1
    assert any("characters; the column holds" in p for p in run.problems)
    assert any("start_year is missing" in p for p in run.problems)
    assert any("figure_link" in w and "dropped" in w for w in run.warnings)
    assert any("lists" in w and "twice" in w for w in run.warnings)
    assert any("history entry" in w for w in run.warnings)


def test_gestalt_cascade_is_not_needed_for_references_to_figures():
    # A figure whose own faction is bad is left out; one that merely lists it
    # in gestalt_of is kept, with a warning that the entry was dropped.
    bad_fac_fig, other, link, fac = _id(), _id(), _id(), _id()
    data = _data(
        faction=[{"_id": fac, "name": "A"}],
        tf_wiki_link=[{"_id": link, "name": "P", "link": "l"}],
        figure=[
            {"_id": bad_fac_fig, "name": "B", "release_year": 1, "character": link},
            {
                "_id": other,
                "name": "O",
                "release_year": 1,
                "faction": fac,
                "character": link,
                "gestalt_of": [bad_fac_fig],
            },
        ],
    )
    run = mig.Run()
    mig.check_documents(data, run)
    assert set(data["figure"].bad) == {str(bad_fac_fig)}
    assert any("gestalt_of entry" in w for w in run.warnings)


class FakeFS:
    def __init__(self, files):
        self.files = files

    def get(self, gid):
        if gid not in self.files:
            raise mig.gridfs.errors.NoFile(gid)
        body, length, name = self.files[gid]
        return SimpleNamespace(read=lambda: body, length=length, filename=name)


def _d(files):
    return SimpleNamespace(fs=FakeFS(files), spec=mig.SPECS["faction"])


def test_read_image_paths():
    body = _png()
    run = mig.Run()
    d = _d({"ok": (body, len(body), "a.png"), "short": (body, len(body) + 1, "b.png")})
    assert mig.read_image(d, {}, run, "x") is None and not run.problems
    data, out = mig.read_image(d, {"image": "ok"}, run, "x")
    assert data == body and out.filename == "a.png"
    assert mig.read_image(d, {"image": "gone"}, run, "x") is None
    assert mig.read_image(d, {"image": "short"}, run, "x") is None
    assert "not in GridFS" in run.problems[0]
    assert "bytes but" in run.problems[1]


@pytest.mark.parametrize(
    "fmt,ext", [("PNG", ".png"), ("JPEG", ".jpg"), ("GIF", ".gif")]
)
def test_image_filename_uses_the_app_scheme(fmt, ext):
    img = mig.open_image(_png(fmt))
    doc = {"_id": ObjectId("5f0000000000000000000001")}
    d = SimpleNamespace(spec={"key": "faction"})
    name = mig.image_filename(d, doc, SimpleNamespace(filename="My Logo!.png"), img)
    assert "_sep_My_Logo" in name and name.endswith(ext)


def test_image_filename_without_a_stored_name():
    img = mig.open_image(_png())
    doc = {"_id": ObjectId("5f0000000000000000000001")}
    d = SimpleNamespace(spec={"key": "faction"})
    for out in (SimpleNamespace(filename=None), SimpleNamespace()):
        name = mig.image_filename(d, doc, out, img)
        assert "_sep_faction-5f0000000000000000000001.png" in name


@pytest.fixture
def in_app():
    # The script's main() runs inside an app context; FAB's image manager needs one.
    with flask_app.app_context():
        yield


def test_write_image_makes_file_and_thumbnail(tmp_path, in_app):
    folder = str(tmp_path / "up")
    body = _png()
    img = mig.open_image(body)
    path = mig.write_image(folder, (20, 10, False), "a_sep_x.png", body, img)
    assert open(path, "rb").read() == body
    thumb = os.path.join(folder, mig.thumbgen_filename("a_sep_x.png"))
    assert Image.open(thumb).size[0] <= 20


def test_write_image_converts_rgba_jpeg(tmp_path, in_app):
    body = _png("PNG", "RGBA")
    img = mig.open_image(body)
    img.format = "JPEG"  # as if the source were a JPEG the app cannot write as RGBA
    mig.write_image(str(tmp_path), (20, 10, False), "a_sep_x.jpg", body, img)
    assert os.path.isfile(tmp_path / mig.thumbgen_filename("a_sep_x.jpg"))


def test_write_image_uses_jpeg_for_formats_the_app_does_not_list(tmp_path, in_app):
    body = _png("BMP")
    img = mig.open_image(body)
    assert img.format == "BMP"
    mig.write_image(str(tmp_path), (20, 10, False), "a_sep_x.jpg", body, img)
    assert os.path.isfile(tmp_path / mig.thumbgen_filename("a_sep_x.jpg"))


def test_check_file(tmp_path):
    (tmp_path / "f.bin").write_bytes(b"hello")
    good = mig.sha256(b"hello")
    assert mig.check_file(str(tmp_path), "f.bin", 5, good) is None
    assert "missing" in mig.check_file(str(tmp_path), "nope", 5, good)
    assert "bytes" in mig.check_file(str(tmp_path), "f.bin", 6, good)
    assert "SHA-256" in mig.check_file(str(tmp_path), "f.bin", 5, mig.sha256(b"HELLO"))


def test_print_report_lists_everything(capsys):
    run = mig.Run()
    run.warn("a warning")
    run.problem("a problem")
    run.mismatches.append("a mismatch")
    tally = {k: dict(new=1, updated=2, images=3, unchanged=4) for k in mig.SPECS}
    mig.print_report(
        [("faction", 2, 2), ("figure", 3, 2)],
        [("figure_franchise", 1, 1)],
        {"faction": (1, 0)},
        tally,
        run,
        dry_run=False,
    )
    out = capsys.readouterr().out
    assert "Migrated" in out and "ok" in out and "MISMATCH" in out
    assert "Warnings" in out and "Problems" in out and "Mismatches" in out
    mig.print_report(None, None, None, tally, mig.Run(), dry_run=True)
    assert "DRY RUN" in capsys.readouterr().out
