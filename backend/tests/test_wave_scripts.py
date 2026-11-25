"""The wave and backup scripts in backend/scripts: a failed stage does not
stop the wave, the stages that read its output are skipped, and the alert
carries the command that resumes it.

The scripts run unchanged, with a stub uv on PATH that records every job it
is asked to run and fails the jobs a test names. A local HTTP server
receives the alert posts and the heartbeat pings."""

import fcntl
import json
import os
import shutil
import socket
import subprocess
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("flock") is None or shutil.which("curl") is None,
    reason="the scripts need flock (util-linux) and curl",
)

BACKEND = Path(__file__).resolve().parent.parent
HOST = os.environ.get("JB_ALERT_HOST") or socket.gethostname()

# The waves call `uv run --no-dev python <script> <args...>`: everything
# after `python` is the command, logged as one line. The institution query
# (-c) lists the hosted institutions; the commands named in FAIL_JOBS exit
# 1; REAPED is what the orphan reaper reports.
STUB_UV = """\
#!/bin/sh
shift 3
echo "$*" >> "$UV_LOG"
case "$1" in
    -c) printf '%s\\n' "$CODES" ;;
    jobs/reap_orphaned_runs.py) [ -z "${REAPED:-}" ] || echo "$REAPED" ;;
esac
case " $FAIL_JOBS " in *" ${*:-none} "*) exit 1 ;; esac
"""

# pg_dump for backup.sh: writes the archive that --file names, or fails.
STUB_PG_DUMP = """\
#!/bin/sh
echo "$*" >> "$BACKUP_LOG"
[ -z "${FAIL_DUMP:-}" ] || exit 1
for arg in "$@"; do
    case "$arg" in --file=*) printf 'PGDMPstub' > "${arg#--file=}" ;; esac
done
"""

# pg_restore for backup.sh: --list reads any archive unless FAIL_RESTORE is set.
STUB_PG_RESTORE = """\
#!/bin/sh
echo "$*" >> "$BACKUP_LOG"
[ -z "${FAIL_RESTORE:-}" ] || exit 1
"""


class _Receiver(BaseHTTPRequestHandler):
    """Alert posts and heartbeat pings land in the class lists."""

    posts: ClassVar[list[str]] = []
    gets: ClassVar[list[str]] = []

    def do_POST(self) -> None:
        self.posts.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
        self.send_response(200)
        self.end_headers()

    def do_GET(self) -> None:
        self.gets.append(self.path)
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


@dataclass
class Sandbox:
    root: Path
    env: dict[str, str]
    posts: list[str]
    gets: list[str]

    def fail(self, *jobs: str) -> None:
        self.env["FAIL_JOBS"] = " ".join(jobs)

    @property
    def jobs(self) -> list[str]:
        """Every job the wave ran, as `<script> <args>`, the reaper left out."""
        log = self.root / "uv.log"
        lines = log.read_text().splitlines() if log.exists() else []
        return [
            line.strip()
            for line in lines
            if line.startswith("jobs/") and not line.startswith("jobs/reap_")
        ]

    def alerts(self) -> list[str]:
        return [json.loads(post)["text"] for post in self.posts]

    def leave_state(self, wave: str, stage: str, failed: str = "") -> None:
        """What a wave killed mid-run leaves in landing/waves."""
        waves = self.root / "landing" / "waves"
        waves.mkdir(parents=True, exist_ok=True)
        (waves / f"{wave}.state").write_text(
            f"stage={stage}\nsince=2026-11-22T23:34:49Z\nfailed={failed}\n"
        )

    def run(self, script: str, *args: str) -> subprocess.CompletedProcess[str]:
        shell = "sh" if script == "backup.sh" else "bash"
        return subprocess.run(
            [shell, str(BACKEND / "scripts" / script), *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )


@pytest.fixture
def sandbox(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {"uv": STUB_UV, "pg_dump": STUB_PG_DUMP, "pg_restore": STUB_PG_RESTORE}
    for name, body in stubs.items():
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Receiver)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "UV_LOG": str(tmp_path / "uv.log"),
        "BACKUP_LOG": str(tmp_path / "backup.log"),
        "FAIL_JOBS": "",
        "CODES": "ut",
        "JB_LANDING_DIR": str(tmp_path / "landing"),
        "JB_ALERT_WEBHOOK_URL": f"{base}/alert",
        "JB_HEARTBEAT_URL": f"{base}/ping",
        "JB_DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/x",
        "JB_BACKUP_DIR": str(tmp_path / "backups"),
    }
    for key in ("JB_ALERT_HOST", "REAPED", "FAIL_DUMP", "FAIL_RESTORE"):
        env.pop(key, None)
    _Receiver.posts, _Receiver.gets = [], []
    yield Sandbox(tmp_path, env, _Receiver.posts, _Receiver.gets)
    server.shutdown()
    server.server_close()


