#!/bin/bash
# Follow the logs of the app on the live server.
#
#   docker/live-logs.sh [-n | --tail LINES]
#
# Starts from the last 100 lines, or LINES with -n ("all" for everything).
# Ctrl-C stops following; the app keeps running.
set -euo pipefail
cd "$(dirname "$0")/.."
tail=100
while [ $# -gt 0 ]; do
    case "$1" in
        -n | --tail) tail=${2:?-n needs a number of lines}; shift 2 ;;
        -h | --help) sed -n '2,7s/^# \{0,1\}//p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
exec sudo docker compose -f docker/compose.yml logs --follow --tail "$tail"
