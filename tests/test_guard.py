import pytest

from guard import assert_mongomock
from app import app as flask_app


def test_guard_accepts_mongomock():
    assert_mongomock({"host": "mongomock://localhost/x"})


@pytest.mark.parametrize("settings", [
    {"host": "localhost"},
    {"host": "mongodb://db.example.com:27017/tfc"},
    {"host": ["mongomock://a", "mongodb://real"]},
    {"DB": "tfc"},
    {},
])
def test_guard_rejects_real_hosts(settings):
    with pytest.raises(RuntimeError, match="not mongomock"):
        assert_mongomock(settings)


def test_running_app_uses_mongomock():
    assert_mongomock(flask_app.config["MONGODB_SETTINGS"])
