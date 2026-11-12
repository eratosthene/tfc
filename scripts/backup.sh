#!/usr/bin/env bash
# Back up TFC: a MariaDB dump and an archive of the uploads folder, as a set
# of dated files in backups/ (git-ignored). A backup needs all of them.
#
#   scripts/backup.sh                                     # live server
#   COMPOSE_FILE=docker/compose.dev.yml scripts/backup.sh # dev stack
#
# The database is dumped from the compose stack's `db` service if it is
# running (dev). Otherwise it is the server's own MariaDB, reached with the
# SQLALCHEMY_DATABASE_URI in docker/.env, using mariadb-dump or mysqldump on
# the host. MongoDB is no longer used and is not backed up here. With no URI the
# dump is skipped with a warning. Run it from cron or launchd; it works from any
# directory. Restore steps are in README.rst.
set -euo pipefail

cd "$(dirname "$0")/.."
compose_file="${COMPOSE_FILE:-docker/compose.yml}"
# On the live server docker needs sudo; set DOCKER="sudo docker" for that.
read -r -a docker <<< "${DOCKER:-docker}"
# -f rather than exporting COMPOSE_FILE: sudo resets the environment, so the
# variable would never reach `sudo docker compose`.
compose=("${docker[@]}" compose -f "$compose_file")
out="${BACKUP_DIR:-backups}"
stamp="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$out"
rm -f "$out"/*.part

db_part="$out/tfc-db-$stamp.sql.gz.part"
if "${compose[@]}" ps --status running --services | grep -qx db; then
  "${compose[@]}" exec -T db sh -c \
    '. /db-env.sh; exec mariadb-dump --single-transaction --routines -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"' \
    | gzip > "$db_part"
else
  uri="${SQLALCHEMY_DATABASE_URI:-}"
  if [ -z "$uri" ] && [ -f docker/.env ]; then
    # Value may be single-quoted, as the README advises.
    uri="$(sed -n "s/^SQLALCHEMY_DATABASE_URI=//p" docker/.env | tail -1 | sed "s/^'\(.*\)'\$/\1/")"
  fi
  if [ -z "$uri" ]; then
    echo "WARNING: no SQLALCHEMY_DATABASE_URI; skipping the database dump." >&2
  else
    rest="${uri#*://}"; cred="${rest%%@*}"; hostdb="${rest#*@}"
    user="${cred%%:*}"; pass="${cred#*:}"
    host="${hostdb%%/*}"; name="${hostdb#*/}"; name="${name%%\?*}"
    port="${host##*:}"; [ "$port" = "$host" ] && port=3306; host="${host%%:*}"
    dump="$(command -v mariadb-dump || command -v mysqldump)"
    MYSQL_PWD="$pass" "$dump" --single-transaction --routines \
      -h "$host" -P "$port" -u "$user" "$name" | gzip > "$db_part"
  fi
fi

"${compose[@]}" exec -T tfc tar czf - -C /app/app/static uploads \
  > "$out/tfc-uploads-$stamp.tar.gz.part"

# Rename only once everything succeeded, so a half-finished backup never
# looks complete.
[ ! -e "$db_part" ] || mv "$db_part" "$out/tfc-db-$stamp.sql.gz"
mv "$out/tfc-uploads-$stamp.tar.gz.part" "$out/tfc-uploads-$stamp.tar.gz"
echo "Backup $stamp written to $out/"
