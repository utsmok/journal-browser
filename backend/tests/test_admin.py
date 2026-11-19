"""Admin surface outcomes: the auth gate and login rate limit, the
settings overlay round trip (including stale overlay keys and a window
edit that must serve downstream immediately), the docs API, feedback
intake + triage, and the admin summary counters.

Replaces test_admin.py, test_admin_login_ratelimit.py,
test_settings_overlay.py, test_docs.py and test_feedback.py (scenario map:
.audit/2026-11-19-sweep/p2-tests-plan.md).
"""

import hashlib

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
    Institution,
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
