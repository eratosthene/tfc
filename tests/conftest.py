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
    Faction,
    Figure,
    Franchise,
    Tooling,
    Category,
    Accessory,
    TFWikiLink,
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
    db.create_all()
    yield


@pytest.fixture(autouse=True)
def _clean_models(_schema):
    # Empty our tables, not FAB's ab_* ones (the test user lives there).
    db.session.rollback()
    for t in reversed(db.metadata.sorted_tables):
        if not t.name.startswith("ab_"):
            db.session.execute(t.delete())
    db.session.commit()
    yield
    db.session.remove()


@pytest.fixture(scope="session")
def admin_user():
    sm = appbuilder.sm
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
    accessory = Accessory(name="Blaster")
    character = TFWikiLink(
        name="Optimus Prime", link="https://tfwiki.net/wiki/Optimus_Prime"
    )
    figure_link = TFWikiLink(
        name="Optimus Prime",
        link="https://tfwiki.net/wiki/Optimus_Prime_(G1)#Generation_1",
    )
    figure = Figure(
        name="Optimus Prime",
        release_year=1984,
        franchise=[franchise],
        character=character,
        figure_link=figure_link,
        tooling=[tooling],
        faction=faction,
        categories=[category],
        accessories=[accessory],
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
            "accessory": accessory,
            "character": character,
            "figure_link": figure_link,
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
