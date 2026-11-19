"""Work funder harvest: OpenAlex awards extraction + upsert idempotency.

Unit tests assert the awards-payload projection literally (bare funder
id, missing award, dedupe by funder); the DB test runs the real
upsert/prune path on the throwaway test database.
"""

from sqlalchemy import select

from conftest import requires_db
from journal_browser.harvest import work_funders as work_funders_mod
from journal_browser.harvest.work_funders import (
    _prune,
    _upsert,
    grants_rows,
    harvest_work_funders,
)
from journal_browser.models import HarvestRun, Institution, SourceRecord, Work, WorkFunder


def _award(funder_id: str | None, name: str | None = None, award_id: str | None = None):
    return {
        "funder_id": f"https://openalex.org/{funder_id}" if funder_id else None,
        "funder_display_name": name,
        "funder_award_id": award_id,
    }


# ── awards payload projection ─────────────────────────────────────────────


def test_grants_rows_bares_funder_id_and_keeps_missing_award():
    rows = grants_rows(1, "uuid-a", [_award("F4320306080", "NWO", None)])
    assert rows == [
        {
            "institution_id": 1,
            "pure_uuid": "uuid-a",
            "funder_openalex_id": "F4320306080",
            "funder_name": "NWO",
            "award": None,
        }
    ]


def test_grants_rows_dedupes_by_funder_first_award_wins():
    rows = grants_rows(
        1, "u", [_award("F1", "A", "999"), _award("F1", "A", "123"), _award("F2", None, "x")]
    )
    assert [r["funder_openalex_id"] for r in rows] == ["F1", "F2"]
    assert rows[0]["award"] == "999"


def test_grants_rows_skips_missing_funder_and_empty_payload():
    assert grants_rows(1, "u", [_award(None, "n", "a"), {"funder_id": "garbage"}]) == []
    assert grants_rows(1, "u", []) == []
    assert grants_rows(1, "u", None) == []


# ── upsert + prune idempotency (DB) ───────────────────────────────────────


async def _land_work(db, inst: Institution, doi: str, uuid: str = "uuid-a") -> Work:
    run = HarvestRun(source="test", entity_type="works", config_fingerprint="test")
    db.add(run)
    await db.flush()
    work = Work(
        institution_id=inst.id,
        pure_uuid=uuid,
        doi_normalized=doi,
        title="t",
        norm_title="t",
        year=2020,
        first_seen_run=run.id,
        last_seen_run=run.id,
    )
    db.add(work)
    await db.commit()
    return work


async def _all_funders(db):
    # populate_existing: Core upserts/deletes bypass the identity map
    return (
        (await db.execute(select(WorkFunder).execution_options(populate_existing=True)))
        .scalars()
        .all()
    )


@requires_db
async def test_work_funder_upsert_idempotent_and_prunes_stale(db, institution_factory):
    inst = await institution_factory(code="ut")
    work = await _land_work(db, inst, "10.1234/abc")

    rows = grants_rows(
        inst.id, work.pure_uuid, [_award("F1", "NWO", "100"), _award("F2", "EC", "200")]
    )
    assert await _upsert(db, rows) == 2
    await db.commit()
    assert sorted(f.funder_openalex_id for f in await _all_funders(db)) == ["F1", "F2"]

    # rerun with the same rows: no growth, award refreshed in place
    rows[0]["award"] = "100b"
    assert await _upsert(db, rows) == 2
    await db.commit()
    stored = await _all_funders(db)
    assert len(stored) == 2
    assert next(f for f in stored if f.funder_openalex_id == "F1").award == "100b"

    # funder F2 disappears from the fresh award set -> pruned
    fresh = grants_rows(inst.id, work.pure_uuid, [_award("F1", "NWO", "100b")])
    assert await _prune(db, [work], fresh) == 1
    await db.commit()
    assert [f.funder_openalex_id for f in await _all_funders(db)] == ["F1"]

    # an empty fresh set prunes everything left
    assert await _prune(db, [work], []) == 1
    await db.commit()
    assert await _all_funders(db) == []


# ── raw payload storage (DB) ──────────────────────────────────────────────


class _FakeAwardWork:
    """Shape harvest_work_funders reads: id, awards, model_dump."""

    id = "W999"

    def __init__(self):
        self.awards = [
            {
                "funder_id": "https://openalex.org/F1",
                "funder_display_name": "NWO",
                "funder_award_id": "100",
            }
        ]

    def model_dump(self, mode: str = "json"):
        return {"id": self.id, "awards": self.awards}


@requires_db
async def test_harvest_work_funders_stores_raw_payloads(db, institution_factory, monkeypatch):
    inst = await institution_factory(code="ut")
    await _land_work(db, inst, "10.1234/wf-raw")

    async def _fake_fetch(client, dois, stats=None):
        return {doi: _FakeAwardWork() for doi in dois}, set(), None

    class _FakeClient:
        def __init__(self, **kwargs): ...

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(work_funders_mod, "fetch_works_by_doi", _fake_fetch)
    monkeypatch.setattr(work_funders_mod, "AlethecaClient", _FakeClient)

    stats = await harvest_work_funders(db)
    assert stats["rows_upserted"] == 1
    assert stats["records_stored"] == 1

    raw = (
        await db.execute(
            select(SourceRecord).where(
                SourceRecord.source == "openalex",
                SourceRecord.entity_type == "work",
                SourceRecord.source_pk == "W999",
            )
        )
    ).scalar_one()
    assert raw.payload["id"] == "W999"
    run = await db.get(HarvestRun, raw.harvest_run_id)
    assert run.status == "completed"
    assert run.entity_type == "work"
