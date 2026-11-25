"""Admin surface outcomes: the auth gate and login rate limit, the
settings overlay round trip (including stale overlay keys and a window
edit that must serve downstream immediately), the docs API, feedback
intake + triage, and the admin summary counters. Also folded from the
2026-11-19 regression files: ops status, the cron next-fire parser,
onboarding settings parsing, window validation + reactivation rebuild,
write audit rows, and the unknown-ISSN deal guard.
"""

import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.config import get_settings, reset_settings_cache
from journal_browser.harvest.denorm import refresh_institution_stats
from journal_browser.harvest.institution_stats import write_pure_canon_stats
from journal_browser.models import (
    AuthorIdentity,
    Deal,
    DealJournal,
    Feedback,
    HarvestRun,
    HarvestState,
    Institution,
    IssnMap,
    JournalFlags,
    Publisher,
    StatusChangeLog,
    Work,
    WorkIdentity,
)
from journal_browser.routers.admin.auth import (
    FAIL_WINDOW_SECONDS,
    MAX_FAILURES_GLOBAL,
    MAX_FAILURES_PER_KEY,
    LoginRateLimiter,
    reset_login_limiter,
)
from journal_browser.routers.admin.cron_next import next_fire
from journal_browser.services.detail_enrichment import list_works

PASSWORD = "test-admin-pw"

DUMP = {
    "url": "/ut/journals?q=water",
    "queries": [{"key": ["journals", "ut", {"q": "water"}], "data": {"items": []}}],
}


@pytest.fixture
async def admin_api(client, db, monkeypatch, tmp_path):
    """Admin password env, a hermetic settings overlay yaml and docs tree,
    plus the fixed backdrop every admin read expects: one hosted
    institution, one flagged deal, one completed harvest run."""
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "settings.yaml"))
    docs_dir = tmp_path / "docs" / "data-pipeline"
    docs_dir.mkdir(parents=True)
    (docs_dir / "OVERVIEW.md").write_text(
        "# Overview\n\nIntro paragraph.\n\n```python\nx = 1\n\ny = 2\n```\n", encoding="utf-8"
    )
    (docs_dir / "aaa-source.md").write_text("# A Source\n\nSource text.\n", encoding="utf-8")
    monkeypatch.setenv("JB_DOCS_DIR", str(tmp_path / "docs"))
    reset_settings_cache()
    reset_login_limiter()

    pub = Publisher(name="Emerald Publishing group")
    db.add(Institution(name="University of Twente", code="ut", active=True))
    db.add(pub)
    db.add(journal_factory("0000-0000", publisher_name="Emerald"))
    await db.flush()
    deal = Deal(
        publisher_id=pub.id,
        status="current",
        corresponding_authors_only=False,
        provenance=[],
        needs_curation=True,
        needs_curation_reason="duplicate sheet",
    )
    db.add(deal)
    await db.flush()
    db.add(DealJournal(deal_id=deal.id, issn="0000-0000", source="jct"))
    db.add(
        HarvestRun(
            source="reconcile",
            entity_type="deal",
            status="completed",
            config_fingerprint="x",
            stats={"matched": 1},
        )
    )
    await db.commit()
    yield client
    reset_settings_cache()
    reset_login_limiter()


async def _login(client: AsyncClient) -> dict[str, str]:
    r = await client.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


@requires_db
async def test_admin_auth_gate(admin_api, monkeypatch):
    # Without JB_ADMIN_PASSWORD the panel is disabled: every admin route
    # answers 403, login included.
    monkeypatch.delenv("JB_ADMIN_PASSWORD")
    reset_settings_cache()
    assert (await admin_api.get("/api/v1/admin/runs")).status_code == 403
    assert (
        await admin_api.post("/api/v1/admin/login", json={"password": PASSWORD})
    ).status_code == 403

    # With the password set, admin routes demand a bearer token from /login.
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    reset_settings_cache()
    assert (await admin_api.get("/api/v1/admin/runs")).status_code == 401
    bogus = {"Authorization": "Bearer not-a-token"}
    assert (await admin_api.get("/api/v1/admin/runs", headers=bogus)).status_code == 401
    r = await admin_api.post("/api/v1/admin/login", json={"password": "wrong"})
    assert r.status_code == 403


