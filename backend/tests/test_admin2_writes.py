"""Admin write-path guarantees from the 2026-11-19 sweep:

- inverted data windows are rejected (finding 1) and clearing
  data_window_end works end to end (finding 6),
- reactivating an institution re-materializes its journal_flags in the
  same request (finding 2),
- a manual deal journal with an unknown ISSN is rejected (finding 5),
- settings, institution, and feedback priority/delete writes leave
  status_changes audit rows without ever logging a secret
  (findings 7 and 8),
- the admin summary counts "missing" work identities (finding 9).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from conftest import journal_factory, requires_db
from journal_browser.config import reset_settings_cache
from journal_browser.harvest.denorm import refresh_institution_stats
from journal_browser.harvest.institution_stats import write_pure_canon_stats
from journal_browser.models import (
    Deal,
    DealJournal,
    Feedback,
    HarvestRun,
    Institution,
    IssnMap,
    JournalFlags,
    Publisher,
    StatusChangeLog,
    Work,
    WorkIdentity,
)

PASSWORD = "test-admin-pw"


@pytest.fixture
async def writes_api(client, db, monkeypatch, tmp_path):
    """Admin login backdrop: one hosted institution with a works corpus, a
    flagged deal, an issn_map row, and a hermetic settings overlay."""
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "settings.yaml"))
    reset_settings_cache()
    inst = Institution(name="University of Twente", code="ut", active=True)
    db.add(inst)
    db.add(journal_factory("0000-0000"))
    pub = Publisher(name="Emerald Publishing group")
    db.add(pub)
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
    db.add(Deal(publisher_id=pub.id, status="current", corresponding_authors_only=False))
    db.add(IssnMap(issn="1111-1111", issn_l="1111-1119", source="test"))
    db.add(
        Feedback(
            title="Chart overlaps labels",
            description="The trend chart hides labels on small screens.",
        )
    )
    await write_pure_canon_stats(db, inst)
    await refresh_institution_stats(db, inst)
    await db.commit()
    yield client
    reset_settings_cache()


async def _login(client: AsyncClient) -> dict[str, str]:
    r = await client.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


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
async def test_inverted_window_rejected(writes_api, db):
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


@requires_db
async def test_clear_window_end_stores_open_null(writes_api, db):
    headers = await _login(writes_api)
    r = await writes_api.put(
        "/api/v1/admin/institutions/ut",
        headers=headers,
        json={"data_window_start": 2020, "data_window_end": 2022},
    )
    assert r.status_code == 200
    r = await writes_api.put(
        "/api/v1/admin/institutions/ut", headers=headers, json={"data_window_end": None}
    )
    assert r.status_code == 200
    assert r.json()["data_window_end"] is None
    await db.rollback()
    row = (
        (
            await db.execute(
                select(StatusChangeLog)
                .where(StatusChangeLog.table_name == "institutions")
                .order_by(StatusChangeLog.id.desc())
            )
        )
        .scalars()
        .first()
    )
    assert row is not None and row.field == "data_window_end"
    assert row.new_value == "(cleared)"
    assert row.row_key == {"code": "ut"}


@requires_db
async def test_reactivate_rematerializes_flags(writes_api, db):
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
    assert (
        len(
            list(
                (
                    await db.execute(select(JournalFlags).where(JournalFlags.institution_id == iid))
                ).scalars()
            )
        )
        == 0
    )

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
    rows = await _inst_audit_rows(db)
    flips = [r for r in rows if r.field == "active"]
    assert [(r.old_value, r.new_value) for r in flips] == [
        ("true", "false"),
        ("false", "true"),
    ]


@requires_db
async def test_institution_field_writes_audited(writes_api, db):
    headers = await _login(writes_api)
    r = await writes_api.put(
        "/api/v1/admin/institutions/ut", headers=headers, json={"short_name": "UT"}
    )
    assert r.status_code == 200
    await db.rollback()
    row = (await _inst_audit_rows(db))[-1]
    assert (row.field, row.old_value, row.new_value) == ("short_name", None, "UT")


@requires_db
async def test_deal_journal_unknown_issn_rejected(writes_api, db):
    headers = await _login(writes_api)
    deal_id = (await db.execute(select(Deal.id).order_by(Deal.id))).scalars().first()
    r = await writes_api.put(
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
    r = await writes_api.put(
        f"/api/v1/admin/deals/{deal_id}/journals",
        headers=headers,
        json={"add": [{"issn": "1111-1111"}]},
    )
    assert r.status_code == 200
    added = next(j for j in r.json()["journals"] if j["issn"] == "1111-1111")
    assert added["issn_l"] == "1111-1119"


@requires_db
async def test_settings_writes_audited_and_secret_masked(writes_api, db):
    headers = await _login(writes_api)
    r = await writes_api.put(
        "/api/v1/admin/settings",
        headers=headers,
        json={"values": {"contact_email": "lib@example.edu"}},
    )
    assert r.status_code == 200
    await db.rollback()
    rows = list(
        (
            await db.execute(
                select(StatusChangeLog).where(StatusChangeLog.table_name == "settings")
            )
        ).scalars()
    )
    email_rows = [r for r in rows if r.field == "contact_email"]
    assert email_rows and email_rows[0].new_value == "lib@example.edu"

    # A secret write is audited, but only as (masked) on both sides.
    r = await writes_api.put(
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
    stored = repr(secret_rows[0])
    assert "sekret-key-123" not in stored


@requires_db
async def test_feedback_priority_and_delete_audited(writes_api, db):
    headers = await _login(writes_api)
    feedback_id = (await db.execute(select(Feedback.id).order_by(Feedback.id))).scalars().first()
    r = await writes_api.patch(
        f"/api/v1/admin/feedback/{feedback_id}",
        headers=headers,
        json={"priority": "high"},
    )
    assert r.status_code == 200
    await db.rollback()
    row = (
        (
            await db.execute(
                select(StatusChangeLog)
                .where(
                    StatusChangeLog.table_name == "feedback_items",
                    StatusChangeLog.field == "priority",
                )
                .order_by(StatusChangeLog.id.desc())
            )
        )
        .scalars()
        .first()
    )
    assert row is not None
    assert (row.old_value, row.new_value, row.row_key) == (
        "normal",
        "high",
        {"id": feedback_id},
    )

    r = await writes_api.delete(f"/api/v1/admin/feedback/{feedback_id}", headers=headers)
    assert r.status_code == 204
    await db.rollback()
    row = (
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
    assert row is not None and row.new_value == "deleted"
    assert "Chart overlaps labels" in (row.note or "")


@requires_db
async def test_summary_counts_missing_work_identities(writes_api, db):
    inst_id = (
        (await db.execute(select(Institution.id).where(Institution.code == "ut"))).scalars().one()
    )
    # work_identity.work_id is an FK into works (institution_id, pure_uuid),
    # so the rows must reference the seeded "ut-in" work.
    for i in range(2):
        db.add(
            WorkIdentity(
                institution_id=inst_id,
                source="openalex",
                source_pk=f"w{i}",
                work_id="ut-in",
                matched_by="trgm:0.7",
                status="missing",
            )
        )
    db.add(
        WorkIdentity(
            institution_id=inst_id,
            source="openalex",
            source_pk="w-cand",
            work_id="ut-in",
            matched_by="trgm:0.7",
            status="candidate",
        )
    )
    await db.commit()

    headers = await _login(writes_api)
    r = await writes_api.get("/api/v1/admin/summary", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["work_identity_missing"] == 2
    assert body["work_identity_candidates"] == 1
