#!/bin/sh
set -e

# config.py isn't in the image; Compose mounts it. Without this check the first
# sign would be an ImportError from deep in the app.
if [ ! -f /app/config.py ]; then
    echo "There's no /app/config.py: mount one (see docker/compose.yml)." >&2
    exit 1
fi

# Once, before gunicorn starts its workers. Importing the app makes Flask-
# AppBuilder create its roles and permissions, and two workers doing that at
# the same moment on a new database collide (duplicate-key errors). Here it
# happens in one process, then the schema is brought up to date.
flask db upgrade

exec "$@"
