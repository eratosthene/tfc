import logging

from flask import Flask, abort, send_from_directory
from flask_appbuilder import AppBuilder
from flask_appbuilder.models.sqla import CustomSignallingSession
from flask_appbuilder.security.sqla.manager import SecurityManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import orm
from flask_migrate.cli import db as db_cli
from PIL import Image

"""
 Logging configuration
"""

logging.basicConfig(format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")

app = Flask(__name__)
app.config.from_object("config")
app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)


def require_database_uri(config):
    """Without it, Flask-SQLAlchemy quietly falls back to an in-memory SQLite
    database and the app "works" while losing every change. Refuse to start."""
    if not config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError(
            "SQLALCHEMY_DATABASE_URI is not set. Set it in config.py (see "
            "config.py.tpl) or in the SQLALCHEMY_DATABASE_URI environment variable."
        )


require_database_uri(app.config)

logging.getLogger().setLevel(app.config.get("LOG_LEVEL", "INFO"))

# Flask-AppBuilder 3.4 resizes images with Image.ANTIALIAS, which Pillow 10
# removed (Pillow 10.1 is the first with Python 3.12 wheels). Put it back until
# Flask-AppBuilder is upgraded.
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS


# Image files (IMG_UPLOAD_URL, "/static/uploads/") are served from
# UPLOAD_FOLDER, which in Docker is a mounted folder rather than part of the app.
# This rule is more specific than Flask's own /static/<path>, so it wins.
# send_from_directory refuses paths that climb out of the folder.
@app.route("/static/uploads/<path:filename>")
def uploaded_file(filename):
    folder = app.config.get("UPLOAD_FOLDER")
    if not folder:
        abort(404)
    return send_from_directory(folder, filename)


# Our models use db.Model, with its own metadata; FAB creates its security
# tables (ab_*) itself on startup, and Flask-Migrate only handles ours (see
# migrations/env.py). FAB 3.4's session class is needed for SQLAlchemy 1.4 with
# Flask-SQLAlchemy 2.5; the stock one fails in FAB's security setup
# ("get_bind() got an unexpected keyword argument 'bind'").
class TfcSQLAlchemy(SQLAlchemy):
    def create_session(self, options):
        return orm.sessionmaker(class_=CustomSignallingSession, db=self, **options)


db = TfcSQLAlchemy(app)
migrate = Migrate(app, db)
# Flask 1.1 finds `flask db` through pkg_resources, which newer setuptools
# no longer ships, so register the command here to be sure it exists.
app.cli.add_command(db_cli)

from app.index import MyIndexView  # noqa: E402 (needs db, which index imports)

appbuilder = AppBuilder(
    app, db.session, security_manager_class=SecurityManager, indexview=MyIndexView
)

from app import views  # noqa: E402, F401 (registers views after appbuilder setup)
