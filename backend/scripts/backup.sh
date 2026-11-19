#!/bin/sh
# Nightly database backup: pg_dump -Fc into $JB_BACKUP_DIR, keeping the
# newest $JB_BACKUP_KEEP archives. Scheduled by scripts/crontab in the
# scheduler service; safe to run by hand. Restore steps: DEPLOYMENT.md,
# section "Backups and restore".
set -eu

: "${JB_BACKUP_DIR:=/backups}"
: "${JB_BACKUP_KEEP:=7}"

dsn="${JB_DATABASE_URL:-}"
[ -n "$dsn" ] || { echo "backup: JB_DATABASE_URL is not set"; exit 1; }

# libpq speaks postgresql://; the app uses postgresql+asyncpg://.
pgdsn="$(printf '%s' "$dsn" | sed 's|^postgresql+asyncpg://|postgresql://|')"

mkdir -p "$JB_BACKUP_DIR"
stamp="$(date -u +%Y%m%d-%H%M%S)"
out="$JB_BACKUP_DIR/journalbrowser-$stamp.dump"

echo "backup: dumping to $out"
# --no-password: fail instead of prompting if the DSN lacks credentials.
pg_dump --no-password --format=custom --file="$out.tmp" "$pgdsn"
mv "$out.tmp" "$out"

# Fail loudly if the archive cannot be read back.
pg_restore --list "$out" > /dev/null
echo "backup: ok ($(du -h "$out" | cut -f1))"

# Retention: keep the newest JB_BACKUP_KEEP archives.
ls -1t "$JB_BACKUP_DIR"/journalbrowser-*.dump 2>/dev/null |
    tail -n +"$((JB_BACKUP_KEEP + 1))" |
    while IFS= read -r old; do
        echo "backup: pruning $old"
        rm -f -- "$old"
    done
