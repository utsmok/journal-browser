"""source_records retention: superseded-version selection, the prune pass,
and the in-place removal of dropped payload keys."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from conftest import requires_db
from journal_browser.harvest.pure.entities import latest_publication_records
from journal_browser.ingest import content_hash
from journal_browser.models import ApcEvidence, HarvestRun, SourceRecord
from journal_browser.retention import (
    delete_versions,
    prune_superseded,
    strip_stored_payloads,
    superseded_versions,
)

NOW = datetime(2026, 11, 25, tzinfo=UTC)
PURE_PK = "oai:ris.utwente.nl:publications/11111111-1111-1111-1111-111111111111"


async def _version(
    db,
    source: str,
    entity_type: str,
    pk: str,
    payload: dict[str, Any],
    *,
    age_days: int,
    institution_id: int | None = None,
) -> SourceRecord:
    run = HarvestRun(
        source=source,
        entity_type=entity_type,
        institution_id=institution_id,
        status="completed",
        config_fingerprint=f"{source}-{entity_type}-{institution_id}-{age_days}",
        stats={},
    )
    db.add(run)
    await db.flush()
    row = SourceRecord(
        source=source,
        entity_type=entity_type,
        source_pk=pk,
        payload=payload,
        content_hash=content_hash(payload),
        harvest_run_id=run.id,
        harvested_at=NOW - timedelta(days=age_days),
    )
    db.add(row)
    await db.flush()
    return row


def _ids(rows: list[tuple[int, str, str, int]]) -> list[int]:
    return sorted(row[0] for row in rows)


async def _selected(db, **kwargs) -> list[tuple[int, str, str, int]]:
    return await superseded_versions(db, after_id=0, batch=10_000, **kwargs)


async def _stored_ids(db) -> list[int]:
    return list((await db.scalars(select(SourceRecord.id).order_by(SourceRecord.id))).all())


# ── Selection ──────────────────────────────────────────────────────────────


@requires_db
async def test_older_versions_are_superseded_inside_their_institution(db, institution_factory):
    ut = await institution_factory(code="ut")
    rug = await institution_factory(code="rug")
    ut_old = await _version(
        db, "openalex", "works_stats", "W1", {"v": 1}, age_days=30, institution_id=ut.id
    )
    await _version(db, "openalex", "works_stats", "W1", {"v": 2}, age_days=10, institution_id=ut.id)
    # RUG's only version is older than UT's newest one, but it is the newest
    # version RUG's readers see.
    await _version(
        db, "openalex", "works_stats", "W1", {"v": 3}, age_days=20, institution_id=rug.id
    )
    global_old = await _version(db, "openaire", "facts", "F1", {"v": 1}, age_days=30)
    await _version(db, "openaire", "facts", "F1", {"v": 2}, age_days=10)
    await _version(db, "crossref", "work", "C1", {"v": 1}, age_days=40)
    await db.commit()

    rows = await _selected(db)

    assert _ids(rows) == sorted([ut_old.id, global_old.id])
    assert [(row[1], row[2]) for row in rows] == [
        ("openalex", "works_stats"),
        ("openaire", "facts"),
    ]
    assert all(row[3] > 0 for row in rows)


@requires_db
async def test_equal_timestamps_resolve_by_id(db):
    older = await _version(db, "crossref", "work", "C1", {"v": 1}, age_days=5)
    await _version(db, "crossref", "work", "C1", {"v": 2}, age_days=5)
    await db.commit()

    assert _ids(await _selected(db)) == [older.id]


@requires_db
async def test_version_referenced_by_apc_evidence_stays(db):
    old = await _version(db, "openapc", "article", "10.1/x", {"euro": 1}, age_days=30)
    await _version(db, "openapc", "article", "10.1/x", {"euro": 2}, age_days=5)
    db.add(ApcEvidence(doi="10.1/x", euro=1, source_record_id=old.id))
    await db.commit()

    assert await _selected(db) == []
    assert await delete_versions(db, [old.id]) == 0


@requires_db
async def test_keep_min_age_and_source_narrow_the_selection(db):
    v1 = await _version(db, "crossref", "work", "C1", {"v": 1}, age_days=30)
    v2 = await _version(db, "crossref", "work", "C1", {"v": 2}, age_days=20)
    v3 = await _version(db, "crossref", "work", "C1", {"v": 3}, age_days=10)
    await _version(db, "crossref", "work", "C1", {"v": 4}, age_days=1)
    await db.commit()

    assert _ids(await _selected(db)) == [v1.id, v2.id, v3.id]
    assert _ids(await _selected(db, keep=2)) == [v1.id, v2.id]
    assert _ids(await _selected(db, older_than=NOW - timedelta(days=5))) == [v1.id, v2.id, v3.id]
    assert await _selected(db, source="openalex") == []


# ── Prune pass ─────────────────────────────────────────────────────────────


@requires_db
async def test_dry_run_reports_without_deleting(db):
    old_id = (await _version(db, "crossref", "work", "C1", {"v": 1}, age_days=30)).id
    await _version(db, "crossref", "work", "C1", {"v": 2}, age_days=5)
    await db.commit()

    report = await prune_superseded(db)

    assert report["mode"] == "dry-run"
    assert report["rows"] == 1 and report["deleted"] == 0
    assert old_id in await _stored_ids(db)


@requires_db
async def test_apply_deletes_the_selection_once_and_reports_bytes(db):
    await _version(db, "crossref", "work", "C1", {"v": 1}, age_days=30)
    new = await _version(db, "crossref", "work", "C1", {"v": 2}, age_days=5)
    single = await _version(db, "crossref", "work", "C2", {"v": 1}, age_days=30)
    await _version(db, "openaire", "facts", "F1", {"v": 1}, age_days=30)
    facts_new = await _version(db, "openaire", "facts", "F1", {"v": 2}, age_days=5)
    await db.commit()

    # The pass rolls the session back, which expires these instances.
    kept = sorted([new.id, single.id, facts_new.id])
    # One id per committed range: every range is scanned whatever its size.
    report = await prune_superseded(db, apply=True, batch=1)

    assert await _stored_ids(db) == kept
    assert report["mode"] == "apply"
    assert report["rows"] == report["deleted"] == 2
    assert (
        report["payload_bytes"]
        == sum(group["payload_bytes"] for group in report["by_source"].values())
        > 0
    )
    assert {name: group["rows"] for name, group in report["by_source"].items()} == {
        "crossref/work": 1,
        "openaire/facts": 1,
    }
    assert (await prune_superseded(db, apply=True))["rows"] == 0


@requires_db
async def test_institution_scoped_reader_sees_the_same_records_after_prune(db, institution_factory):
    ut = await institution_factory(code="ut")
    rug = await institution_factory(code="rug")
    await _version(
        db, "pure", "work_cerif", PURE_PK, {"title": "old"}, age_days=40, institution_id=ut.id
    )
    await _version(
        db, "pure", "work_cerif", PURE_PK, {"title": "UT"}, age_days=10, institution_id=ut.id
    )
    await _version(
        db, "pure", "work_cerif", PURE_PK, {"title": "RUG"}, age_days=20, institution_id=rug.id
    )
    await db.commit()
    # The pass rolls the session back, which expires these instances.
    inst_ids = [ut.id, rug.id]
    before = {inst_id: await latest_publication_records(db, inst_id) for inst_id in inst_ids}
    assert {inst_id: [p["title"] for p in recs.values()] for inst_id, recs in before.items()} == {
        inst_ids[1]: ["RUG"],
        inst_ids[0]: ["UT"],
    }

    report = await prune_superseded(db, apply=True)

    assert report["deleted"] == 1
    after = {inst_id: await latest_publication_records(db, inst_id) for inst_id in inst_ids}
    assert after == before


# ── Dropped keys in stored payloads ────────────────────────────────────────


@requires_db
async def test_strip_reports_then_rewrites_only_payloads_with_dropped_keys(db):
    journal = await _version(
        db,
        "openalex",
        "sources",
        "S1",
        {"id": "S1", "topic_share": [1], "topics": [2]},
        age_days=1,
    )
    work = await _version(
        db,
        "openalex",
        "works_stats",
        "W1",
        {"id": "W1", "abstract_inverted_index": {"T": [0]}, "publication_year": 2024},
        age_days=1,
    )
    product = await _version(db, "openaire", "work", "P1", {"descriptions": ["d"]}, age_days=1)
    await db.commit()
    # The passes roll the session back, which expires these instances.
    ids = [row.id for row in (journal, work, product)]
    unchanged = {
        row.id: (row.content_hash, row.harvested_at, row.publication_year)
        for row in (journal, work, product)
    }

    report = await strip_stored_payloads(db)

    assert report["mode"] == "dry-run" and report["rows"] == 2
    assert (await db.get(SourceRecord, ids[0])).payload["topic_share"] == [1]

    report = await strip_stored_payloads(db, apply=True, batch=1)
    rows = {row.id: row for row in (await db.execute(select(SourceRecord))).scalars()}

    assert rows[ids[0]].payload == {"id": "S1", "topics": [2]}
    assert rows[ids[1]].payload == {"id": "W1", "publication_year": 2024}
    assert rows[ids[2]].payload == {"descriptions": ["d"]}
    assert {
        row_id: (row.content_hash, row.harvested_at, row.publication_year)
        for row_id, row in rows.items()
    } == unchanged
    assert report["rows"] == 2
    assert report["payload_bytes_after"] < report["payload_bytes_before"]
    assert (await strip_stored_payloads(db, apply=True))["rows"] == 0
