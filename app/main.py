import logging
from flask import Flask
from flask_appbuilder.security.mongoengine.manager import SecurityManager
from flask_appbuilder import AppBuilder
from flask_mongoengine import MongoEngine
from index import MyIndexView

"""
 Logging configuration
"""

logging.basicConfig(format='%(asctime)s:%(levelname)s:%(name)s:%(message)s')
logging.getLogger().setLevel(logging.DEBUG)

app = Flask(__name__)
app.config.from_envvar('TFC_SETTINGS')
db = MongoEngine(app)
appbuilder = AppBuilder(app, security_manager_class=SecurityManager, indexview=MyIndexView)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
