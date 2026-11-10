"""Admin panel API: password gate, run listing, flagged deals, settings."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import pair_rows, requires_db
from journal_browser.config import get_settings, reset_settings_cache
from journal_browser.models import (
    Author,
    AuthorIdentity,
    Deal,
    DealJournal,
    Feedback,
    HarvestRun,
    Institution,
    Journal,
    OpenalexWork,
    Publisher,
    SourceRecord,
    StatusChangeLog,
    Work,
    WorkIdentity,
)

PASSWORD = "test-admin-pw"


@pytest.fixture
async def admin_api(client, db_engine, monkeypatch, tmp_path):
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "settings.yaml"))
    reset_settings_cache()
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async with maker() as session:
        home = Institution(name="University of Twente", code="ut", active=True)
        session.add(home)
        await session.flush()
        pub = Publisher(name="Emerald Publishing group")
        session.add(pub)
        await session.flush()
        deal = Deal(
            publisher_id=pub.id,
            status="current",
            corresponding_authors_only=False,
            provenance=[],
            needs_curation=True,
            needs_curation_reason="duplicate sheet",
        )
        session.add(deal)
        await session.flush()
        journal = Journal(issn_l="0000-0000", title="J", publisher_name="Emerald")
        session.add(journal)
        await session.flush()
        session.add(DealJournal(deal_id=deal.id, issn="0000-0000", source="jct"))
        session.add(
            HarvestRun(
                source="reconcile",
                entity_type="deal",
                status="completed",
                config_fingerprint="x",
                stats={"matched": 1},
            )
        )
        await session.commit()
    yield client
    reset_settings_cache()


async def _login(client: AsyncClient) -> dict[str, str]:
    r = await client.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


@requires_db
async def test_gate_rejects_without_password(admin_api):
    r = await admin_api.get("/api/v1/admin/runs")
    assert r.status_code == 401
    r = await admin_api.post("/api/v1/admin/login", json={"password": "wrong"})
    assert r.status_code == 403


@requires_db
async def test_login_and_runs(admin_api):
    r = await admin_api.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert r.status_code == 200
    token = r.json()["token"]
    r = await admin_api.get("/api/v1/admin/runs", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    runs = r.json()
    sources = {run["source"]: run for run in runs}
    assert sources["reconcile"]["stats"]["matched"] == 1


@requires_db
async def test_flagged_and_settings(admin_api):
    token = (await admin_api.post("/api/v1/admin/login", json={"password": PASSWORD})).json()[
        "token"
    ]
    headers = {"Authorization": f"Bearer {token}"}
    flagged = (await admin_api.get("/api/v1/admin/flagged", headers=headers)).json()
    assert len(flagged) == 1
    assert flagged[0]["journals"] == 1
    assert flagged[0]["reason"] == "duplicate sheet"
    settings = (await admin_api.get("/api/v1/admin/settings", headers=headers)).json()
    assert settings["values"]["bootstrap"] in {"auto", "always", "off"}
    assert settings["values"]["admin_password"] == "********"
    assert "institution_name" not in settings["values"]
    assert any(
        f["key"] == "institution_name" and f["section"] == "institution" for f in settings["schema"]
    )


@requires_db
async def test_settings_put_roundtrip_and_masking(admin_api, tmp_path):
    headers = await _login(admin_api)
    yaml_path = tmp_path / "settings.yaml"
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
    # Written atomically to the YAML overlay and live for get_settings().
    text = yaml_path.read_text()
    assert "bootstrap: always" in text
    assert "1234-5678" in text
    assert get_settings().bootstrap == "always"
    assert get_settings().ignored_issns == ["1234-5678"]
    # Masked secret keeps the existing value and never lands in the file.
    r = await admin_api.put(
        "/api/v1/admin/settings", headers=headers, json={"values": {"admin_password": "********"}}
    )
    assert r.status_code == 200
    assert "admin_password" not in yaml_path.read_text()
    assert get_settings().admin_password == PASSWORD
    # Validation: unknown key, wrong type, institution-section key.
    for bad in ({"nope": 1}, {"bootstrap": True}, {"institution_name": "X"}):
        r = await admin_api.put("/api/v1/admin/settings", headers=headers, json={"values": bad})
        assert r.status_code == 400
    # A newly written secret takes effect immediately (the token MAC derives
    # from the live settings).
    r = await admin_api.put(
        "/api/v1/admin/settings", headers=headers, json={"values": {"admin_password": "pw2"}}
    )
    assert r.status_code == 200
    r = await admin_api.post("/api/v1/admin/login", json={"password": "pw2"})
    assert r.status_code == 200


@requires_db
async def test_institutions_get_put(admin_api):
    headers = await _login(admin_api)
    r = await admin_api.get("/api/v1/admin/institutions/ut", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == "ut"
    assert body["name"] == "University of Twente"
    r = await admin_api.get("/api/v1/admin/institutions/zz", headers=headers)
    assert r.status_code == 404
    # Unknown/immutable key rejected before anything is applied.
    r = await admin_api.put(
        "/api/v1/admin/institutions/ut",
        headers=headers,
        json={"data_window_start": 2019, "code": "rug"},
    )
    assert r.status_code == 422
    r = await admin_api.get("/api/v1/admin/institutions/ut", headers=headers)
    assert r.json()["data_window_start"] == 2020
    r = await admin_api.put(
        "/api/v1/admin/institutions/ut",
        headers=headers,
        json={"data_window_start": 2019, "active": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["data_window_start"] == 2019
    assert body["active"] is True
    # Author-search confirmation flag round-trips (default on).
    assert body["require_confirmed_affiliation"] is True
    r = await admin_api.put(
        "/api/v1/admin/institutions/ut",
        headers=headers,
        json={"require_confirmed_affiliation": False},
    )
    assert r.status_code == 200
    assert r.json()["require_confirmed_affiliation"] is False
    for bad in (
        {"data_window_start": "x"},
        {"active": "yes"},
        {"require_confirmed_affiliation": 1},
    ):
        r = await admin_api.put("/api/v1/admin/institutions/ut", headers=headers, json=bad)
        assert r.status_code == 422


def test_get_settings_live_yaml_merge(tmp_path, monkeypatch):
    yaml_path = tmp_path / "settings.yaml"
    monkeypatch.setenv("JB_SETTINGS_YAML", str(yaml_path))
    reset_settings_cache()
    try:
        fallback = get_settings().bootstrap
        # Bare `off` would parse as boolean False (YAML 1.1) and fail
        # validation loudly — hand edits must quote such scalars.
        yaml_path.write_text("bootstrap: 'off'\nignored_issns: ['1111-2222']\n")
        assert get_settings().bootstrap == "off"
        assert get_settings().ignored_issns == ["1111-2222"]
        assert get_settings().database_url  # env fallback untouched
        yaml_path.unlink()
        assert get_settings().bootstrap == fallback
    finally:
        reset_settings_cache()


@requires_db
async def test_feedback_limit_rejects_nonpositive(admin_api):
    headers = await _login(admin_api)
    res = await admin_api.get("/api/v1/admin/feedback", params={"limit": -1}, headers=headers)
    assert res.status_code == 422


@requires_db
async def test_institution_put_rejects_null_nonnullable(admin_api):
    headers = await _login(admin_api)
    for key in ("name", "data_window_start", "data_window_end", "active"):
        r = await admin_api.put("/api/v1/admin/institutions/ut", headers=headers, json={key: None})
        assert r.status_code == 422, key
    # A nullable field still clears on explicit null.
    r = await admin_api.put(
        "/api/v1/admin/institutions/ut", headers=headers, json={"admin_contact": None}
    )
    assert r.status_code == 200
    assert r.json()["admin_contact"] is None


@requires_db
async def test_author_identities_list_and_flip(admin_api, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        inst_id = (await session.execute(select(Institution.id).limit(1))).scalar_one()
        session.add(
            Author(
                institution_id=inst_id,
                pure_uuid="p-review",
                name="Review Me",
                n_works=1,
                confirmed=True,
            )
        )
        session.add(
            AuthorIdentity(
                institution_id=inst_id,
                author_pure_uuid="p-review",
                source="openalex",
                external_id="a-1",
                status="candidate",
                method="initials",
                n_works=2,
                evidence={"conflicts": 1},
            )
        )
        await session.commit()

    headers = await _login(admin_api)
    r = await admin_api.get(
        "/api/v1/admin/author-identities", params={"status": "candidate"}, headers=headers
    )
    assert r.status_code == 200
    rows = r.json()["items"]
    row = next(row for row in rows if row["author_pure_uuid"] == "p-review")
    assert row["author_name"] == "Review Me"
    assert row["institution_code"] == "ut"

    # flip to confirmed
    r = await admin_api.put(
        "/api/v1/admin/author-identities",
        headers=headers,
        json={
            "institution_id": row["institution_id"],
            "author_pure_uuid": "p-review",
            "source": "openalex",
            "external_id": "a-1",
            "status": "confirmed",
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "confirmed"

    # invalid status 422; unknown row 404
    r = await admin_api.put(
        "/api/v1/admin/author-identities",
        headers=headers,
        json={
            "institution_id": row["institution_id"],
            "author_pure_uuid": "p-review",
            "source": "openalex",
            "external_id": "a-1",
            "status": "maybe",
        },
    )
    assert r.status_code == 422
    r = await admin_api.put(
        "/api/v1/admin/author-identities",
        headers=headers,
        json={
            "institution_id": row["institution_id"],
            "author_pure_uuid": "p-missing",
            "source": "openalex",
            "external_id": "a-1",
            "status": "confirmed",
        },
    )
    assert r.status_code == 404


@requires_db
async def test_author_identity_flip_audits_and_skips_noops(admin_api, db_engine):
    """Every actual flip appends one status_changes row; no-ops write none."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        inst_id = (await session.execute(select(Institution.id).limit(1))).scalar_one()
        session.add(
            AuthorIdentity(
                institution_id=inst_id,
                author_pure_uuid="p-audit",
                source="openalex",
                external_id="a-9",
                status="candidate",
                evidence={},
            )
        )
        await session.commit()

    headers = await _login(admin_api)
    body = {
        "institution_id": inst_id,
        "author_pure_uuid": "p-audit",
        "source": "openalex",
        "external_id": "a-9",
        "status": "rejected",
        "changed_by": "sam",
        "note": "namesake, not the same person",
    }
    r = await admin_api.put("/api/v1/admin/author-identities", headers=headers, json=body)
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"

    # Idempotent repeat: 200, same payload, no extra audit row.
    r = await admin_api.put("/api/v1/admin/author-identities", headers=headers, json=body)
    assert r.status_code == 200

    async with maker() as session:
        changes = (
            (
                await session.execute(
                    select(StatusChangeLog).where(StatusChangeLog.table_name == "author_identities")
                )
            )
            .scalars()
            .all()
        )
        assert len(changes) == 1
        assert changes[0].old_value == "candidate"
        assert changes[0].new_value == "rejected"
        assert changes[0].changed_by == "sam"
        assert changes[0].row_key["external_id"] == "a-9"

    listing = (
        await admin_api.get(
            "/api/v1/admin/status-changes",
            params={"table_name": "author_identities"},
            headers=headers,
        )
    ).json()
    assert len(listing) == 1
    assert listing[0]["old_value"] == "candidate" and listing[0]["new_value"] == "rejected"


