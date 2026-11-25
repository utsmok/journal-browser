# shellcheck shell=sh
# Shared helpers for the scheduled jobs: refresh_wave.sh, source_wave.sh,
# backup.sh and run_scheduler.sh source this file. POSIX sh on purpose: the
# waves run under bash, backup.sh and the scheduler entrypoint under dash.
#
# Failure alerts. With JB_ALERT_WEBHOOK_URL set (a Slack or Mattermost
# incoming webhook), a job that fails POSTs one JSON message,
# {"text": "..."}: which host, which job, which stage failed, and the
# command that resumes it. Without the variable the alert is the log line
# alone.
#
# Success heartbeat. With JB_HEARTBEAT_URL set, a job that ends well sends
# one GET, as a healthchecks.io check expects.
#
# Wave record. A wave writes the stage it is about to run to
# landing/waves/<wave>.state and removes the file when it exits. A wave
# killed by SIGKILL or the OOM killer cannot, so the next scheduler or wave
# start reports the leftover (report_dead_waves). While it runs, the wave
# holds an flock on landing/waves/<wave>.lock: that tells a wave that still
# runs elsewhere from a dead one, and stops a second copy of the same wave.
# Compose bind-mounts the landing directory into every service that runs
# jobs, so all containers see the same files.

_jb_root="$(cd "$(dirname "$0")/.." && pwd)"
JB_WAVE_DIR="${JB_LANDING_DIR:-$_jb_root/landing}/waves"
host="${JB_ALERT_HOST:-$(hostname 2> /dev/null || echo unknown)}"

alert_post() {
    # $1: message. Logs it, and POSTs it when JB_ALERT_WEBHOOK_URL is set.
    # Returns 1 only when a configured post failed.
    echo "alert: $1"
    [ -n "${JB_ALERT_WEBHOOK_URL:-}" ] || return 0
    body="$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr '\n\r\t' '   ')"
    if ! curl -fsS --max-time 15 -X POST -H 'Content-Type: application/json' \
        --data "{\"text\": \"$body\"}" "$JB_ALERT_WEBHOOK_URL" > /dev/null 2>&1; then
        echo "alert: could not post to JB_ALERT_WEBHOOK_URL" >&2
        return 1
    fi
    return 0
}

heartbeat() {
    # One GET after a job ended well (a healthchecks.io dead-man's switch).
    if [ -n "${JB_HEARTBEAT_URL:-}" ]; then
        curl -fsS --max-time 10 --retry 3 "$JB_HEARTBEAT_URL" > /dev/null 2>&1 ||
            echo "heartbeat: could not reach JB_HEARTBEAT_URL" >&2
    fi
    return 0
}

job_command() {
    # $1 interpreter, $2 script, $3 stage (may be empty): the command that
    # reruns the job by hand, from the repository root. The waves need bash,
    # not sh: they use arrays.
    if [ "$_jb_root" = /app ]; then
        prefix="docker compose run --rm --entrypoint /bin/$1 scheduler /app/scripts/"
    else
        prefix="$1 scripts/"
    fi
    echo "$prefix$2${3:+ --from $3}"
}

_field() {
    # $1 state file, $2 key: its value, or empty.
    sed -n "s/^$2=//p" "$1" 2> /dev/null | head -n 1
}

_wave_alive() {
    # $1 wave. Exit 0 while a live process holds its lock.
    [ -e "$JB_WAVE_DIR/$1.lock" ] && ! flock -n "$JB_WAVE_DIR/$1.lock" true 2> /dev/null
}

report_dead_waves() {
    # Report every wave killed before it could exit, once: the leftover
    # state file is the record, and goes away with the delivered report.
    # The resume stage is the first stage that failed, when any; else the
    # stage that was running.
    # $1: a wave to leave alone.
    for state in "$JB_WAVE_DIR"/*.state; do
        [ -e "$state" ] || continue
        wave="${state##*/}"
        wave="${wave%.state}"
        [ "$wave" != "${1:-}" ] || continue
        _wave_alive "$wave" && continue
        failed="$(_field "$state" failed)"
        stage="${failed%% *}"
        [ -n "$stage" ] || stage="$(_field "$state" stage)"
        message="[$host] $wave was stopped before it finished and is not running."
        [ -z "$failed" ] || message="$message Failed stages: $failed."
        message="$message Last stage: $(_field "$state" stage) (since $(_field "$state" since))."
        if alert_post "$message Resume: $(job_command bash "$wave.sh" "$stage")"; then
            rm -f "$state"
        fi
    done
    return 0
}

