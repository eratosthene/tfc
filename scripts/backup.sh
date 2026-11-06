#!/usr/bin/env bash
# Back up TFC: a MariaDB dump and an archive of the uploads folder, as a
# matching pair of dated files in backups/ (git-ignored). A backup needs both.
# While the app still uses MongoDB (until sub-issue #7), a mongodump archive
# is taken too, if the mongo service is running.
#
#   scripts/backup.sh
#
# Run it from cron or launchd; it works from any directory. Restore steps are
# in README.rst.
set -euo pipefail

cd "$(dirname "$0")/.."
out="${BACKUP_DIR:-backups}"
stamp="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$out"

# The password is already in the db container's environment.
docker compose exec -T db sh -c \
  'exec mariadb-dump --single-transaction --routines -u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"' \
  | gzip > "$out/tfc-db-$stamp.sql.gz.part"

docker compose exec -T app tar czf - -C /app/app/static uploads \
  > "$out/tfc-uploads-$stamp.tar.gz.part"

if docker compose ps --status running --services | grep -qx mongo; then
  docker compose exec -T mongo mongodump --quiet --archive --gzip \
    > "$out/tfc-mongo-$stamp.archive.gz.part"
  mv "$out/tfc-mongo-$stamp.archive.gz.part" "$out/tfc-mongo-$stamp.archive.gz"
fi

# Rename only once everything succeeded, so a half-finished backup never
# looks complete.
mv "$out/tfc-db-$stamp.sql.gz.part" "$out/tfc-db-$stamp.sql.gz"
mv "$out/tfc-uploads-$stamp.tar.gz.part" "$out/tfc-uploads-$stamp.tar.gz"
echo "Backup $stamp written to $out/"
