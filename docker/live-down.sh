#!/bin/bash
# Stop the app on the live server and remove its container.
#
#   docker/live-down.sh
#
# It runs `sudo docker compose -f docker/compose.yml down`. The uploads
# volume is kept. docker/live-up.sh starts it again.
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-}" in
    "") ;;
    -h | --help) sed -n '2,7s/^# \{0,1\}//p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
esac
exec sudo docker compose -f docker/compose.yml down
