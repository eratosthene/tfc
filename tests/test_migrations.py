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
    flask_app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"),
    reason="migrations are for MariaDB",
)


def _is_ours(obj, name, type_, reflected, compare_to):
    return not (type_ == "table" and name.startswith("ab_"))


PRE_CONTRACT = "i9e1a3b5d780"  # the last revision before the contract


def _empty_database():
    own = [t for t in db.metadata.sorted_tables if not t.name.startswith("ab_")]
    with db.engine.begin() as conn:
        conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
        for name in (
            "tf_wiki_link",
            "accessory",
            "figure_accessory",
            "figure_history",
            "figure_packed_with",
            *[t.name for t in own],
        ):
            conn.exec_driver_sql("DROP TABLE IF EXISTS `%s`" % name)
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")


def _verified():
    with db.engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO data_model_migration (step) VALUES ('apply'), ('verify')"
        )


def _before_the_contract():
    """An empty database at the revision before the contract, with the data
    migration's ``verify`` recorded."""
    _empty_database()
    upgrade(revision=PRE_CONTRACT)
    _verified()


def _sql(statement):
    with db.engine.begin() as conn:
        return conn.exec_driver_sql(statement)


def _add_a_figure(character=True):
    """One figure, in the old and new structures both, as the app left it."""
    _sql("INSERT INTO faction (name) VALUES ('Autobot')")
    _sql("INSERT INTO tf_wiki_link (name, link) VALUES ('Old', 'https://x/Old')")
    _sql("INSERT INTO accessory (name) VALUES ('Axe')")
    _sql("INSERT INTO `character` (name, link) VALUES ('Prime', 'https://x/Prime')")
    _sql(
        "INSERT INTO figure (name, release_year, faction_id, character_id,"
        " figure_link_id, character_id_new, accessories_text, link)"
        " VALUES ('Fig', 2000, 1, 1, 1, %s, 'Axe', 'https://x/Fig')"
        % ("1" if character else "NULL")
    )
    _sql("INSERT INTO figure_accessory (figure_id, accessory_id) VALUES (1, 1)")
    _sql("INSERT INTO figure_history (figure_id, tf_wiki_link_id) VALUES (1, 1)")
    _sql("INSERT INTO figure_packed_with (figure_id, tf_wiki_link_id) VALUES (1, 1)")


def test_migrations_build_the_models_schema():
    """An empty database has nothing to protect, so it needs no ``verify``."""
    with flask_app.app_context():
        _empty_database()
        upgrade()
        with db.engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"include_object": _is_ours})
            assert compare_metadata(ctx, db.metadata) == []


def test_expand_revision_downgrades_and_upgrades_again():
    """b2d4f6a8c013 only adds, so going back one step drops just what it added."""
    from flask_migrate import downgrade
    from sqlalchemy import inspect

    with flask_app.app_context():
        _before_the_contract()
        downgrade(revision="a1c3e5f7b902")
        insp = inspect(db.engine)
        tables = set(insp.get_table_names())
        assert not tables & {"continuity", "character", "figure_reference"}
        assert "tf_wiki_link" in tables
        assert "link" not in {c["name"] for c in insp.get_columns("figure")}
        upgrade(revision=PRE_CONTRACT)
        _verified()
        upgrade()
        insp = inspect(db.engine)
        assert {"continuity", "character", "figure_reference"} <= set(
            insp.get_table_names()
        )
        assert {"link", "character_id", "accessories"} <= {
            c["name"] for c in insp.get_columns("figure")
        }


def test_the_contract_refuses_until_verify_was_recorded(capfd):
    from sqlalchemy import inspect

    with flask_app.app_context():
        _empty_database()
        upgrade(revision=PRE_CONTRACT)
        _add_a_figure()
        with pytest.raises(SystemExit):  # flask-migrate reports the error and exits
            upgrade()
        assert "verify step is not recorded" in capfd.readouterr().err
        insp = inspect(db.engine)
        assert {"tf_wiki_link", "accessory"} <= set(insp.get_table_names())
        assert "figure_link_id" in {c["name"] for c in insp.get_columns("figure")}


def test_the_contract_refuses_while_a_figure_has_no_character(capfd):
    from sqlalchemy import inspect

    with flask_app.app_context():
        _before_the_contract()
        _add_a_figure(character=False)
        with pytest.raises(SystemExit):
            upgrade()
        assert "1 figure(s) have no character" in capfd.readouterr().err
        assert "tf_wiki_link" in inspect(db.engine).get_table_names()


def test_the_contract_drops_the_old_structures_and_keeps_the_new_data():
    from flask_migrate import downgrade
    from sqlalchemy import inspect

    with flask_app.app_context():
        _before_the_contract()
        _add_a_figure()
        upgrade()
        insp = inspect(db.engine)
        assert not set(insp.get_table_names()) & {
            "tf_wiki_link",
            "accessory",
            "figure_accessory",
            "figure_history",
            "figure_packed_with",
        }
        columns = {c["name"]: c for c in insp.get_columns("figure")}
        assert not {"figure_link_id", "character_id_new", "accessories_text"} & set(
            columns
        )
        assert columns["character_id"]["nullable"] is False
        row = _sql("SELECT character_id, accessories, link FROM figure").fetchone()
        assert tuple(row) == (1, "Axe", "https://x/Fig")
        # One foreign key on character_id, to the new character table.
        assert [
            (fk["constrained_columns"], fk["referred_table"])
            for fk in insp.get_foreign_keys("figure")
            if "character_id" in fk["constrained_columns"]
        ] == [(["character_id"], "character")]

        # Going back recreates the empty old structure; the data is a restore.
        downgrade(revision=PRE_CONTRACT)
        insp = inspect(db.engine)
        assert {
            "tf_wiki_link",
            "accessory",
            "figure_accessory",
            "figure_history",
            "figure_packed_with",
        } <= set(insp.get_table_names())
        columns = {c["name"] for c in insp.get_columns("figure")}
        assert {
            "figure_link_id",
            "character_id",
            "character_id_new",
            "accessories_text",
        } <= columns
        row = _sql("SELECT character_id_new, accessories_text FROM figure").fetchone()
        assert tuple(row) == (1, "Axe")
        upgrade()  # and forward again
