import logging
from flask import Flask
from flask_appbuilder.security.mongoengine.manager import SecurityManager
from flask_appbuilder import AppBuilder
from flask_mongoengine import MongoEngine
from app.index import MyIndexView

"""
 Logging configuration
"""

logging.basicConfig(format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")

app = Flask(__name__)
app.config.from_object("config")

logging.getLogger().setLevel(app.config.get("LOG_LEVEL", "INFO"))
db = MongoEngine(app)
appbuilder = AppBuilder(
    app, security_manager_class=SecurityManager, indexview=MyIndexView
)

from app import views
