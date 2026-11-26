"""source_records storage: which payload versions are superseded, and the
keys a stored payload keeps.

`source_records` is append-only. A changed payload lands as a new version
(unique on source, entity_type, source_pk, content_hash) and no job removed
the older version, so superseded rows made up 39% of the live table in
2026-11.

Every reader takes, per (source, entity_type, source_pk), the newest version
inside one institution's harvest runs (openalex_works, the Pure entities and
the author listings scope their DISTINCT ON by harvest_runs.institution_id)
or the newest version overall (JISC, OpenAIRE facts, work partners, OpenAPC
evidence, journal info). Older versions are unused, so
`jobs/prune_source_records.py` deletes them. A version that apc_evidence
points at is never selected.

Rows written before ingest.PAYLOAD_DROP_KEYS existed still carry the keys
the ingest projection now omits; `jobs/strip_source_records.py` removes
them in place.
"""

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Text, and_, bindparam, delete, exists, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from .ingest import PAYLOAD_DROP_KEYS
from .models import ApcEvidence, HarvestRun, SourceRecord

#: Row-lock wait per committed batch. A longer wait means something unexpected
#: holds source_records rows; the job then aborts instead of queueing behind it.
LOCK_TIMEOUT = "5s"
BATCH_IDS = 10_000


def _newer_versions():
    """Correlated count of versions newer than the outer source_records row.

    "Newer" is scoped to the harvest run's institution: a version harvested
    for institution A never supersedes institution B's copy of the same key,
    because institution-scoped readers only look at their own rows.
    """
    newer, newer_run = aliased(SourceRecord), aliased(HarvestRun)
    return (
        select(func.count())
        .select_from(newer)
        .join(newer_run, newer_run.id == newer.harvest_run_id)
        .where(
            newer.source == SourceRecord.source,
            newer.entity_type == SourceRecord.entity_type,
            newer.source_pk == SourceRecord.source_pk,
            newer_run.institution_id.is_not_distinct_from(HarvestRun.institution_id),
            tuple_(newer.harvested_at, newer.id)
            > tuple_(SourceRecord.harvested_at, SourceRecord.id),
        )
        .correlate(SourceRecord, HarvestRun)
        .scalar_subquery()
    )


async def superseded_versions(
    session: AsyncSession,
    *,
    after_id: int,
    batch: int,
    keep: int = 1,
    older_than: datetime | None = None,
    source: str | None = None,
) -> list[tuple[int, str, str, int]]:
    """Superseded versions with id in (after_id, after_id + batch].

    A version is superseded when at least `keep` newer versions exist for
    the same key inside the same institution scope. Versions harvested at
    or after `older_than` are not superseded yet. Returns one
    (id, source, entity_type, stored payload bytes) tuple per version.
    """
    stmt = (
        select(
            SourceRecord.id,
            SourceRecord.source,
            SourceRecord.entity_type,
            func.pg_column_size(SourceRecord.payload),
        )
        .join(HarvestRun, HarvestRun.id == SourceRecord.harvest_run_id)
        .where(
            SourceRecord.id > after_id,
            SourceRecord.id <= after_id + batch,
            _newer_versions() >= keep,
            ~exists().where(ApcEvidence.source_record_id == SourceRecord.id),
        )
        .order_by(SourceRecord.id)
    )
    if older_than is not None:
        stmt = stmt.where(SourceRecord.harvested_at < older_than)
    if source is not None:
        stmt = stmt.where(SourceRecord.source == source)
    return [(row[0], row[1], row[2], row[3]) for row in (await session.execute(stmt)).all()]


async def delete_versions(session: AsyncSession, ids: Sequence[int]) -> int:
    """Delete versions by id; one that apc_evidence points at stays. Returns the count."""
    result = await session.execute(
        delete(SourceRecord).where(
            SourceRecord.id.in_(ids),
            ~exists().where(ApcEvidence.source_record_id == SourceRecord.id),
        )
    )
    return result.rowcount or 0


