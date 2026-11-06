#!/bin/sh
# Derive the MariaDB user, password and database from SQLALCHEMY_DATABASE_URI,
# then hand over to the image's own entrypoint.
set -e
. /db-env.sh
exec docker-entrypoint.sh "$@"