@requires_db
async def test_login_lockout_retry_after_and_per_key(admin_api):
    for _ in range(MAX_FAILURES_PER_KEY):
        r = await admin_api.post("/api/v1/admin/login", json={"password": "wrong"})
        assert r.status_code == 403
    # Locked out: even the correct password is refused without a check, and
    # the wait is bounded by the failure window.
    r = await admin_api.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert r.status_code == 429
    assert 1 <= int(r.headers["Retry-After"]) <= FAIL_WINDOW_SECONDS
    # A different forwarded client still reaches the password check.
    r = await admin_api.post(
        "/api/v1/admin/login", json={"password": "wrong"}, headers={"X-Forwarded-For": "10.1.1.2"}
    )
    assert r.status_code == 403


@requires_db
async def test_login_success_does_not_count(admin_api):
    for _ in range(MAX_FAILURES_PER_KEY - 1):
        assert (
            await admin_api.post("/api/v1/admin/login", json={"password": "wrong"})
        ).status_code == 403
    ok = await admin_api.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert ok.status_code == 200
    # The success consumed nothing: one more failure is still allowed, and
    # only the failure after that trips the lockout.
    assert (
        await admin_api.post("/api/v1/admin/login", json={"password": "wrong"})
    ).status_code == 403
    assert (
        await admin_api.post("/api/v1/admin/login", json={"password": PASSWORD})
    ).status_code == 429


def test_login_rate_limiter_windows():
    t = 0.0
    lim = LoginRateLimiter(clock=lambda: t)
    for _ in range(MAX_FAILURES_PER_KEY):
        lim.record_failure("k")
    assert lim.retry_after("k") == FAIL_WINDOW_SECONDS
    # The wait is ceil-rounded: half a second before expiry costs a full one.
    t = FAIL_WINDOW_SECONDS - 0.5
    assert lim.retry_after("k") == 1
    # Sliding window: aged-out failures unblock the key itself ...
    t = FAIL_WINDOW_SECONDS + 0.5
    assert lim.retry_after("k") is None
    # ... while the global cap blocks keys with no failures of their own,
    # until the global failures age out too.
    for i in range(MAX_FAILURES_GLOBAL):
        lim.record_failure(f"key{i}")
    assert lim.retry_after("fresh") == FAIL_WINDOW_SECONDS
    t += FAIL_WINDOW_SECONDS + 1
    assert lim.retry_after("fresh") is None


@requires_db
async def test_settings_put_round_trip(admin_api, tmp_path):
    headers = await _login(admin_api)
    r = await admin_api.put(
        "/api/v1/admin/settings",
        headers=headers,
        json={
            "values": {
                "bootstrap": "always",
                "ignored_issns": ["1234-5678"],
                "pure_oai_min_spacing": 2.5,
            }
        },
    )
    assert r.status_code == 200
    assert r.json()["values"]["bootstrap"] == "always"

    # GET serves the same edit, the overlay file holds it, and
    # get_settings() sees it live.
    r = await admin_api.get("/api/v1/admin/settings", headers=headers)
    assert r.json()["values"]["bootstrap"] == "always"
    text = (tmp_path / "settings.yaml").read_text()
    assert "bootstrap: always" in text
    assert "1234-5678" in text
    assert get_settings().bootstrap == "always"
    assert get_settings().ignored_issns == ["1234-5678"]

    # The masked secret keeps the current value and never lands in the file.
    r = await admin_api.put(
        "/api/v1/admin/settings", headers=headers, json={"values": {"admin_password": "********"}}
    )
    assert r.status_code == 200
    assert "admin_password" not in (tmp_path / "settings.yaml").read_text()
    assert get_settings().admin_password == PASSWORD

    # Unknown key, wrong type, institution-section key: 400 each.
    for bad in ({"nope": 1}, {"bootstrap": True}, {"institution_name": "X"}):
        r = await admin_api.put("/api/v1/admin/settings", headers=headers, json={"values": bad})
        assert r.status_code == 400

    # A newly written secret is live immediately (login derives from it).
    r = await admin_api.put(
        "/api/v1/admin/settings", headers=headers, json={"values": {"admin_password": "pw2"}}
    )
    assert r.status_code == 200
    r = await admin_api.post("/api/v1/admin/login", json={"password": "pw2"})
    assert r.status_code == 200


