"""Admin ops status (GET /admin/ops/status) and the cron next-fire parser.

Covers 2026-11-19 sweep finding 3: wave outcome, next scheduled runs,
backup visibility, and per-source freshness, all without shell access.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from conftest import journal_factory, requires_db
from journal_browser.models import HarvestRun, HarvestState
from journal_browser.routers.admin.cron_next import next_fire

PASSWORD = "test-admin-pw"
THURSDAY_NOON = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


def test_cron_next_daily():
    assert next_fire("30 1 * * *", THURSDAY_NOON) == datetime(2026, 11, 20, 1, 30, tzinfo=UTC)


def test_cron_next_weekly_sunday_both_spellings():
    for dow in ("0", "7"):
        assert next_fire(f"0 22 * * {dow}", THURSDAY_NOON) == datetime(
            2026, 11, 22, 22, 0, tzinfo=UTC
        )


def test_cron_next_lists_ranges_steps():
    assert next_fire("0 9,18 * * 1-5", THURSDAY_NOON) == datetime(2026, 11, 19, 18, 0, tzinfo=UTC)
    assert next_fire("0 */6 * * *", THURSDAY_NOON) == datetime(2026, 11, 19, 18, 0, tzinfo=UTC)


def test_cron_next_never_matching_returns_none():
    assert next_fire("0 0 30 2 *", THURSDAY_NOON) is None


def test_cron_next_rejects_malformed():
    with pytest.raises(ValueError):
        next_fire("61 * * * *", THURSDAY_NOON)
    with pytest.raises(ValueError):
        next_fire("30 1 * *", THURSDAY_NOON)


@pytest.fixture
async def ops_api(client, db, monkeypatch, tmp_path):
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "settings.yaml"))
    monkeypatch.delenv("JB_SOURCE_WAVE_CRON", raising=False)
    monkeypatch.delenv("JB_REFRESH_WAVE_CRON", raising=False)
    monkeypatch.delenv("JB_BACKUP_CRON", raising=False)
    backups = tmp_path / "backups"
    backups.mkdir()
    import os

    dump = backups / "journalbrowser-20261119-040000.dump"
    dump.write_bytes(b"PGCOP" + b"0" * 1024)
    old = backups / "journalbrowser-20261118-040000.dump"
    old.write_bytes(b"older")
    # Write order alone would make the "older" archive newest by mtime.
    os.utime(old, (1_700_000_000, 1_700_000_000))
    monkeypatch.setenv("JB_BACKUP_DIR", str(backups))
    db.add(journal_factory("0000-0000"))
    await db.flush()
    wave_run = HarvestRun(
        source="harvest_stats", entity_type="works", status="failed", config_fingerprint="t"
    )
    db.add(wave_run)
    db.add(
        HarvestRun(
            source="embed_journals",
            entity_type="embedding",
            status="completed",
            config_fingerprint="t",
        )
    )
    # An old global run must stay out of the latest wave cluster.
    db.add(
        HarvestRun(
            source="pure",
            entity_type="works",
            status="completed",
            config_fingerprint="t",
            started_at=datetime.now(UTC) - timedelta(days=3),
        )
    )
    await db.flush()
    db.add(
        HarvestState(
            source="harvest_stats",
            entity_type="works",
            filter_set="default",
            status="failed",
            last_run_id=wave_run.id,
        )
    )
    await db.commit()
    from journal_browser.config import reset_settings_cache

    reset_settings_cache()
    yield client
    reset_settings_cache()


async def _login(client: AsyncClient) -> dict[str, str]:
    r = await client.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


@requires_db
async def test_ops_status_sections(ops_api):
    headers = await _login(ops_api)
    r = await ops_api.get("/api/v1/admin/ops/status", headers=headers)
    assert r.status_code == 200
    body = r.json()

    wave = body["last_wave"]
    assert wave is not None
    stages = {(s["source"], s["entity_type"]) for s in wave["stages"]}
    assert ("harvest_stats", "works") in stages
    assert ("embed_journals", "embedding") in stages
    assert ("pure", "works") not in stages  # old run excluded from the cluster
    assert wave["failed"] == 1 and wave["running"] == 0

    schedules = {s["name"]: s for s in body["schedules"]}
    assert set(schedules) == {"refresh_wave", "source_wave", "backup"}
    assert schedules["refresh_wave"]["cron"] == "30 1 * * *"
    assert schedules["refresh_wave"]["from_env"] is False
    assert schedules["source_wave"]["cron"] == "0 22 * * 0"  # the weekly default
    assert schedules["source_wave"]["error"] is None
    now = datetime.now(UTC)
    for entry in schedules.values():
        assert entry["next_run_utc"] is not None
        assert datetime.fromisoformat(entry["next_run_utc"]) > now

    backup = body["backup"]
    assert backup["available"] is True
    assert backup["file"] == "journalbrowser-20261119-040000.dump"
    assert backup["size_bytes"] > 0
    assert backup["modified_at"] is not None

    assert any(t["source"] == "harvest_stats" for t in body["freshness"])
    assert "journals" in body["tables"]


@requires_db
async def test_ops_status_backup_unavailable(ops_api, monkeypatch):
    monkeypatch.setenv("JB_BACKUP_DIR", "/nonexistent/backups")
    headers = await _login(ops_api)
    r = await ops_api.get("/api/v1/admin/ops/status", headers=headers)
    assert r.status_code == 200
    backup = r.json()["backup"]
    assert backup["available"] is False
    assert backup["file"] is None
    assert backup["detail"]


@requires_db
async def test_ops_status_requires_admin(ops_api):
    r = await ops_api.get("/api/v1/admin/ops/status")
    assert r.status_code == 401
