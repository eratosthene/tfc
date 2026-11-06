#!/bin/bash
# Build the image and start the app on the live server, from this checkout.
#
#   docker/live-up.sh [-n | --no-build]
#
# It runs `sudo docker compose -f docker/compose.yml up -d --build
# --force-recreate`, which replaces the running container. -n skips the
# build, which is all a change to config.py or docker/.env needs. It makes an
# empty docker/.env if there isn't one.
set -euo pipefail

cd "$(dirname "$0")/.."

build=(--build)
while [ $# -gt 0 ]; do
    case "$1" in
        -n | --no-build) build=(); shift ;;
        -h | --help) sed -n '2,9s/^# \{0,1\}//p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

# The container mounts config.py rather than having it built in.
if [ ! -f config.py ]; then
    echo "config.py is missing; copy config.py.tpl to config.py and fill it in." >&2
    exit 1
fi
# docker/compose.yml needs docker/.env, even an empty one. It can hold
# secrets, so only its owner can read it.
if [ ! -f docker/.env ]; then
    (umask 077 && touch docker/.env)
    echo "Made an empty docker/.env."
fi

# Recreated even when nothing in the compose file changed, since `up -d`
# alone doesn't notice an edit to the mounted config.py.
sudo docker compose -f docker/compose.yml up -d "${build[@]}" --force-recreate
echo
echo "Started; the app is on port 9999 once it's up."
echo "  Follow the logs: docker/live-logs.sh"
echo "  Stop it:         docker/live-down.sh"