def test_failed_stage_keeps_the_wave_going_and_names_the_resume_command(sandbox):
    sandbox.fail("jobs/ingest_jct.py", "jobs/harvest_doaj.py")
    sandbox.env["CODES"] = "ut"

    r = sandbox.run("source_wave.sh")

    assert r.returncode == 1
    # Independent stages still ran. The deal chain that reads JCT, the
    # OpenAIRE match that needs its ISSN-Ls and the stats that read the
    # match were skipped, the last two because a skipped stage counts as
    # missing for the stages that read it.
    assert "jobs/harvest_pure.py --institution ut" in sandbox.jobs
    assert "jobs/harvest_openaire.py --institution ut" not in sandbox.jobs
    assert "jobs/harvest_stats.py --institution ut" not in sandbox.jobs
    assert "failed stages: deals-jct doaj" in r.stdout
    assert "resume with: bash scripts/source_wave.sh --from deals-jct" in r.stdout
    # One alert, and --from the first failed stage reruns every later one.
    assert sandbox.alerts() == [
        f"[{HOST}] source_wave failed at stage deals-jct. The wave keeps running; "
        "stages that need its output are skipped. Resume when it ends: "
        "bash scripts/source_wave.sh --from deals-jct"
    ]
    assert sandbox.gets == []
    assert not (sandbox.root / "landing" / "waves" / "source_wave.state").exists()


def test_failed_institution_stage_skips_only_its_own_dependents(sandbox):
    sandbox.fail("jobs/harvest_pure.py --institution rug")
    sandbox.env["CODES"] = "ut\nrug"

    r = sandbox.run("source_wave.sh")

    assert r.returncode == 1
    assert "jobs/enrich_works.py --institution rug" not in sandbox.jobs
    assert "jobs/harvest_stats.py --institution rug" not in sandbox.jobs
    assert "jobs/enrich_works.py --institution ut" in sandbox.jobs
    assert "jobs/harvest_stats.py --institution ut" in sandbox.jobs


def test_refresh_wave_skips_only_the_stages_that_read_the_failed_one(sandbox):
    sandbox.fail("jobs/build_openalex_works.py")

    r = sandbox.run("refresh_wave.sh")

    assert r.returncode == 1
    for skipped in ("backfill_parts", "resolve_author_ids", "ingest_authors", "harvest_oa_colors"):
        assert f"jobs/{skipped}.py" not in sandbox.jobs
    assert "jobs/harvest_work_funders.py" in sandbox.jobs
    assert "jobs/embed_journals.py" in sandbox.jobs
    assert "resume with: bash scripts/refresh_wave.sh --from build_openalex_works" in r.stdout


def test_from_runs_the_named_stage_and_every_later_one(sandbox):
    r = sandbox.run("source_wave.sh", "--from", "enrich:ut")

    assert r.returncode == 0, r.stderr
    assert sandbox.jobs[0] == "jobs/enrich_works.py --institution ut"
    assert not any("harvest_pure" in job for job in sandbox.jobs)
    assert "jobs/harvest_stats.py --institution ut" in sandbox.jobs
    assert sandbox.posts == []
    assert sandbox.gets == ["/ping"]


def test_unknown_from_stage_exits_2_without_running_or_alerting(sandbox):
    r = sandbox.run("source_wave.sh", "--from", "nope")

    assert r.returncode == 2
    assert "unknown --from stage 'nope'" in r.stderr
    assert sandbox.jobs == []
    assert sandbox.posts == []


