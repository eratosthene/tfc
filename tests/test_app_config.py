"""How the app loads its configuration (config.py, or config.py.tpl as a model).

The app does ``app.config.from_object("config")`` at import time, so these run
a fresh interpreter in a temp folder with only the config under test.
"""

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import textwrap


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIRED = [
    "SECRET_KEY",
    "SQLALCHEMY_DATABASE_URI",
    "UPLOAD_FOLDER",
    "IMG_UPLOAD_FOLDER",
]


def _load_template(monkeypatch, **env):
    monkeypatch.delenv("SQLALCHEMY_DATABASE_URI", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    path = os.path.join(ROOT, "config.py.tpl")
    loader = importlib.machinery.SourceFileLoader("tfc_config_tpl", path)
    spec = importlib.util.spec_from_loader("tfc_config_tpl", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_template_defines_every_required_setting(monkeypatch):
    mod = _load_template(monkeypatch)
    for name in REQUIRED + ["AUTH_TYPE", "APP_NAME", "IMG_UPLOAD_URL"]:
        assert getattr(mod, name), name
    assert mod.SQLALCHEMY_DATABASE_URI.startswith("mysql+pymysql://")
    assert "utf8mb4" in mod.SQLALCHEMY_DATABASE_URI
    assert mod.UPLOAD_FOLDER.endswith(os.sep)
    assert mod.IMG_UPLOAD_FOLDER == mod.UPLOAD_FOLDER


def test_template_database_uri_comes_from_the_environment(monkeypatch):
    mod = _load_template(monkeypatch, SQLALCHEMY_DATABASE_URI="sqlite:///x.db")
    assert mod.SQLALCHEMY_DATABASE_URI == "sqlite:///x.db"


def test_test_config_is_what_the_app_loaded():
    from app import app as flask_app

    for name in REQUIRED:
        assert flask_app.config[name]
    assert flask_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] is False


def _run_app_import(tmp_path, config_source):
    if config_source is not None:
        (tmp_path / "config.py").write_text(textwrap.dedent(config_source))
    env = dict(os.environ, PYTHONPATH=ROOT, PYTHONDONTWRITEBYTECODE="1")
    env.pop("TEST_DATABASE_URI", None)
    code = "import app; print(app.app.config.get('SECRET_KEY'))"
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )


def test_missing_config_module_fails_with_a_clear_message(tmp_path):
    proc = _run_app_import(tmp_path, None)
    assert proc.returncode != 0
    assert "No module named 'config'" in proc.stderr
    assert "Original exception" in proc.stderr  # Flask's own wording


def test_app_loads_a_complete_config(tmp_path):
    proc = _run_app_import(
        tmp_path,
        """
        from flask_appbuilder.security.manager import AUTH_DB
        SECRET_KEY = "from-file"
        SQLALCHEMY_DATABASE_URI = "sqlite://"
        AUTH_TYPE = AUTH_DB
        LOG_LEVEL = "ERROR"
        """,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().endswith("from-file")


def test_other_settings_are_not_enforced(tmp_path):
    # Documents today's behavior: only the import of config.py is checked.
    # SECRET_KEY, the database URI and UPLOAD_FOLDER are not required by the
    # app, so a config without them still loads (and Flask-SQLAlchemy falls
    # back to an in-memory SQLite database).
    proc = _run_app_import(tmp_path, 'SECRET_KEY = "only-this"\n')
    assert proc.returncode == 0, proc.stderr
    assert "only-this" in proc.stdout
