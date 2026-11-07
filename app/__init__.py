import logging

from flask import Flask
from flask_appbuilder import AppBuilder
from flask_appbuilder.models.sqla import CustomSignallingSession
from flask_appbuilder.security.sqla.manager import SecurityManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import orm
from flask_migrate.cli import db as db_cli

"""
 Logging configuration
"""

logging.basicConfig(format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")

app = Flask(__name__)
app.config.from_object("config")
app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)

logging.getLogger().setLevel(app.config.get("LOG_LEVEL", "INFO"))


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