def test_stale_overlay_key_is_ignored(monkeypatch, tmp_path):
    """A settings.yaml key that left Settings must not break get_settings();
    overlays reload live on mtime, so an unknown key is ignored, never
    raised on."""
    overlay = tmp_path / "settings.yaml"
    overlay.write_text("enable_jisc: false\ncontact_email: overlay@example.com\n", encoding="utf-8")
    monkeypatch.setenv("JB_SETTINGS_YAML", str(overlay))
    monkeypatch.setenv("JB_CONTACT_EMAIL", "env@example.com")
    reset_settings_cache()
    try:
        s = get_settings()
        assert s.contact_email == "overlay@example.com"  # overlay wins over env
        assert "enable_jisc" not in type(s).model_fields
    finally:
        reset_settings_cache()


@requires_db
async def test_window_edit_stores_open_null_and_serves_downstream(admin_api, db):
    """data_window_end 0 (the compose/.env default) stores NULL, and a
    window edit rebuilds the window-bounded card counts in the same request
    (2026-11-08: the PUT used to leave the card stale until the stats job)."""
    inst = (await db.execute(select(Institution).where(Institution.code == "ut"))).scalar_one()
    inst.data_window_start = 2021
    run = HarvestRun(
        source="pure",
        entity_type="works",
        status="completed",
        institution_id=inst.id,
        config_fingerprint="t",
    )
    db.add(run)
    await db.flush()
    db.add_all(
        [
            Work(
                institution_id=inst.id,
                pure_uuid="ut-pre",
                title="Pre window",
                norm_title="pre window",
                year=2020,
                work_type="article",
                journal_issn_l="0000-0000",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            Work(
                institution_id=inst.id,
                pure_uuid="ut-in",
                title="In window",
                norm_title="in window",
                year=2021,
                work_type="article",
                journal_issn_l="0000-0000",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
        ]
    )
    await write_pure_canon_stats(db, inst)
    await refresh_institution_stats(db, inst)
    await db.commit()
    # The card starts on the old window: the 2020 work is excluded.
    flags = await db.get(JournalFlags, {"institution_id": inst.id, "issn_l": "0000-0000"})
    assert flags is not None and flags.works_count == 1

    headers = await _login(admin_api)
    r = await admin_api.put(
        "/api/v1/admin/institutions/ut", headers=headers, json={"data_window_end": 0}
    )
    assert r.status_code == 200
    assert r.json()["data_window_end"] is None
    r = await admin_api.put(
        "/api/v1/admin/institutions/ut", headers=headers, json={"data_window_start": 2020}
    )
    assert r.status_code == 200

    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as session:
        fresh = (
            await session.execute(select(Institution).where(Institution.code == "ut"))
        ).scalar_one()
        page = await list_works(session, "0000-0000", fresh, page=1, page_size=50)
        flags = await session.get(JournalFlags, {"institution_id": fresh.id, "issn_l": "0000-0000"})
    assert flags is not None and flags.works_count == 2
    assert page["total"] == 2


@requires_db
async def test_docs_list_detail_edit(admin_api):
    r = await admin_api.get("/api/v1/docs")
    assert r.status_code == 200
    docs = r.json()
    assert [d["slug"] for d in docs] == ["overview", "aaa-source"]
    assert docs[0]["group"] == "overview" and docs[0]["order"] == 0
    assert all(d["edits"] == 0 for d in docs)

    r = await admin_api.get("/api/v1/docs/OVERVIEW")
    assert r.status_code == 200
    detail = r.json()
    assert [b["key"] for b in detail["blocks"]] == [
        f"b{i:03d}" for i in range(len(detail["blocks"]))
    ]
    block = next(b for b in detail["blocks"] if b["type"] == "paragraph")
    assert (await admin_api.get("/api/v1/docs/no-such-doc")).status_code == 404

    headers = await _login(admin_api)
    edit = {
        "block_key": block["key"],
        "original_hash": hashlib.sha256(block["text"].encode()).hexdigest(),
        "replacement": "A replacement paragraph.",
    }
    r = await admin_api.put("/api/v1/admin/docs/overview/edits", headers=headers, json=edit)
    assert r.status_code == 200
    assert r.json() == {"slug": "overview", "block_key": block["key"], "edited": True}

    # The edit is served at read time; the listing counts it.
    edited = (await admin_api.get("/api/v1/docs/OVERVIEW")).json()
    now = next(b for b in edited["blocks"] if b["key"] == block["key"])
    assert now["text"] == "A replacement paragraph."
    assert now["edited"] is True
    listing = (await admin_api.get("/api/v1/docs")).json()
    assert next(d for d in listing if d["slug"] == "overview")["edits"] == 1

    # Empty replacement and unknown slugs are rejected before any write.
    r = await admin_api.put(
        "/api/v1/admin/docs/overview/edits", headers=headers, json={**edit, "replacement": "   "}
    )
    assert r.status_code == 422
    r = await admin_api.put("/api/v1/admin/docs/no-such-doc/edits", headers=headers, json=edit)
    assert r.status_code == 404

    # Deleting the override restores the source text.
    r = await admin_api.delete(f"/api/v1/admin/docs/overview/edits/{block['key']}", headers=headers)
    assert r.status_code == 204
    restored = (await admin_api.get("/api/v1/docs/OVERVIEW")).json()
    back = next(b for b in restored["blocks"] if b["key"] == block["key"])
    assert back["text"] == block["text"]
    assert back["edited"] is False


@requires_db
async def test_feedback_intake_and_triage(admin_api, db):
    r = await admin_api.post(
        "/api/v1/feedback",
        json={
            "title": "Wrong APC price",
            "description": "The list price for ISSN 1234-5678 looks wrong.",
            "category": "bug",
            "page_url": "/ut/journals/1234-5678",
            "page_data": DUMP,
        },
    )
    assert r.status_code == 201
    assert r.json()["status"] == "todo"

    # Intake is public, triage is not; bad category and an oversized page
    # dump are rejected before storage.
    assert (await admin_api.get("/api/v1/admin/feedback")).status_code == 401
    r = await admin_api.post(
        "/api/v1/feedback", json={"title": "x", "description": "y", "category": "not-a-thing"}
    )
    assert r.status_code == 422
    r = await admin_api.post(
        "/api/v1/feedback",
        json={"title": "x", "description": "y", "page_data": {"blob": "a" * 1_100_000}},
    )
    assert r.status_code == 413

    headers = await _login(admin_api)
    items = (await admin_api.get("/api/v1/admin/feedback", headers=headers)).json()
    assert len(items) == 1
    assert items[0]["page_data"] == DUMP
    assert items[0]["page_url"] == "/ut/journals/1234-5678"
    fid = items[0]["id"]

    # A status flip is audited once; a notes-only patch writes no audit row.
    r = await admin_api.patch(
        f"/api/v1/admin/feedback/{fid}",
        headers=headers,
        json={
            "status": "in_progress",
            "priority": "high",
            "resolution_notes": "looking",
            "changed_by": "sam",
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "in_progress"
    r = await admin_api.patch(
        f"/api/v1/admin/feedback/{fid}", headers=headers, json={"resolution_notes": "still looking"}
    )
    assert r.status_code == 200
    changes = (
        (
            await db.execute(
                select(StatusChangeLog).where(StatusChangeLog.table_name == "feedback_items")
            )
        )
        .scalars()
        .all()
    )
    # The priority flip and the status flip each land one audit row, in
    # that order; the notes-only patch writes none.
    assert [(c.old_value, c.new_value) for c in changes] == [
        ("normal", "high"),
        ("todo", "in_progress"),
    ]
    assert changes[0].changed_by == "sam"

    r = await admin_api.get(
        "/api/v1/admin/feedback", headers=headers, params={"status": "in_progress"}
    )
    assert [i["id"] for i in r.json()] == [fid]
    r = await admin_api.patch(
        f"/api/v1/admin/feedback/{fid}", headers=headers, json={"status": "nope"}
    )
    assert r.status_code == 422
    r = await admin_api.get("/api/v1/admin/feedback", headers=headers, params={"limit": -1})
    assert r.status_code == 422

    r = await admin_api.delete(f"/api/v1/admin/feedback/{fid}", headers=headers)
    assert r.status_code == 204
    assert (await admin_api.get("/api/v1/admin/feedback", headers=headers)).json() == []
    await db.rollback()
    deleted = (
        (
            await db.execute(
                select(StatusChangeLog).where(
                    StatusChangeLog.table_name == "feedback_items",
                    StatusChangeLog.field == "deleted",
                )
            )
        )
        .scalars()
        .first()
    )
    assert deleted is not None and deleted.new_value == "deleted"
    assert "Wrong APC price" in (deleted.note or "")


@requires_db
async def test_admin_summary_counts(admin_api, db):
    ut = (await db.execute(select(Institution).where(Institution.code == "ut"))).scalar_one()
    db.add_all(
        [
            # Global failure inside the 24h window ...
            HarvestRun(
                source="openaccess_nl",
                entity_type="deal",
                status="failed",
                config_fingerprint="x",
                stats={"error": "boom"},
            ),
            # ... an institution-scoped failure ...
            HarvestRun(
                source="pure",
                entity_type="works",
                status="failed",
                institution_id=ut.id,
                config_fingerprint="x",
            ),
            Feedback(title="t", description="d", category="bug"),
            AuthorIdentity(
                institution_id=ut.id,
                author_pure_uuid="p-sum",
                source="openalex",
                external_id="a-sum",
                status="candidate",
            ),
        ]
    )
    await db.flush()
    run_id = (
        await db.execute(select(HarvestRun.id).where(HarvestRun.source == "reconcile").limit(1))
    ).scalar_one()
    db.add(
        Work(
            institution_id=ut.id,
            pure_uuid="w-sum",
            title="Summary work",
            norm_title="summary work",
            year=2025,
            first_seen_run=run_id,
            last_seen_run=run_id,
        )
    )
    db.add(
        WorkIdentity(
            institution_id=ut.id,
            source="openalex",
            source_pk="doi:10.1/sum",
            work_id="w-sum",
            matched_by="doi",
            status="candidate",
        )
    )
    db.add(
        WorkIdentity(
            institution_id=ut.id,
            source="openalex",
            source_pk="doi:10.1/miss",
            work_id="w-sum",
            matched_by="trgm:0.7",
            status="missing",
        )
    )
    await db.flush()
    # Inserted last: becomes last_run globally.
    db.add(
        HarvestRun(source="openalex", entity_type="work", status="running", config_fingerprint="x")
    )
    await db.commit()

    headers = await _login(admin_api)
    body = (await admin_api.get("/api/v1/admin/summary", headers=headers)).json()
    assert body["failed_runs_24h"] == 2
    assert body["running_runs"] == 1
    assert body["flagged_deals"] == 1
    assert body["open_feedback"] == 1
    assert body["author_identity_candidates"] == 1
    assert body["work_identity_candidates"] == 1
    assert body["work_identity_missing"] == 1
    assert body["last_run"]["source"] == "openalex"
    assert body["last_run"]["status"] == "running"

    scoped = (
        await admin_api.get("/api/v1/admin/summary", params={"institution": "ut"}, headers=headers)
    ).json()
    assert scoped["failed_runs_24h"] == 1
    assert scoped["running_runs"] == 0
    assert scoped["last_run"]["institution_code"] == "ut"
    assert scoped["last_run"]["status"] == "failed"
    # Flagged deals stay instance-global under a scope.
    assert scoped["flagged_deals"] == 1

    r = await admin_api.get(
        "/api/v1/admin/summary", params={"institution": "nope"}, headers=headers
    )
    assert r.status_code == 404


# ── Cron next-fire parser (folded from test_admin2_ops.py) ────────────────


def test_cron_next_parser():
    noon = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)  # a Thursday
    assert next_fire("30 1 * * *", noon) == datetime(2026, 11, 20, 1, 30, tzinfo=UTC)
    for dow in ("0", "7"):
        assert next_fire(f"0 22 * * {dow}", noon) == datetime(2026, 11, 22, 22, 0, tzinfo=UTC)
    assert next_fire("0 9,18 * * 1-5", noon) == datetime(2026, 11, 19, 18, 0, tzinfo=UTC)
    assert next_fire("0 */6 * * *", noon) == datetime(2026, 11, 19, 18, 0, tzinfo=UTC)
    assert next_fire("0 0 30 2 *", noon) is None  # Feb 30 never matches
    with pytest.raises(ValueError):
        next_fire("61 * * * *", noon)
    with pytest.raises(ValueError):
        next_fire("30 1 * *", noon)


# ── Ops status endpoint (folded from test_admin2_ops.py) ──────────────────


@pytest.fixture
async def ops_api(client, db, monkeypatch, tmp_path):
    """Admin backdrop plus the ops fixtures: backup archives with mtimes
    that differ from creation order, and a latest wave cluster of
    harvest_stats + embed_journals runs, with an old global run excluded."""
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "settings.yaml"))
    monkeypatch.delenv("JB_SOURCE_WAVE_CRON", raising=False)
    monkeypatch.delenv("JB_REFRESH_WAVE_CRON", raising=False)
    monkeypatch.delenv("JB_BACKUP_CRON", raising=False)
    backups = tmp_path / "backups"
    backups.mkdir()
    dump = backups / "journalbrowser-20261119-040000.dump"
    dump.write_bytes(b"PGCOP" + b"0" * 1024)
    old = backups / "journalbrowser-20261118-040000.dump"
    old.write_bytes(b"older")
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
    reset_settings_cache()
    yield client
    reset_settings_cache()


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

    # None of the registered sources ran in this fixture; the rows
    # themselves are covered by test_freshness.py.
    assert body["sources"] == []
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


# ── Onboarding settings parsing (folded from test_onboarding_settings.py) ─


def _example_overlay(monkeypatch, tmp_path):
    """Hermetic overlay location and clean cache, with the checkout's
    backend/.env (cwd-relative env_file) out of the picture."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "settings.yaml"))
    reset_settings_cache()


def test_empty_env_values_parse_to_defaults(monkeypatch, tmp_path):
    """Compose passes unset JB_* variables through as ""; that must mean
    "use the default", not an empty list / int / bool parse error."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("JB_IGNORED_ISSNS", "")
    monkeypatch.setenv("JB_USAGE_RETENTION_DAYS", "")
    monkeypatch.setenv("JB_ENABLE_USAGE_TRACKING", "")
    s = get_settings()
    assert s.ignored_issns == []
    assert s.usage_retention_days == 90
    assert s.enable_usage_tracking is True
    reset_settings_cache()


def test_null_overlay_keys_use_defaults(monkeypatch, tmp_path):
    """Bare keys (YAML null) keep the defaults and the env fallback: a null
    admin_password must not disable a JB_ADMIN_PASSWORD-set panel."""
    _example_overlay(monkeypatch, tmp_path)
    (tmp_path / "settings.yaml").write_text(
        "admin_password:\njisc_api_key:\ncontact_email:\nut_metadata_dsn: postgresql://x\n",
        encoding="utf-8",
    )
    for var in ("JB_ADMIN_PASSWORD", "JB_CONTACT_EMAIL", "JB_JISC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("JB_ADMIN_PASSWORD", "envpw")
    monkeypatch.setenv("JB_CONTACT_EMAIL", "env@example.com")
    s = get_settings()
    assert s.admin_password == "envpw"
    assert s.contact_email == "env@example.com"
    assert s.jisc_api_key == ""
    assert s.ut_metadata_dsn == "postgresql://x"  # non-null values still win
    reset_settings_cache()


def test_repo_example_yaml_boots(monkeypatch, tmp_path):
    """The shipped settings.yaml.example (what the entrypoint copies on
    first boot) must load without a settings validation error."""
    _example_overlay(monkeypatch, tmp_path)
    example = Path(__file__).resolve().parents[1] / "settings.yaml.example"
    (tmp_path / "settings.yaml").write_bytes(example.read_bytes())
    s = get_settings()
    assert s.institution_code == "ut"
    assert s.data_window_end is None  # example's `0` = open-ended window
    assert s.admin_contact == ""
    reset_settings_cache()


# ── Write-path guarantees (folded from test_admin2_writes.py) ─────────────


@pytest.fixture
async def writes_api(client, db, monkeypatch, tmp_path):
    """Admin login backdrop with a works corpus, so flag materialization
    and window-bounded counts have data: one hosted institution, one work
    in the window, and the stats derived from them."""
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "settings.yaml"))
    reset_settings_cache()
    inst = Institution(name="University of Twente", code="ut", active=True)
    db.add(inst)
    db.add(journal_factory("0000-0000"))
    await db.flush()
    run = HarvestRun(
        source="pure",
        entity_type="works",
        status="completed",
        institution_id=inst.id,
        config_fingerprint="t",
    )
    db.add(run)
    await db.flush()
    db.add(
        Work(
            institution_id=inst.id,
            pure_uuid="ut-in",
            title="In window",
            norm_title="in window",
            year=2021,
            work_type="article",
            journal_issn_l="0000-0000",
            first_seen_run=run.id,
            last_seen_run=run.id,
        )
    )
    await write_pure_canon_stats(db, inst)
    await refresh_institution_stats(db, inst)
    await db.commit()
    yield client
    reset_settings_cache()