@requires_db
async def test_work_identities_list_flip_and_audit(admin_api, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        inst_id = (await session.execute(select(Institution.id).limit(1))).scalar_one()
        run_id = (await session.execute(select(HarvestRun.id).limit(1))).scalar_one()
        session.add(
            Work(
                institution_id=inst_id,
                pure_uuid="w-local",
                title="A local work",
                norm_title="a local work",
                year=2025,
                first_seen_run=run_id,
                last_seen_run=run_id,
            )
        )
        session.add(
            WorkIdentity(
                institution_id=inst_id,
                source="openalex",
                source_pk="doi:10.1/xyz",
                work_id="w-local",
                matched_by="doi",
                status="missing",
            )
        )
        await session.commit()

    headers = await _login(admin_api)
    rows = (await admin_api.get("/api/v1/admin/work-identities", headers=headers)).json()["items"]
    assert len(rows) == 1
    assert rows[0]["work_title"] == "A local work"
    assert rows[0]["institution_code"] == "ut"

    body = {
        "institution_id": inst_id,
        "source": "openalex",
        "source_pk": "doi:10.1/xyz",
        "status": "candidate",
    }
    r = await admin_api.put("/api/v1/admin/work-identities", headers=headers, json=body)
    assert r.status_code == 200
    assert r.json()["status"] == "candidate"

    # No-op: no audit row.
    r = await admin_api.put("/api/v1/admin/work-identities", headers=headers, json=body)
    assert r.status_code == 200

    # Validation + unknown row.
    r = await admin_api.put(
        "/api/v1/admin/work-identities",
        headers=headers,
        json={**body, "status": "maybe"},
    )
    assert r.status_code == 422
    r = await admin_api.put(
        "/api/v1/admin/work-identities",
        headers=headers,
        json={**body, "source_pk": "doi:10.1/none"},
    )
    assert r.status_code == 404

    async with maker() as session:
        changes = (
            (
                await session.execute(
                    select(StatusChangeLog).where(StatusChangeLog.table_name == "work_identity")
                )
            )
            .scalars()
            .all()
        )
        assert len(changes) == 1
        assert changes[0].old_value == "missing"
        assert changes[0].new_value == "candidate"


@requires_db
async def test_author_identities_paging_envelope(admin_api, db_engine):
    """total reflects all filtered rows; offset pages through without overlap."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        inst_id = (await session.execute(select(Institution.id).limit(1))).scalar_one()
        base = datetime(2026, 1, 1, tzinfo=UTC)
        for i in range(5):
            session.add(
                AuthorIdentity(
                    institution_id=inst_id,
                    author_pure_uuid=f"p-page-{i}",
                    source="openalex",
                    external_id=f"a-{i}",
                    # Even rows confirmed, odd rows candidate: filter below.
                    status="candidate" if i % 2 else "confirmed",
                    method="initials",
                    n_works=1,
                    evidence={},
                    # Distinct stamps pin the newest-first order.
                    updated_at=base + timedelta(minutes=i),
                )
            )
        await session.commit()

    headers = await _login(admin_api)

    async def page(**params):
        r = await admin_api.get("/api/v1/admin/author-identities", params=params, headers=headers)
        assert r.status_code == 200
        return r.json()

    first = await page(limit=2)
    assert (first["total"], first["offset"]) == (5, 0)
    assert len(first["items"]) == 2

    second = await page(limit=2, offset=2)
    assert (second["total"], second["offset"]) == (5, 2)
    tail = await page(limit=2, offset=4)
    assert len(tail["items"]) == 1
    everything = {it["author_pure_uuid"] for it in first["items"] + second["items"] + tail["items"]}
    assert len(everything) == 5

    # Filters apply to the total, not just the items.
    filtered = await page(status="candidate", limit=1)
    assert filtered["total"] == 2
    assert {it["status"] for it in filtered["items"]} == {"candidate"}

    r = await admin_api.get(
        "/api/v1/admin/author-identities", params={"offset": -1}, headers=headers
    )
    assert r.status_code == 422


@requires_db
async def test_work_identities_paging_envelope(admin_api, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        inst_id = (await session.execute(select(Institution.id).limit(1))).scalar_one()
        run_id = (await session.execute(select(HarvestRun.id).limit(1))).scalar_one()
        for i in range(4):
            session.add(
                Work(
                    institution_id=inst_id,
                    pure_uuid=f"w-{i}",
                    title=f"Work {i}",
                    norm_title=f"work {i}",
                    year=2025,
                    first_seen_run=run_id,
                    last_seen_run=run_id,
                )
            )
            session.add(
                WorkIdentity(
                    institution_id=inst_id,
                    # Two openalex rows, two pure rows: filter below.
                    source="openalex" if i < 2 else "pure",
                    source_pk=f"doi:10.9/{i}",
                    work_id=f"w-{i}",
                    matched_by="doi",
                    status="missing",
                )
            )
        await session.commit()

    headers = await _login(admin_api)

    async def page(**params):
        r = await admin_api.get("/api/v1/admin/work-identities", params=params, headers=headers)
        assert r.status_code == 200
        return r.json()

    first = await page(limit=3)
    assert (first["total"], first["offset"]) == (4, 0)
    assert len(first["items"]) == 3
    rest = await page(limit=3, offset=3)
    assert (rest["total"], rest["offset"]) == (4, 3)
    assert len(rest["items"]) == 1
    seen = {it["source_pk"] for it in first["items"] + rest["items"]}
    assert len(seen) == 4

    filtered = await page(source="openalex", limit=1)
    assert filtered["total"] == 2
    assert {it["source"] for it in filtered["items"]} == {"openalex"}


@requires_db
async def test_feedback_status_change_is_audited(admin_api, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        session.add(Feedback(title="t", description="d", category="bug"))
        await session.commit()

    headers = await _login(admin_api)
    fb_id = (await admin_api.get("/api/v1/admin/feedback", headers=headers)).json()[0]["id"]

    # Status flip -> audited. Notes-only patch -> not audited.
    r = await admin_api.patch(
        f"/api/v1/admin/feedback/{fb_id}",
        headers=headers,
        json={"status": "in_progress", "changed_by": "sam"},
    )
    assert r.status_code == 200
    r = await admin_api.patch(
        f"/api/v1/admin/feedback/{fb_id}",
        headers=headers,
        json={"resolution_notes": "looking"},
    )
    assert r.status_code == 200

    async with maker() as session:
        changes = (
            (
                await session.execute(
                    select(StatusChangeLog).where(StatusChangeLog.table_name == "feedback_items")
                )
            )
            .scalars()
            .all()
        )
        assert len(changes) == 1
        assert changes[0].old_value == "todo"
        assert changes[0].new_value == "in_progress"
        assert changes[0].changed_by == "sam"


@requires_db
async def test_admin_summary_counts(admin_api, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        inst_id = (await session.execute(select(Institution.id).limit(1))).scalar_one()
        run_id = (
            await session.execute(
                select(HarvestRun.id).where(HarvestRun.source == "reconcile").limit(1)
            )
        ).scalar_one()
        session.add(
            HarvestRun(
                source="openaccess_nl",
                entity_type="deal",
                status="failed",
                config_fingerprint="x",
                stats={"error": "boom"},
            )
        )
        session.add(
            HarvestRun(
                source="openalex",
                entity_type="work",
                status="running",
                config_fingerprint="x",
                stats={},
            )
        )
        session.add(Feedback(title="t", description="d", category="bug"))
        session.add(
            AuthorIdentity(
                institution_id=inst_id,
                author_pure_uuid="p-sum",
                source="openalex",
                external_id="a-sum",
                status="candidate",
            )
        )
        session.add(
            Work(
                institution_id=inst_id,
                pure_uuid="w-sum",
                title="Summary work",
                norm_title="summary work",
                year=2025,
                first_seen_run=run_id,
                last_seen_run=run_id,
            )
        )
        session.add(
            WorkIdentity(
                institution_id=inst_id,
                source="openalex",
                source_pk="doi:10.1/sum",
                work_id="w-sum",
                matched_by="doi",
                status="candidate",
            )
        )
        await session.commit()

    headers = await _login(admin_api)
    r = await admin_api.get("/api/v1/admin/summary", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["failed_runs_24h"] == 1
    assert body["running_runs"] == 1
    assert body["flagged_deals"] == 1
    assert body["open_feedback"] == 1
    assert body["author_identity_candidates"] == 1
    assert body["work_identity_candidates"] == 1
    assert body["last_run"]["source"] == "openalex"
    assert body["last_run"]["status"] == "running"


@requires_db
async def test_admin_summary_institution_scope(admin_api, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        ut_id = (
            await session.execute(select(Institution.id).where(Institution.code == "ut"))
        ).scalar_one()
        session.add(Institution(name="Other University", code="rug", active=True))
        session.add(
            HarvestRun(
                source="openalex",
                entity_type="work",
                status="failed",
                institution_id=ut_id,
                config_fingerprint="x",
            )
        )
        session.add(
            HarvestRun(
                source="reconcile", entity_type="deal", status="completed", config_fingerprint="x"
            )
        )
        session.add(
            AuthorIdentity(
                institution_id=ut_id,
                author_pure_uuid="p-scope",
                source="openalex",
                external_id="a-scope",
                status="candidate",
            )
        )
        await session.commit()

    headers = await _login(admin_api)
    body = (await admin_api.get("/api/v1/admin/summary", headers=headers)).json()
    assert body["failed_runs_24h"] == 1
    assert body["author_identity_candidates"] == 1
    # Global last run is the unscoped rug run (inserted last).
    assert body["last_run"]["institution_code"] is None
    assert body["last_run"]["status"] == "completed"
    # Flagged deals and feedback stay instance-global.
    assert body["flagged_deals"] == 1
    assert body["open_feedback"] == 0

    scoped = (await admin_api.get("/api/v1/admin/summary?institution=ut", headers=headers)).json()
    assert scoped["failed_runs_24h"] == 1
    assert scoped["running_runs"] == 0
    assert scoped["author_identity_candidates"] == 1
    assert scoped["work_identity_candidates"] == 0
    assert scoped["last_run"]["institution_code"] == "ut"
    assert scoped["last_run"]["status"] == "failed"
    assert scoped["flagged_deals"] == 1

    rug = (await admin_api.get("/api/v1/admin/summary?institution=rug", headers=headers)).json()
    assert rug["failed_runs_24h"] == 0
    assert rug["author_identity_candidates"] == 0
    assert rug["last_run"] is None
    assert rug["flagged_deals"] == 1

    r = await admin_api.get("/api/v1/admin/summary?institution=nope", headers=headers)
    assert r.status_code == 404


@requires_db
async def test_external_author_served_from_source_records(admin_api, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        ut_id = (
            await session.execute(select(Institution.id).where(Institution.code == "ut"))
        ).scalar_one()
        run_id = (await session.execute(select(HarvestRun.id).limit(1))).scalar_one()
        session.add(
            SourceRecord(
                source="openalex",
                entity_type="authors",
                source_pk="A123",
                payload={
                    "id": "https://openalex.org/A123",
                    "display_name": "Jane Doe",
                    "works_count": 7,
                    "orcid": "https://orcid.org/0000-0000-0000-0001",
                },
                content_hash="h1",
                harvest_run_id=run_id,
            )
        )
        admin_works = [
            OpenalexWork(
                institution_id=ut_id,
                w_id="W1",
                title="One",
                year=2024,
                doi_normalized="10.1/one",
                authorships=[{"a": "A123", "n": "Jane Doe", "o": None}],
            ),
            OpenalexWork(
                institution_id=ut_id,
                w_id="W2",
                title="Two",
                year=2023,
                doi_normalized=None,
                authorships=[{"a": "A999", "n": "Other", "o": None}],
            ),
        ]
        session.add_all(admin_works)
        session.add_all(pair_rows(*admin_works))
        await session.commit()

    headers = await _login(admin_api)
    r = await admin_api.get("/api/v1/admin/external-author/A123", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["source_pk"] == "A123"
    assert body["author"]["display_name"] == "Jane Doe"
    assert [work["w_id"] for work in body["works"]] == ["W1"]
    assert body["works"][0]["doi"] == "10.1/one"

    scoped = await admin_api.get(
        "/api/v1/admin/external-author/A123?institution=ut", headers=headers
    )
    assert scoped.status_code == 200

    r = await admin_api.get("/api/v1/admin/external-author/A404", headers=headers)
    assert r.status_code == 404