wave_begin() {
    # $1 wave name, $2 "resume" when the operator passed --from. Reports
    # waves killed earlier, refuses to start while another copy runs, then
    # arms the exit trap. A leftover of a resumed wave is not reported: the
    # operator is already acting on it.
    WAVE="$1"
    WAVE_STAGE=""
    WAVE_SINCE=""
    WAVE_FAILED=""
    WAVE_SKIPPED=""
    WAVE_REPORTED=""
    mkdir -p "$JB_WAVE_DIR" 2> /dev/null
    if ! exec 9> "$JB_WAVE_DIR/$WAVE.lock"; then
        echo "$WAVE: cannot write $JB_WAVE_DIR" >&2
        alert_post "[$host] $WAVE could not start: $JB_WAVE_DIR is not writable" || :
        exit 1
    fi
    if [ "${2:-}" = resume ]; then
        report_dead_waves "$WAVE"
    else
        report_dead_waves
    fi
    if ! flock -n 9; then
        other="$(_field "$JB_WAVE_DIR/$WAVE.state" stage)"
        echo "$WAVE: another copy is still running (stage ${other:-none}); not starting a second one" >&2
        alert_post "[$host] $WAVE did not start: another copy is still running at stage ${other:-none}" || :
        exit 1
    fi
    rm -f "$JB_WAVE_DIR/$WAVE.state"
    wave_stage ""
    trap _wave_exit EXIT
}

usage_error() {
    # $1 wave, $2 message. Exit 2 for a wrong command line; that is not an
    # outage, so WAVE_USAGE_ERROR keeps the exit trap from alerting it.
    WAVE_USAGE_ERROR=1
    echo "$1: $2" >&2
    exit 2
}

wave_stage() {
    # $1: the stage about to run ("" = none yet).
    WAVE_STAGE="$1"
    WAVE_SINCE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    wave_state
}

wave_state() {
    # Rewrite the wave's state file: what runs, since when, what failed.
    printf 'stage=%s\nsince=%s\nfailed=%s\n' "$WAVE_STAGE" "$WAVE_SINCE" "$WAVE_FAILED" \
        > "$JB_WAVE_DIR/$WAVE.state.tmp" \
        && mv -f "$JB_WAVE_DIR/$WAVE.state.tmp" "$JB_WAVE_DIR/$WAVE.state" \
        || echo "$WAVE: could not update $JB_WAVE_DIR/$WAVE.state" >&2
}

wave_fail() {
    # $1: a stage that exited non-zero. The wave keeps going after it; the
    # stages that need its output are skipped (wave_failed_any). The first
    # failure posts the alert, because --from that stage reruns every later
    # stage as well. Later failures only log, unless that post failed too.
    WAVE_FAILED="${WAVE_FAILED:+$WAVE_FAILED }$1"
    echo "$WAVE: $1 failed"
    wave_state
    if [ -z "$WAVE_REPORTED" ]; then
        alert_post "[$host] $WAVE failed at stage $1. The wave keeps running; stages that need its output are skipped. Resume when it ends: $(job_command bash "$WAVE.sh" "$1")" &&
            WAVE_REPORTED=1
    fi
    return 0
}

_wave_exit() {
    # Exit trap. A non-zero end that wave_fail did not report means the
    # wave failed to start, was killed or broke between stages. The state
    # file goes away once the report is out; if the post failed it stays,
    # and the next scheduler start reports the wave again.
    status=$?
    trap - EXIT
    keep_state=""
    if [ "$status" -ne 0 ] && [ -z "$WAVE_REPORTED" ] && [ -z "${WAVE_USAGE_ERROR:-}" ]; then
        WAVE_REPORTED=1
        if [ -n "$WAVE_FAILED" ]; then
            message="[$host] $WAVE ended with exit status $status; failed stages: $WAVE_FAILED."
            stage="${WAVE_FAILED%% *}"
        else
            message="[$host] $WAVE stopped with exit status $status at stage ${WAVE_STAGE:-none} and is not running."
            stage="$WAVE_STAGE"
        fi
        alert_post "$message Resume: $(job_command bash "$WAVE.sh" "$stage")" || keep_state=1
    fi
    [ -n "$keep_state" ] || rm -f "$JB_WAVE_DIR/$WAVE.state"
    if [ "$status" -eq 0 ]; then heartbeat; fi
    exit "$status"
}

wave_skip() {
    # $1: a stage skipped because a stage it reads failed or was skipped.
    # The stages that read it in turn are skipped as well.
    WAVE_SKIPPED="${WAVE_SKIPPED:+$WAVE_SKIPPED }$1"
}

wave_failed_any() {
    # True when any of the comma-separated $1 stages failed or was skipped
    # in this wave.
    for req in $(printf '%s' "$1" | tr ',' ' '); do
        for missing in $WAVE_FAILED $WAVE_SKIPPED; do
            [ "$req" = "$missing" ] && return 0
        done
    done
    return 1
}

reap_orphans() {
    # Fail the harvest_runs rows a killed job left 'running' (the job
    # prints one line per row) and alert about them. Never fatal: run from
    # the backend root, where the job module lives.
    if ! out="$(timeout 300 uv run --no-dev python jobs/reap_orphaned_runs.py)"; then
        echo "reaper: could not check for orphaned harvest runs" >&2
        return 0
    fi
    [ -n "$out" ] || return 0
    echo "reaper: marked failed as orphaned:"
    echo "$out"
    # No `read` here: the joined line has no trailing newline, so `read`
    # returns 1, and under the waves' `set -e` that ended the whole wave.
    runs="$(printf '%s\n' "$out" | tr '\n' ';')"
    alert_post "[$host] harvest runs left 'running' by a killed process are now marked failed: $runs" || :
    return 0
}
