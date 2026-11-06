import importlib.util
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repo root, so ``import app`` works
sys.path.insert(0, HERE)

from guard import assert_mongomock  # noqa: E402

# Register the test config as the ``config`` module BEFORE ``app`` is imported,
# because app/__init__.py does app.config.from_object('config') at import time.
_spec = importlib.util.spec_from_file_location(
    "config", os.path.join(HERE, "test_config.py")
)
_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_config)
sys.modules["config"] = _config

# Fail before the app (and so any connection) is created.
assert_mongomock(_config.MONGODB_SETTINGS)

from app import app as flask_app, appbuilder  # noqa: E402
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
    """Fail the whole run if the live app config does not point at mongomock."""
    assert_mongomock(flask_app.config["MONGODB_SETTINGS"])


@pytest.fixture(autouse=True)
def _clean_models():
    for m in (Figure, Franchise, Faction, Tooling, Category, Accessory, TFWikiLink):
        m.drop_collection()
    yield


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
    ).save()
    faction = Faction(name="Autobot").save()
    tooling = Tooling(name="Prime tooling").save()
    category = Category(name="Leader").save()
    accessory = Accessory(name="Blaster").save()
    character = TFWikiLink(
        name="Optimus Prime", link="https://tfwiki.net/wiki/Optimus_Prime"
    ).save()
    figure_link = TFWikiLink(
        name="Optimus Prime",
        link="https://tfwiki.net/wiki/Optimus_Prime_(G1)#Generation_1",
    ).save()
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
    ).save()
    return {
        "franchise": franchise,
        "faction": faction,
        "tooling": tooling,
        "category": category,
        "accessory": accessory,
        "character": character,
        "figure_link": figure_link,
        "figure": figure,
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