async def _inst_audit_rows(db) -> list[StatusChangeLog]:
    rows = (
        (
            await db.execute(
                select(StatusChangeLog)
                .where(StatusChangeLog.table_name == "institutions")
                .order_by(StatusChangeLog.id)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@requires_db
async def test_window_validation_and_clear_audit(writes_api, db):
    headers = await _login(writes_api)
    r = await writes_api.put(
        "/api/v1/admin/institutions/ut",
        headers=headers,
        json={"data_window_start": 2024, "data_window_end": 2020},
    )
    assert r.status_code == 400
    assert "data_window" in r.json()["detail"]

    # A one-sided body is checked against the stored row too.
    r = await writes_api.put(
        "/api/v1/admin/institutions/ut", headers=headers, json={"data_window_end": 2015}
    )
    assert r.status_code == 400

    # Equal ends are a legal one-year window.
    r = await writes_api.put(
        "/api/v1/admin/institutions/ut",
        headers=headers,
        json={"data_window_start": 2020, "data_window_end": 2020},
    )
    assert r.status_code == 200
    assert r.json()["data_window_end"] == 2020

    # Clearing the end stores an open NULL window and audits "(cleared)".
    r = await writes_api.put(
        "/api/v1/admin/institutions/ut", headers=headers, json={"data_window_end": None}
    )
    assert r.status_code == 200
    assert r.json()["data_window_end"] is None
    await db.rollback()
    row = (await _inst_audit_rows(db))[-1]
    assert row.field == "data_window_end" and row.new_value == "(cleared)"
    assert row.row_key == {"code": "ut"}


@requires_db
async def test_reactivate_rematerializes_flags_and_audits(writes_api, db):
    inst = (await db.execute(select(Institution).where(Institution.code == "ut"))).scalar_one()
    iid = inst.id
    flags = await db.get(JournalFlags, {"institution_id": iid, "issn_l": "0000-0000"})
    assert flags is not None and flags.works_count == 1

    headers = await _login(writes_api)
    r = await writes_api.put(
        "/api/v1/admin/institutions/ut", headers=headers, json={"active": False}
    )
    assert r.status_code == 200
    assert r.json()["rematerialized_journals"] is None
    await db.rollback()
    live = (
        (await db.execute(select(JournalFlags).where(JournalFlags.institution_id == iid)))
        .scalars()
        .all()
    )
    assert live == []

    r = await writes_api.put(
        "/api/v1/admin/institutions/ut", headers=headers, json={"active": True}
    )
    assert r.status_code == 200
    assert r.json()["rematerialized_journals"] == 1
    await db.rollback()
    fresh = (
        (await db.execute(select(JournalFlags).where(JournalFlags.institution_id == iid)))
        .scalars()
        .all()
    )
    assert len(fresh) == 1 and fresh[0].works_count == 1

    # Both flips are audited.
    flips = [r for r in await _inst_audit_rows(db) if r.field == "active"]
    assert [(r.old_value, r.new_value) for r in flips] == [("true", "false"), ("false", "true")]

    # A plain field write is audited with its old and new value.
    r = await writes_api.put(
        "/api/v1/admin/institutions/ut", headers=headers, json={"short_name": "UT"}
    )
    assert r.status_code == 200
    await db.rollback()
    row = (await _inst_audit_rows(db))[-1]
    assert (row.field, row.old_value, row.new_value) == ("short_name", None, "UT")


@requires_db
async def test_deal_journal_unknown_issn_rejected(admin_api, db):
    db.add(IssnMap(issn="1111-1111", issn_l="1111-1119", source="test"))
    await db.commit()
    headers = await _login(admin_api)
    deal_id = (await db.execute(select(Deal.id).order_by(Deal.id))).scalars().first()
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/journals",
        headers=headers,
        json={"add": [{"issn": "9999-9999", "journal_name": "P2 Added Journal"}]},
    )
    assert r.status_code == 400
    assert "9999-9999" in r.json()["detail"]
    await db.rollback()
    assert (
        await db.execute(select(DealJournal).where(DealJournal.issn == "9999-9999"))
    ).scalars().first() is None

    # A known ISSN resolves through issn_map to its ISSN-L.
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/journals",
        headers=headers,
        json={"add": [{"issn": "1111-1111"}]},
    )
    assert r.status_code == 200
    added = next(j for j in r.json()["journals"] if j["issn"] == "1111-1111")
    assert added["issn_l"] == "1111-1119"


@requires_db
async def test_settings_writes_audited_and_secret_masked(admin_api, db):
    headers = await _login(admin_api)
    r = await admin_api.put(
        "/api/v1/admin/settings",
        headers=headers,
        json={"values": {"contact_email": "lib@example.edu"}},
    )
    assert r.status_code == 200
    await db.rollback()
    email_rows = list(
        (
            await db.execute(
                select(StatusChangeLog).where(
                    StatusChangeLog.table_name == "settings",
                    StatusChangeLog.field == "contact_email",
                )
            )
        ).scalars()
    )
    assert email_rows and email_rows[0].new_value == "lib@example.edu"

    # A secret write is audited, but only as (masked) on both sides.
    r = await admin_api.put(
        "/api/v1/admin/settings",
        headers=headers,
        json={"values": {"openalex_api_key": "sekret-key-123"}},
    )
    assert r.status_code == 200
    await db.rollback()
    secret_rows = list(
        (
            await db.execute(
                select(StatusChangeLog).where(
                    StatusChangeLog.table_name == "settings",
                    StatusChangeLog.field == "openalex_api_key",
                )
            )
        ).scalars()
    )
    assert len(secret_rows) == 1
    # Nothing was stored in the overlay before, so the old side may be
    # null — either way the secret itself must not appear.
    assert secret_rows[0].old_value in (None, "(masked)")
    assert secret_rows[0].new_value == "(masked)"
    assert "sekret-key-123" not in repr(secret_rows[0])
