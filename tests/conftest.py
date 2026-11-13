import importlib.util
import os
import sys
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repo root, so ``import app`` works
sys.path.insert(0, HERE)

from guard import assert_test_database  # noqa: E402

# Register the test config as the ``config`` module BEFORE ``app`` is imported,
# because app/__init__.py does app.config.from_object('config') at import time.
_spec = importlib.util.spec_from_file_location(
    "config", os.path.join(HERE, "test_config.py")
)
_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_config)
sys.modules["config"] = _config

# Fail before the app (and so any connection) is created.
assert_test_database(_config.SQLALCHEMY_DATABASE_URI)

from app import app as flask_app, appbuilder, db  # noqa: E402
from app.models import (  # noqa: E402
    Category,
    Character,
    Continuity,
    ContinuityFamily,
    Faction,
    Figure,
    FigureReference,
    Franchise,
    Tooling,
)

TEST_USER = "tester"
TEST_PASSWORD = "tester-pass"


@pytest.fixture(scope="session", autouse=True)
def _db_guard():
    """Fail the whole run if the live app config is not a test database."""
    assert_test_database(flask_app.config["SQLALCHEMY_DATABASE_URI"])


@pytest.fixture(scope="session", autouse=True)
def _schema(_db_guard):
    """Create our tables. (FAB makes its own ab_* tables when the app starts.)"""
    with flask_app.app_context():
        db.create_all()
    yield


@pytest.fixture(autouse=True)
def _app_context():
    """Flask-SQLAlchemy 3 needs an application context for every session use,
    and scopes its session to it, so each test gets a fresh one."""
    with flask_app.app_context():
        yield


@pytest.fixture(autouse=True)
def _clean_models(_schema, _app_context):
    # Empty our tables, not FAB's ab_* ones (the test user lives there).
    db.session.rollback()
    # A franchise may point at another one, so none may keep a parent while the
    # rows are deleted in table order.
    db.session.execute(Franchise.__table__.update().values(parent_id=None))
    for t in reversed(db.metadata.sorted_tables):
        if not t.name.startswith("ab_"):
            db.session.execute(t.delete())
    db.session.commit()
    yield
    db.session.remove()


@pytest.fixture(scope="session")
def admin_user():
    sm = appbuilder.sm
    with flask_app.app_context():
        if not sm.find_user(username=TEST_USER):
            sm.add_user(
                TEST_USER,
                "Test",
                "User",
                "tester@example.com",
                sm.find_role(sm.auth_role_admin),
                TEST_PASSWORD,
            )
    return TEST_USER


@pytest.fixture
def seed():
    franchise = Franchise(
        name="Generation 1",
        start_year=1984,
        end_year=1990,
        link="https://example.com/g1",
    )
    faction = Faction(name="Autobot")
    tooling = Tooling(name="Prime tooling")
    category = Category(name="Leader")
    family = ContinuityFamily(name="Generation 1 family")
    continuity = Continuity(name="G1", family=family)
    character = Character(
        name="Optimus Prime",
        link="https://tfwiki.net/wiki/Optimus_Prime_(G1)",
        continuity=continuity,
    )
    figure = Figure(
        name="Optimus Prime",
        release_year=1984,
        franchise=[franchise],
        character_new=character,
        link="https://tfwiki.net/wiki/Optimus_Prime_(G1)#Generation_1",
        tooling=[tooling],
        faction=faction,
        categories=[category],
        accessories_text="Blaster, Axe",
        references=[
            FigureReference(
                kind="ancestor",
                position=0,
                name="Diaclone Convoy",
                link="https://tfwiki.net/wiki/Diaclone_Convoy",
            ),
            FigureReference(
                kind="packed_with",
                position=0,
                name="Roller",
                link="https://tfwiki.net/wiki/Roller",
            ),
        ],
    )
    db.session.add(figure)
    db.session.commit()
    # Plain ids, not the objects: a request ends the session, which detaches
    # them. Tests that change the data fetch the rows again.
    return {
        k: SimpleNamespace(id=v.id)
        for k, v in {
            "franchise": franchise,
            "faction": faction,
            "tooling": tooling,
            "category": category,
            "character": character,
            "continuity": continuity,
            "family": family,
            "figure": figure,
        }.items()
    }


@pytest.fixture
def client():
    return flask_app.test_client()


@pytest.fixture
def auth_client(client, admin_user):
    resp = client.post(
        "/login/", data={"username": admin_user, "password": TEST_PASSWORD}
    )
    assert resp.status_code in (200, 302)
    return client


# --- tfwiki.net: recorded pages, and a fake wiki (nothing here uses the network) ----


@pytest.fixture
def cached(tmp_path, monkeypatch):
    """The recorded wiki pages (tests/fixtures/tfwiki) as the app's cache, with
    fetching off."""
    import shutil

    source = os.path.join(HERE, "fixtures", "tfwiki")
    folder = tmp_path / "cache"
    folder.mkdir()
    for name in os.listdir(source):
        if name.endswith(".json"):
            shutil.copy(os.path.join(source, name), folder)
    monkeypatch.setitem(flask_app.config, "TFWIKI_CACHE_DIR", str(folder))
    monkeypatch.setitem(flask_app.config, "TFWIKI_ENABLED", False)
    return str(folder)


@pytest.fixture
def csrf_on(monkeypatch):
    """Turn CSRF checking on (the test config has it off)."""
    monkeypatch.setitem(flask_app.config, "WTF_CSRF_ENABLED", True)


@pytest.fixture
def online(cached, monkeypatch):
    """Fetching is on, against a fake wiki. Pages come from the recorded copies (so
    a "refresh" really goes through the fetch path; a page that was not recorded
    is "no such page"); ``state.picture`` is what a picture download returns."""
    import io
    import urllib.parse
    from types import SimpleNamespace

    from PIL import Image

    from app import addfigure, refresh
    from app.tfwiki.fetcher import Fetcher, PageNotFound, cache_name

    buf = io.BytesIO()
    Image.new("RGB", (400, 300), "blue").save(buf, "JPEG")
    state = SimpleNamespace(
        pages=[], pictures=[], picture=(buf.getvalue(), "image/jpeg")
    )

    def get(url):
        title = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["page"][0]
        state.pages.append(title)
        path = os.path.join(cached, cache_name(title))
        if not os.path.exists(path):
            raise PageNotFound(title)
        with open(path, encoding="utf-8") as f:
            return f.read()

    def get_bytes(url):
        state.pictures.append(url)
        if isinstance(state.picture, Exception):
            raise state.picture
        return state.picture

    def make(refreshing=False):
        fetcher = Fetcher(
            cached,
            enabled=True,
            get=get,
            get_bytes=get_bytes,
            sleep=lambda seconds: None,
            wall=lambda: 1000.0,
        )
        return addfigure.Refreshing(fetcher) if refreshing else fetcher

    monkeypatch.setattr(addfigure, "make_fetcher", make)
    monkeypatch.setattr(refresh, "make_fetcher", make)
    return state
