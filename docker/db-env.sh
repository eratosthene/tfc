# Sourced inside the db container (by db-entrypoint.sh and scripts/backup.sh).
# Splits SQLALCHEMY_DATABASE_URI, e.g. mysql+pymysql://tfc:secret@db/tfc, into
# the MARIADB_* values, so the URI in .env is the one place the credentials
# live. Use a password with no URL-special characters (@ : / % # ?).
if [ -z "${SQLALCHEMY_DATABASE_URI:-}" ]; then
  echo "Set SQLALCHEMY_DATABASE_URI in .env (mysql+pymysql://tfc:PASSWORD@db/tfc) to use the db service" >&2
  exit 1
fi
_rest="${SQLALCHEMY_DATABASE_URI#*://}"
_cred="${_rest%%@*}"
MARIADB_USER="${_cred%%:*}"
MARIADB_PASSWORD="${_cred#*:}"
MARIADB_DATABASE="${_rest##*/}"
MARIADB_DATABASE="${MARIADB_DATABASE%%\?*}"
export MARIADB_USER MARIADB_PASSWORD MARIADB_DATABASE