async def prune_superseded(
    session: AsyncSession,
    *,
    apply: bool = False,
    keep: int = 1,
    older_than: datetime | None = None,
    source: str | None = None,
    batch: int = BATCH_IDS,
    on_batch: Callable[[int, int, int], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Scan source_records in id order; report or delete superseded versions.

    Without `apply` nothing is written. With `apply`, each id range is
    deleted and committed before the next one is scanned, so the job holds
    row locks for one batch at a time and an interrupted run leaves a
    consistent table that the next run rescans. `on_batch(last_id,
    selected, deleted)` runs after every range.

    Returns the totals. payload_bytes is the compressed size of the
    selected payloads; plain VACUUM turns it into free space that new
    versions reuse.
    """
    max_id = (await session.execute(select(func.max(SourceRecord.id)))).scalar_one()
    await session.rollback()
    by_source: dict[str, dict[str, int]] = {}
    stats: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "keep": keep,
        "source": source,
        "older_than": older_than.isoformat() if older_than else None,
        "rows": 0,
        "deleted": 0,
        "payload_bytes": 0,
        "batches": 0,
        "by_source": by_source,
    }
    after_id = 0
    while after_id < (max_id or 0):
        rows = await superseded_versions(
            session,
            after_id=after_id,
            batch=batch,
            keep=keep,
            older_than=older_than,
            source=source,
        )
        deleted = 0
        if apply and rows:
            await session.execute(select(func.set_config("lock_timeout", LOCK_TIMEOUT, True)))
            deleted = await delete_versions(session, [row[0] for row in rows])
        if apply:
            await session.commit()
        else:
            await session.rollback()
        stats["rows"] += len(rows)
        stats["deleted"] += deleted
        stats["batches"] += 1
        for _, row_source, entity_type, payload_bytes in rows:
            group = by_source.setdefault(
                f"{row_source}/{entity_type}", {"rows": 0, "payload_bytes": 0}
            )
            group["rows"] += 1
            group["payload_bytes"] += payload_bytes
            stats["payload_bytes"] += payload_bytes
        after_id += batch
        if on_batch is not None:
            await on_batch(after_id, len(rows), deleted)
    return stats


def _carries(keys: frozenset[str], param_name: str = "keys"):
    """`payload ?| keys`: the payload still has one of the dropped keys."""
    return SourceRecord.payload.op("?|")(bindparam(param_name, sorted(keys), type_=ARRAY(Text)))


def _without(keys: frozenset[str], param_name: str = "drop_keys"):
    """`payload - text[]`: the payload minus its dropped top-level keys."""
    return SourceRecord.payload.op("-")(bindparam(param_name, sorted(keys), type_=ARRAY(Text)))


async def strip_stored_payloads(
    session: AsyncSession,
    *,
    apply: bool = False,
    batch: int = BATCH_IDS,
    on_batch: Callable[[str, int, int, int, int], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """Remove the PAYLOAD_DROP_KEYS keys from stored payloads that still have one.

    Rows written before the ingest projection existed keep those keys until
    this runs. The table is scanned once in id ranges across every
    (source, entity_type) group with dropped keys, and only payloads carrying
    a dropped key are rewritten, so a rerun finds nothing left. id,
    content_hash and harvested_at stay as they were. Without `apply` nothing
    is written. `on_batch(group, last_id, rows, bytes_before, bytes_after)`
    runs after every matching group's range.

    Returns the totals. payload_bytes_before and payload_bytes_after are the
    compressed sizes of the rewritten payloads, read from the stored rows.
    """
    max_id = (await session.execute(select(func.max(SourceRecord.id)))).scalar_one()
    await session.rollback()
    stats: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "rows": 0,
        "payload_bytes_before": 0,
        "payload_bytes_after": 0,
        "by_source": {
            f"{source}/{entity_type}": {
                "rows": 0,
                "payload_bytes_before": 0,
                "payload_bytes_after": 0,
            }
            for source, entity_type in sorted(PAYLOAD_DROP_KEYS)
        },
    }
    group_specs = sorted(PAYLOAD_DROP_KEYS.items())
    match_predicate = or_(
        *(
            and_(
                SourceRecord.source == source,
                SourceRecord.entity_type == entity_type,
                _carries(keys, f"keys_{idx}"),
            )
            for idx, ((source, entity_type), keys) in enumerate(group_specs)
        )
    )
    after_id = 0
    while after_id < (max_id or 0):
        rows = (
            await session.execute(
                select(
                    SourceRecord.id,
                    SourceRecord.source,
                    SourceRecord.entity_type,
                    func.pg_column_size(SourceRecord.payload),
                ).where(
                    SourceRecord.id > after_id,
                    SourceRecord.id <= after_id + batch,
                    match_predicate,
                )
            )
        ).all()
        by_group: dict[tuple[str, str], list[tuple[int, int]]] = {}
        for row_id, src, etype, size in rows:
            by_group.setdefault((src, etype), []).append((row_id, size))
        group_results: dict[str, tuple[int, int, int]] = {}
        if apply and by_group:
            await session.execute(select(func.set_config("lock_timeout", LOCK_TIMEOUT, True)))
        for (source, entity_type), items in sorted(by_group.items()):
            name = f"{source}/{entity_type}"
            keys = PAYLOAD_DROP_KEYS[(source, entity_type)]
            ids = [row_id for row_id, _ in items]
            before = sum(size for _, size in items)
            after = before
            if apply and ids:
                await session.execute(
                    update(SourceRecord)
                    .where(SourceRecord.id.in_(ids))
                    .values(payload=_without(keys, f"drop_{source}_{entity_type}"))
                )
                after = int(
                    await session.scalar(
                        select(
                            func.coalesce(func.sum(func.pg_column_size(SourceRecord.payload)), 0)
                        ).where(SourceRecord.id.in_(ids))
                    )
                    or 0
                )
            group = stats["by_source"][name]
            group["rows"] += len(ids)
            group["payload_bytes_before"] += before
            group["payload_bytes_after"] += after
            group_results[name] = (len(ids), before, after)
        if apply:
            await session.commit()
        else:
            await session.rollback()
        after_id += batch
        if on_batch is not None:
            for (source, entity_type), _keys in group_specs:
                name = f"{source}/{entity_type}"
                n_rows, before, after = group_results.get(name, (0, 0, 0))
                await on_batch(name, after_id, n_rows, before, after)
    for field in ("rows", "payload_bytes_before", "payload_bytes_after"):
        stats[field] = sum(group[field] for group in stats["by_source"].values())
    return stats