@pytest.mark.parametrize(("failed", "resume_from"), [("", "enrich:ut"), ("doaj enrich:ut", "doaj")])
def test_killed_wave_is_reported_once_at_the_next_wave_start(sandbox, failed, resume_from):
    sandbox.leave_state("source_wave", "enrich:ut", failed)

    r = sandbox.run("refresh_wave.sh")

    assert r.returncode == 0, r.stderr
    stage = f"Failed stages: {failed}. " if failed else ""
    assert sandbox.alerts() == [
        f"[{HOST}] source_wave was stopped before it finished and is not running. "
        f"{stage}Last stage: enrich:ut (since 2026-11-22T23:34:49Z). "
        f"Resume: bash scripts/source_wave.sh --from {resume_from}"
    ]
    # Reported once: the leftover went with the delivered alert.
    assert not (sandbox.root / "landing" / "waves" / "source_wave.state").exists()


def test_wave_that_still_runs_is_neither_restarted_nor_reported(sandbox):
    sandbox.leave_state("source_wave", "enrich:ut")
    lock = sandbox.root / "landing" / "waves" / "source_wave.lock"
    lock.write_text("")
    with lock.open() as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        r = sandbox.run("source_wave.sh")

    assert r.returncode == 1
    assert "another copy is still running (stage enrich:ut)" in r.stderr
    assert sandbox.jobs == []
    assert sandbox.alerts() == [
        f"[{HOST}] source_wave did not start: another copy is still running at stage enrich:ut"
    ]
    assert lock.with_suffix(".state").exists()


def test_orphaned_harvest_runs_are_alerted(sandbox):
    sandbox.env["REAPED"] = "run 408 openalex/work institution=1 started 2026-11-22T23:34:49Z"

    r = subprocess.run(
        ["sh", "-c", ". scripts/lib.sh; reap_orphans"],
        cwd=BACKEND,
        env=sandbox.env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert r.returncode == 0, r.stderr
    assert sandbox.alerts() == [
        f"[{HOST}] harvest runs left 'running' by a killed process are now marked failed: "
        "run 408 openalex/work institution=1 started 2026-11-22T23:34:49Z;"
    ]


def test_wave_runs_on_after_reporting_orphaned_runs(sandbox):
    # The waves run under `set -euo pipefail`; reporting an orphan must not
    # end the wave (2026-11-25: it did, right after a database crash).
    sandbox.env["REAPED"] = (
        "run 423 openalex/works_stats institution=1 started 2026-11-25T13:09:42Z"
    )

    r = sandbox.run("refresh_wave.sh")

    assert r.returncode == 0, r.stdout + r.stderr
    assert "jobs/embed_journals.py" in sandbox.jobs
    assert sandbox.alerts() == [
        f"[{HOST}] harvest runs left 'running' by a killed process are now marked failed: "
        "run 423 openalex/works_stats institution=1 started 2026-11-25T13:09:42Z;"
    ]


def test_backup_dumps_with_zstd_checks_the_archive_and_pings(sandbox):
    r = sandbox.run("backup.sh")

    assert r.returncode == 0, r.stderr
    log = (sandbox.root / "backup.log").read_text().splitlines()
    assert "--format=custom" in log[0] and "--compress=zstd:9" in log[0]
    assert "--list" in log[1]
    archives = list((sandbox.root / "backups").glob("journalbrowser-*.dump"))
    assert [archive.read_bytes() for archive in archives] == [b"PGDMPstub"]
    assert sandbox.posts == []
    assert sandbox.gets == ["/ping"]


@pytest.mark.parametrize(
    ("failure", "reason"),
    [("FAIL_DUMP", "pg_dump exited 1"), ("FAIL_RESTORE", "pg_restore --list cannot read")],
)
def test_backup_failure_alerts_with_the_resume_command_and_keeps_no_archive(
    sandbox, failure, reason
):
    sandbox.env[failure] = "1"

    r = sandbox.run("backup.sh")

    assert r.returncode == 1
    alert = sandbox.alerts()[0]
    assert f"backup failed: {reason}" in alert
    assert alert.endswith("Resume: sh scripts/backup.sh")
    assert list((sandbox.root / "backups").iterdir()) == []
    assert sandbox.gets == []
