"""Canonical publisher resolution from the OpenAlex lineage hierarchy.

Distinct source host organizations (~16k ids: publisher P-ids and
institution I-ids) resolve through the OpenAlex publisher hierarchy to
their root publisher's display name. Results cache in openalex_publishers
(one row per attempted id, failures included) so re-runs fetch only
unknown ids, then journals.publisher_canonical backfills from the cache.
Hosts that are institutions, missing, or unfetchable keep the journal's
own publisher_name.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from aletheca import AlethecaClient
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import OpenalexPublisher, SourceRecord
from .openalex_journals import _payload_dict

logger = logging.getLogger(__name__)

BATCH = 50  # OpenAlex pipe-filter maximum

#: Latest source payload per journal -> cached lineage root -> canonical
#: name; journals without a resolvable host keep their own name (the
#: service's COALESCE fallback). IS DISTINCT FROM avoids rewriting rows
#: whose canonical is already correct (idempotent re-runs).
BACKFILL_SQL = text(
    """
    WITH latest AS (
        SELECT DISTINCT ON (sr.source_pk)
               sr.source_pk, sr.payload->>'host_organization' AS host_org
        FROM source_records sr
        WHERE sr.source = 'openalex' AND sr.entity_type = 'sources'
        ORDER BY sr.source_pk, sr.harvested_at DESC
    )
    UPDATE journals j
    SET publisher_canonical = op.canonical_name
    FROM latest l
    JOIN openalex_publishers op
      ON op.openalex_id = split_part(l.host_org, '/', -1)
     AND op.canonical_name IS NOT NULL
     AND op.canonical_name <> ''
    WHERE j.openalex_id = l.source_pk
      AND j.publisher_canonical IS DISTINCT FROM op.canonical_name
    """
)


def host_pk(host_org: str | None) -> str:
    """'https://openalex.org/P4310319808' -> 'P4310319808'."""
    return (host_org or "").rsplit("/", 1)[-1]


def canonical_from_lineage(lineage: Any) -> str | None:
    """OpenAlex lineage is [self, ..., root]; the root is the canonical
    publisher. None without a lineage (failed/missing fetch)."""
    if not lineage:
        return None
    return host_pk(lineage[-1])


async def distinct_host_orgs(session: AsyncSession) -> list[str | None]:
    rows = await session.execute(
        select(SourceRecord.payload.op("->>")("host_organization").label("host"))
        .where(SourceRecord.entity_type == "sources")
        .distinct()
    )
    return list(rows.scalars())


def _rows_for(
    payloads: dict[str, dict[str, Any] | None], names: dict[str, str | None]
) -> list[dict[str, Any]]:
    """One openalex_publishers row per attempted id; a None payload marks a
    failed fetch (NULL lineage) so re-runs skip it."""
    rows = []
    for pid, payload in payloads.items():
        payload = payload or {}
        lineage = [host_pk(x) for x in payload.get("lineage") or []]
        canonical_id = canonical_from_lineage(lineage)
        rows.append(
            dict(
                openalex_id=pid,
                display_name=payload.get("display_name"),
                lineage=lineage or None,
                canonical_id=canonical_id,
                canonical_name=names.get(canonical_id or "") or None,
                fetched_at=datetime.now(UTC),
            )
        )
    return rows


async def _store(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    # Chunked: asyncpg rejects statements with > 32767 bind parameters
    # (~10k publisher rows x 6 columns).
    for i in range(0, len(rows), 4000):
        chunk = rows[i : i + 4000]
        stmt = pg_insert(OpenalexPublisher).values(chunk)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["openalex_id"],
                set_={
                    "display_name": stmt.excluded.display_name,
                    "lineage": stmt.excluded.lineage,
                    "canonical_id": stmt.excluded.canonical_id,
                    "canonical_name": stmt.excluded.canonical_name,
                    "fetched_at": text("now()"),
                },
            )
        )


async def _fetch(client: AlethecaClient, ids: list[str]) -> dict[str, dict[str, Any] | None]:
    """Batched pipe-filter lookups; ids absent from the response map to
    None (404s are normal for some publisher entities)."""
    out: dict[str, dict[str, Any] | None] = {}
    for i in range(0, len(ids), BATCH):
        batch = ids[i : i + BATCH]
        found = await client.publishers.batch_get(
            batch, field="openalex_id", key_fn=lambda e: host_pk(_payload_dict(e)["id"])
        )
        for pid in batch:
            entity = found.get(pid)
            out[pid] = _payload_dict(entity) if entity is not None else None
    return out


async def backfill_canonical(session: AsyncSession) -> int:
    """Set journals.publisher_canonical from the latest source payload's
    host organization via the lineage cache; returns updated row count."""
    result = await session.execute(BACKFILL_SQL)
    return result.rowcount or 0


async def harvest_publishers(session: AsyncSession) -> dict[str, int]:
    """Resolve + cache every distinct source host organization's lineage,
    then backfill journals.publisher_canonical. Idempotent: only ids
    without a cache row are fetched."""
    hosts = await distinct_host_orgs(session)
    p_ids = sorted({hpk for h in hosts if (hpk := host_pk(h)).startswith("P")})
    cache = {
        row.openalex_id: row.display_name
        for row in (await session.execute(select(OpenalexPublisher))).scalars()
    }
    todo = [p for p in p_ids if p not in cache]
    stats = {
        "host_orgs": len(hosts),
        "publisher_ids": len(p_ids),
        "fetched": 0,
        "failed": 0,
        "journals_updated": 0,
    }
    if todo:
        client_kwargs: dict[str, Any] = {}
        if api_key := get_settings().openalex_api_key:
            client_kwargs["api_key"] = api_key
        async with AlethecaClient(**client_kwargs) as client:
            payloads = await _fetch(client, todo)
            # Root publishers referenced by a fetched lineage but never
            # seen themselves still need their display name.
            roots = {canonical_from_lineage(p.get("lineage")) for p in payloads.values() if p} - {
                None
            }
            need = sorted(roots - payloads.keys() - cache.keys())
            if need:
                payloads.update(await _fetch(client, need))
        names: dict[str, str | None] = dict(cache)
        names.update({pid: (p or {}).get("display_name") for pid, p in payloads.items()})
        rows = _rows_for(payloads, names)
        await _store(session, rows)
        stats["fetched"] = sum(1 for p in payloads.values() if p)
        stats["failed"] = sum(1 for p in payloads.values() if not p)
    result = await session.execute(BACKFILL_SQL)
    stats["journals_updated"] = result.rowcount or 0
    logger.info("harvest_publishers: %s", stats)
    return stats
