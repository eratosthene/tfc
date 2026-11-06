# Copy this file to config.py and fill in the real values. config.py is
# git-ignored, so the real secret key and database host never go in git.
#
#   cp config.py.tpl config.py
#   python -c "import secrets; print(secrets.token_hex(32))"   # for SECRET_KEY
import os

from flask_appbuilder.security.manager import AUTH_DB

basedir = os.path.abspath(os.path.dirname(__file__))

# Your app secret key. Use a long random value and keep it out of git.
SECRET_KEY = "change-me-to-a-long-random-value"

# The SQLAlchemy connection string. Use utf8mb4, as below, so any character
# can be stored. The Compose stack sets it from docker/.env; otherwise this one
# is used.
SQLALCHEMY_DATABASE_URI = os.environ.get(
    "SQLALCHEMY_DATABASE_URI",
    "mysql+pymysql://user:password@host/db?charset=utf8mb4",
)
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Root log level (DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL = "INFO"

# Flask-WTF flag for CSRF
CSRF_ENABLED = True

# ---------------------------------------------------------------------------
# App builder
# ---------------------------------------------------------------------------
APP_NAME = "TFC"
# APP_ICON = "static/img/logo.jpg"

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
# AUTH_DB: username and password stored in the database.
# AUTH_LDAP, AUTH_OID and AUTH_REMOTE_USER are also supported by Flask-AppBuilder.
AUTH_TYPE = AUTH_DB

# Uncomment to set the full admin role name
# AUTH_ROLE_ADMIN = "Admin"

# Uncomment to set a public role that needs no login
# AUTH_ROLE_PUBLIC = "Public"

# Allow self-registration. Off, because users are created by hand
# with `flask fab create-admin`.
AUTH_USER_REGISTRATION = False
# AUTH_USER_REGISTRATION_ROLE = "Public"

# ---------------------------------------------------------------------------
# Images and uploads
# ---------------------------------------------------------------------------
# Image files are stored on disk. The Compose stack mounts this folder as a
# volume so uploads survive container rebuilds.
UPLOAD_FOLDER = os.path.join(basedir, "app", "static", "uploads") + os.sep
IMG_UPLOAD_FOLDER = UPLOAD_FOLDER
IMG_UPLOAD_URL = "/static/uploads/"
# Each model sets its own full and thumbnail sizes; IMG_SIZE is the fallback.
IMG_SIZE = (2000, 2000, False)
