"""Config used by the test suite instead of the git-ignored config.py.

conftest.py registers this module as ``config`` before ``app`` is imported,
so ``app.config.from_object('config')`` loads these values and the tests
never need (or read) a developer's real config.py.
"""

from flask_appbuilder.security.manager import AUTH_DB

SECRET_KEY = "test-secret-key"
MONGODB_SETTINGS = {"host": "mongomock://localhost/tfc_test"}
LOG_LEVEL = "WARNING"
APP_NAME = "TFC"
AUTH_TYPE = AUTH_DB
AUTH_USER_REGISTRATION = False
CSRF_ENABLED = False
WTF_CSRF_ENABLED = False
TESTING = True
UPLOAD_FOLDER = "/tmp/tfc-test-uploads/"
IMG_UPLOAD_FOLDER = UPLOAD_FOLDER
IMG_UPLOAD_URL = "/static/uploads/"
