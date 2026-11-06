"""The initial migration must build the same schema as the models.

SQLite can't run it (the schema uses MySQL table options and constraints
alembic won't alter there), so this runs only against MariaDB in CI or Compose.
"""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask_migrate import upgrade

from app import app as flask_app, db

pytestmark = pytest.mark.skipif(
    db.engine.dialect.name == "sqlite", reason="migrations are for MariaDB"
)


def _is_ours(obj, name, type_, reflected, compare_to):
    return not (type_ == "table" and name.startswith("ab_"))


def test_migrations_build_the_models_schema():
    own = [t for t in db.metadata.sorted_tables if not t.name.startswith("ab_")]
    with db.engine.begin() as conn:
        conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
        for t in own:
            conn.exec_driver_sql("DROP TABLE IF EXISTS `%s`" % t.name)
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")
    with flask_app.app_context():
        upgrade()
    with db.engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"include_object": _is_ours})
        assert compare_metadata(ctx, db.metadata) == []
