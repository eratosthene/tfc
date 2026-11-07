import pytest

from guard import assert_test_database
from app import app as flask_app


@pytest.mark.parametrize(
    "uri",
    [
        "sqlite://",
        "sqlite:////tmp/x.db",
        "mysql+pymysql://u:p@db/tfc_test?charset=utf8mb4",
    ],
)
def test_guard_accepts_test_databases(uri):
    assert_test_database(uri)


@pytest.mark.parametrize(
    "uri",
    [
        "mysql+pymysql://u:p@db/tfc",
        "mysql+pymysql://u:p@db.example.com/",
        "postgresql://u:p@db/production",
    ],
)
def test_guard_rejects_real_databases(uri):
    with pytest.raises(RuntimeError, match="Refusing"):
        assert_test_database(uri)


def test_running_app_uses_test_database():
    assert_test_database(flask_app.config["SQLALCHEMY_DATABASE_URI"])
