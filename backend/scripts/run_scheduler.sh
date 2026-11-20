#!/bin/sh
# Scheduler entrypoint: render scripts/crontab with the env schedules,
# validate the result (supercronic -test exits nonzero on a bad schedule,
# so a typo'd .env fails the container loudly instead of silently), then
# run supercronic in the foreground. Job output goes to the container log,
# which compose keeps rotated (json-file, 5 x 50 MB).
set -eu

src="${JB_CRONTAB:-/app/scripts/crontab}"
rendered=/tmp/jb-crontab
cp "$src" "$rendered"

if [ -n "${JB_SOURCE_WAVE_CRON:-}" ]; then
    sed -i "s#^.*\( /bin/bash /app/scripts/source_wave.sh\)#${JB_SOURCE_WAVE_CRON}\1#" "$rendered"
    grep -Fq "${JB_SOURCE_WAVE_CRON} /bin/bash /app/scripts/source_wave.sh" "$rendered" ||
        { echo "scheduler: failed to apply JB_SOURCE_WAVE_CRON"; exit 1; }
fi
if [ -n "${JB_REFRESH_WAVE_CRON:-}" ]; then
    sed -i "s#^.*\( /bin/bash /app/scripts/refresh_wave.sh\)#${JB_REFRESH_WAVE_CRON}\1#" "$rendered"
    grep -Fq "${JB_REFRESH_WAVE_CRON} /bin/bash /app/scripts/refresh_wave.sh" "$rendered" ||
        { echo "scheduler: failed to apply JB_REFRESH_WAVE_CRON"; exit 1; }
fi
if [ -n "${JB_BACKUP_CRON:-}" ]; then
    sed -i "s#^.*\( /bin/sh /app/scripts/backup.sh\)#${JB_BACKUP_CRON}\1#" "$rendered"
    grep -Fq "${JB_BACKUP_CRON} /bin/sh /app/scripts/backup.sh" "$rendered" ||
        { echo "scheduler: failed to apply JB_BACKUP_CRON"; exit 1; }
fi

supercronic -test "$rendered"
echo "scheduler: starting supercronic with:"
cat "$rendered"
exec supercronic -passthrough-logs "$rendered"
