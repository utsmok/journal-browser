#!/bin/sh
# Every container start flows through here. When root (compose sets the
# bootstrap service root-only so the bind-mounted landing dir, which the
# docker daemon creates root-owned on fresh hosts, can be handed over),
# chown it and drop to uid 1000 so jobs and `docker compose run` one-offs
# never write root-owned files into the host mount.
set -e

if [ "$(id -u)" = "0" ]; then
    # Bind-mounted dirs: docker creates them root-owned on fresh hosts;
    # hand them to uid 1000 so jobs and `docker compose run` one-offs
    # never write root-owned files into the host mounts.
    if [ -d /app/landing ]; then chown -R 1000:1000 /app/landing; fi
    if [ -d /app/state ]; then chown -R 1000:1000 /app/state; fi
    if [ -d /backups ]; then chown -R 1000:1000 /backups; fi
    # First boot: seed the settings overlay from the shipped example. The
    # admin panel writes this file (secrets included), so it stays out of
    # git and lives in the bind-mounted ./backend/state dir; compose sets
    # JB_SETTINGS_YAML=/app/state/settings.yaml in every service that uses
    # it. Deployments that predate the state dir move their existing file
    # there once (see DEPLOYMENT.md, First boot).
    if [ -f /app/settings.yaml.example ] && [ -d /app/state ] && [ ! -f /app/state/settings.yaml ]; then
        cp /app/settings.yaml.example /app/state/settings.yaml
        chown 1000:1000 /app/state/settings.yaml
    fi
    # HOME too: compose sets root's /root, which uid 1000 cannot write
    # (uv's cache lives under it).
    export HOME=/home/app
    exec setpriv --reuid=1000 --regid=1000 --clear-groups "$@"
fi

exec "$@"
