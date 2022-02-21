import logging
from flask import Flask
from flask_appbuilder.security.mongoengine.manager import SecurityManager
from flask_appbuilder import AppBuilder
from flask_mongoengine import MongoEngine
from app.index import MyIndexView

"""
 Logging configuration
"""

logging.basicConfig(format='%(asctime)s:%(levelname)s:%(name)s:%(message)s')
logging.getLogger().setLevel(logging.DEBUG)

app = Flask(__name__)
app.config.from_envvar('TFC_SETTINGS')
db = MongoEngine(app)
appbuilder = AppBuilder(app, security_manager_class=SecurityManager, indexview=MyIndexView)

from app import views

