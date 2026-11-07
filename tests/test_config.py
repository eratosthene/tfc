"""Config used by the test suite instead of the git-ignored config.py.

conftest.py registers this module as ``config`` before ``app`` is imported,
so ``app.config.from_object('config')`` loads these values and the tests
never need (or read) a developer's real config.py.
"""

import os
import tempfile

from flask_appbuilder.security.manager import AUTH_DB

SECRET_KEY = "test-secret-key"
# In-memory SQLite by default, for speed. CI sets TEST_DATABASE_URI to its
# MariaDB service (the database name must end in _test, see tests/guard.py).
SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URI", "sqlite://")
SQLALCHEMY_TRACK_MODIFICATIONS = False
LOG_LEVEL = "WARNING"
APP_NAME = "TFC"
AUTH_TYPE = AUTH_DB
AUTH_USER_REGISTRATION = False
CSRF_ENABLED = False
WTF_CSRF_ENABLED = False
TESTING = True
UPLOAD_FOLDER = tempfile.mkdtemp(prefix="tfc-test-uploads-") + os.sep
IMG_UPLOAD_FOLDER = UPLOAD_FOLDER
IMG_UPLOAD_URL = "/static/uploads/"
IMG_SIZE = (2000, 2000, False)
