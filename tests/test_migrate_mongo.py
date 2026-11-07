"""scripts/migrate_mongo_to_sql.py, against a real MongoDB (GridFS included).

Needs TEST_MONGO_URI, for example mongodb://127.0.0.1:27017 (CI has a service;
locally: ``docker run --rm -p 27017:27017 mongo:4.4``). Each test makes its own
throwaway Mongo database and drops it. Skipped without a URI or pymongo.
"""

import hashlib
import importlib.util
import os
import uuid

import pytest

pymongo = pytest.importorskip("pymongo")

import mongo_fixture  # noqa: E402
from app import app as flask_app, db  # noqa: E402
from app.models import Faction, Figure, Franchise, Tooling, TFWikiLink  # noqa: E402

MONGO_URI = os.environ.get("TEST_MONGO_URI")
pytestmark = pytest.mark.skipif(not MONGO_URI, reason="TEST_MONGO_URI is not set")

_spec = importlib.util.spec_from_file_location(
    "migrate_mongo_to_sql",
    os.path.join(os.path.dirname(__file__), "..", "scripts", "migrate_mongo_to_sql.py"),
)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)

FOLDER = flask_app.config["IMG_UPLOAD_FOLDER"]


@pytest.fixture
def mongo():
    client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    name = "tfc_migtest_" + uuid.uuid4().hex[:8]
    mdb = client[name]
    ids = mongo_fixture.load(mdb)
    yield mdb, ids, name
    client.drop_database(name)
    for f in os.listdir(FOLDER):
        p = os.path.join(FOLDER, f)
        if os.path.isfile(p):
            os.remove(p)


def run(name, *args):
    return mig.main(["--mongo-uri", MONGO_URI, "--mongo-db", name, *args])


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def test_dry_run_writes_nothing(mongo, capsys):
    _mdb, _ids, name = mongo
    assert run(name, "--dry-run") == 0  # the dangling figure_link is only a warning
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "figure" in out
    assert db.session.query(Figure).count() == 0
    assert db.session.query(Franchise).count() == 0
    assert os.listdir(FOLDER) == []


def test_migrates_everything_and_verifies(mongo, capsys):
    mdb, ids, name = mongo
    assert run(name, "--seed", "1") == 0, capsys.readouterr().out
    q = db.session.query
    assert q(Franchise).count() == 2
    assert q(Tooling).count() == 2
    assert q(TFWikiLink).count() == 4
    fig = q(Figure).filter_by(legacy_id=str(ids["fig1"])).one()
    assert fig.name == "Optimus Prime" and fig.quantity == 2
    assert fig.figure_link.legacy_id == str(ids["optimus_fig"])
    # List order is kept.
    assert [f.name for f in fig.franchise] == ["Beast Wars", "Generation 1"]
    assert [t.name for t in fig.tooling] == ["Megatron étude ☃", "Prime tooling"]
    assert [x.name for x in fig.packed_with] == ["Soundwave", "Megatron"]
    assert [c.name for c in fig.categories] == ["Voyager", "Leader"]
    other = q(Figure).filter_by(legacy_id=str(ids["fig2"])).one()
    assert [g.name for g in other.gestalt_of] == ["Optimus Prime"]
    assert other.figure_link is None and other.quantity == 1
    # Images: same bytes as GridFS, the app's name scheme, and a thumbnail.
    assert "_sep_" in fig.image and fig.image.endswith(".jpg")
    src = (
        mig.gridfs.GridFS(mdb, collection="figure_images")
        .get([d for d in mdb.figure.find({"image": {"$ne": None}})][0]["image"])
        .read()
    )
    assert sha(os.path.join(FOLDER, fig.image)) == hashlib.sha256(src).hexdigest()
    assert os.path.isfile(os.path.join(FOLDER, mig.thumbgen_filename(fig.image)))
    assert q(Faction).filter_by(name="Autobot").one().image


def test_rerun_is_idempotent(mongo, capsys):
    _mdb, _ids, name = mongo
    assert run(name) == 0
    q = db.session.query
    before = {f.legacy_id: (f.id, f.image) for f in q(Figure)}
    files = sorted(os.listdir(FOLDER))
    db.session.remove()
    assert run(name) == 0
    assert {f.legacy_id: (f.id, f.image) for f in q(Figure)} == before
    assert sorted(os.listdir(FOLDER)) == files
    assert q(Franchise).count() == 2 and q(Figure).count() == 2


def test_verify_catches_changes(mongo, capsys):
    _mdb, _ids, name = mongo
    assert run(name) == 0
    capsys.readouterr()
    fig = db.session.query(Figure).filter_by(name="Megatron").one()
    fig.name = "Changed"
    path = os.path.join(
        FOLDER, db.session.query(Faction).filter_by(name="Autobot").one().image
    )
    db.session.commit()
    with open(path, "ab") as fh:
        fh.write(b"x")
    assert run(name, "--verify-only") == 1
    out = capsys.readouterr().out
    assert "name is 'Changed'" in out
    assert "SHA-256" in out or "bytes" in out


def test_figure_with_missing_required_reference_is_left_out(mongo, capsys):
    mdb, ids, name = mongo
    mdb.t_f_wiki_link.delete_one({"_id": ids["mega"]})  # fig2's character
    assert run(name) == 1
    out = capsys.readouterr().out
    assert "left out" in out
    q = db.session.query
    assert q(Figure).count() == 1  # the other figure still migrated
    assert q(Figure).one().name == "Optimus Prime"
    assert [h.name for h in q(Figure).one().history] == []  # entry pointed at nothing
