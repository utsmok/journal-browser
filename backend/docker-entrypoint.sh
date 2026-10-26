#!/bin/sh
# Every container start flows through here. When root (compose sets the
# bootstrap service root-only so the bind-mounted landing dir, which the
# docker daemon creates root-owned on fresh hosts, can be handed over),
# chown it and drop to uid 1000 so jobs and `docker compose run` one-offs
# never write root-owned files into the host mount.
set -e

if [ "$(id -u)" = "0" ]; then
    chown -R 1000:1000 /app/landing
    # HOME too: compose sets root's /root, which uid 1000 cannot write
    # (uv's cache lives under it).
    export HOME=/home/app
    exec setpriv --reuid=1000 --regid=1000 --clear-groups "$@"
fi

exec "$@"
