#!/bin/sh
# Nightly database backup: pg_dump -Fc with zstd compression into
# $JB_BACKUP_DIR, keeping the newest $JB_BACKUP_KEEP archives. Scheduled by
# scripts/crontab in the scheduler service; safe to run by hand. Alerts on
# failure and pings JB_HEARTBEAT_URL after success (scripts/lib.sh). Restore
# steps: DEPLOYMENT.md, section "Backups and restore".
set -eu

. "$(dirname "$0")/lib.sh"

: "${JB_BACKUP_DIR:=/backups}"
: "${JB_BACKUP_KEEP:=7}"

dsn="${JB_DATABASE_URL:-}"
[ -n "$dsn" ] || { echo "backup: JB_DATABASE_URL is not set"; exit 1; }

# libpq speaks postgresql://; the app uses postgresql+asyncpg://.
pgdsn="$(printf '%s' "$dsn" | sed 's|^postgresql+asyncpg://|postgresql://|')"

mkdir -p "$JB_BACKUP_DIR"
stamp="$(date -u +%Y%m%d-%H%M%S)"
out="$JB_BACKUP_DIR/journalbrowser-$stamp.dump"

fail() {
    # $1: what failed. The archive is incomplete or unreadable, so it goes;
    # rerunning the backup is the whole repair.
    rm -f "$out.tmp" "$out"
    alert_post "[$host] backup failed: $1. Resume: $(job_command sh backup.sh)" || :
    exit 1
}

echo "backup: dumping to $out"
# Serialize after an overlapping nightly wave: take a shared lock on
# refresh_wave.lock (waiting up to 2h) so pg_dump waits for active wave DDL /
# rewrites instead of colliding with them.
if mkdir -p "$JB_WAVE_DIR" 2> /dev/null && exec 8>> "$JB_WAVE_DIR/refresh_wave.lock" 2> /dev/null; then
    flock -s -w "${JB_BACKUP_LOCK_WAIT:-7200}" 8 ||
        echo "backup: refresh_wave still holds lock after timeout; proceeding anyway" >&2
fi
# --no-password: fail instead of prompting if the DSN lacks credentials.
# zstd in place of pg_dump's default gzip: measured on a sample of the
# live data, a third smaller archive and decompression 4.5 times faster,
# with no extra dump time (DEPLOYMENT.md, "Backups and restore"). Reading
# the archive back needs pg_restore 17 built with zstd, as the scheduler
# image has; the file name and pg_restore commands stay the same.
pg_dump --no-password --format=custom --compress=zstd:9 --file="$out.tmp" "$pgdsn" ||
    fail "pg_dump exited $?"
exec 8>&- 2> /dev/null || :
mv "$out.tmp" "$out"

# Fail loudly if the archive cannot be read back.
pg_restore --list "$out" > /dev/null || fail "pg_restore --list cannot read $out"
echo "backup: ok ($(du -h "$out" | cut -f1))"
heartbeat "${JB_HEARTBEAT_BACKUP_URL:-}"

# Retention: keep the newest JB_BACKUP_KEEP archives.
ls -1t "$JB_BACKUP_DIR"/journalbrowser-*.dump 2>/dev/null |
    tail -n +"$((JB_BACKUP_KEEP + 1))" |
    while IFS= read -r old; do
        echo "backup: pruning $old"
        rm -f -- "$old"
    done
