"""Per-work funder harvest: OpenAlex works awards -> work_funders.

Every OpenAlex work carries its grants/awards inline (funder id, display
name, award number), so no funder sweep or join is needed: fetch each
work's DOI as a single-entity GET (free under OpenAlex's 2026-11 credit
pricing, unlike the pipe-OR batch filter this replaced), project awards
into work_funders rows, and upsert. Idempotent: reruns refresh every
touched row and prune rows for works whose awards changed or whose DOI
stopped resolving. Committing per chunk follows the author_ids sweep
convention, so an interrupted run simply resumes as a rerun.
"""

import logging
from collections import defaultdict
from collections.abc import Sequence
from typing import Any, cast

from aletheca import AlethecaClient
from sqlalchemy import delete, func, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..ingest import IngestSession
from ..models import Work, WorkFunder
from .enrich import fetch_works_by_doi

logger = logging.getLogger(__name__)

#: works per fetch chunk of single-entity GETs (see enrich.fetch_works_by_doi)
WORK_CHUNK = 500
#: asyncpg caps statements at 32,767 binds; rows here have 6 columns
UPSERT_CHUNK = 2_000
#: log progress every N batches
PROGRESS_EVERY = 20

UPSERT_COLS = ("funder_name", "award")


def grants_rows(
    inst_id: int, pure_uuid: str, awards: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """work_funders rows from one work's awards payload; deduped by
    funder (first award wins), entries without a funder id skipped."""
    rows: dict[str, dict[str, Any]] = {}
    for g in awards or []:
        funder_id = str(g.get("funder_id") or "").rsplit("/", 1)[-1]
        if not funder_id.startswith("F"):
            continue
        rows.setdefault(
            funder_id,
            {
                "institution_id": inst_id,
                "pure_uuid": pure_uuid,
                "funder_openalex_id": funder_id,
                "funder_name": g.get("funder_display_name"),
                "award": g.get("funder_award_id"),
            },
        )
    return list(rows.values())


async def _upsert(session: AsyncSession, rows: list[dict[str, Any]]) -> int:
    """Chunked INSERT ... ON CONFLICT DO UPDATE; harvested_at re-stamps
    to now() on every rerun."""
    for at in range(0, len(rows), UPSERT_CHUNK):
        chunk = rows[at : at + UPSERT_CHUNK]
        stmt = pg_insert(cast("Any", WorkFunder.__table__)).values(chunk)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["institution_id", "pure_uuid", "funder_openalex_id"],
                set_={
                    **{c: getattr(stmt.excluded, c) for c in UPSERT_COLS},
                    "harvested_at": text("now()"),
                },
            )
        )
    return len(rows)


async def _prune(session: AsyncSession, works: Sequence[Any], rows: list[dict[str, Any]]) -> int:
    """Drop work_funders rows of this batch's works that the fresh award
    set no longer carries; returns the deleted row count."""
    work_keys = [(w.institution_id, w.pure_uuid) for w in works]
    stmt = delete(WorkFunder).where(
        tuple_(WorkFunder.institution_id, WorkFunder.pure_uuid).in_(work_keys)
    )
    if rows:
        fresh_keys = [(r["institution_id"], r["pure_uuid"], r["funder_openalex_id"]) for r in rows]
        stmt = stmt.where(
            tuple_(
                WorkFunder.institution_id,
                WorkFunder.pure_uuid,
                WorkFunder.funder_openalex_id,
            ).not_in(fresh_keys)
        )
    result = await session.execute(stmt)
    return int(getattr(result, "rowcount", 0) or 0)


async def harvest_work_funders(session: AsyncSession) -> dict[str, Any]:
    """Upsert work_funders from OpenAlex awards for every work with a
    DOI. Idempotent full refresh; stats name the sweep's shape. Fetched
    work payloads land verbatim in source_records via IngestSession
    (deduped by content hash, merged W-ids included)."""
    stats: dict[str, Any] = {
        "works_attempted": 0,
        "matched_with_grants": 0,
        "rows_upserted": 0,
        "pruned": 0,
    }

    result = await session.execute(
        select(Work.institution_id, Work.pure_uuid, Work.doi_normalized).where(
            Work.doi_normalized.is_not(None)
        )
    )
    works = result.all()
    stats["works_attempted"] = len(works)
    if not works:
        raise RuntimeError("work_funders harvest: zero works with a doi_normalized")

    client_kwargs: dict[str, Any] = {}
    if api_key := get_settings().openalex_api_key:
        client_kwargs["api_key"] = api_key

    fetch_stats: dict[str, int] = {}
    ingest = IngestSession(session)
    await ingest.start_run(
        "openalex",
        "work",
        "work_funders",
        {"via": "single_get_by_doi"},
    )
    async with AlethecaClient(**client_kwargs) as client:
        for at in range(0, len(works), WORK_CHUNK):
            batch = works[at : at + WORK_CHUNK]
            batch_no = at // WORK_CHUNK + 1
            # works in different institutions may share a DOI
            by_doi: dict[str, list[Any]] = defaultdict(list)
            for w in batch:
                by_doi[w.doi_normalized].append(w)
            found, errored, _ = await fetch_works_by_doi(client, list(by_doi), fetch_stats)

            rows: list[dict[str, Any]] = []
            matched = 0
            for doi, award_payload in found.items():
                if award_payload is None or doi in errored:
                    continue
                await ingest.ingest_record(
                    str(getattr(award_payload, "id", "") or f"doi:{doi}"),
                    award_payload.model_dump(mode="json"),
                )
                for w in by_doi.get(doi, ()):
                    work_rows = grants_rows(
                        w.institution_id, w.pure_uuid, getattr(award_payload, "awards", None)
                    )
                    if work_rows:
                        matched += 1
                    rows.extend(work_rows)

            # Prune only works whose fetch succeeded: a transient error must
            # not wipe known-good rows as "stopped resolving".
            prunable = [w for w in batch if w.doi_normalized not in errored]
            try:
                stats["rows_upserted"] += await _upsert(session, rows)
                stats["pruned"] += await _prune(session, prunable, rows)
                stats["matched_with_grants"] += matched
                await ingest.commit()
            except Exception as exc:
                raise RuntimeError(f"upsert/prune: doi chunk {batch_no}: {exc}") from exc

            if batch_no % PROGRESS_EVERY == 0:
                logger.info(
                    "harvest_work_funders: chunk %d/%d rows_upserted=%d pruned=%d errors=%d",
                    batch_no,
                    (len(works) + WORK_CHUNK - 1) // WORK_CHUNK,
                    stats["rows_upserted"],
                    stats["pruned"],
                    fetch_stats.get("fetch_errors", 0),
                )
    stats["fetch_errors"] = fetch_stats.get("fetch_errors", 0)

    stats["distinct_funders"] = await session.scalar(
        select(func.count(func.distinct(WorkFunder.funder_openalex_id)))
    )
    top = (
        await session.execute(
            select(
                WorkFunder.funder_openalex_id,
                func.max(WorkFunder.funder_name).label("name"),
                func.count().label("works"),
            )
            .group_by(WorkFunder.funder_openalex_id)
            .order_by(text("works DESC"))
            .limit(5)
        )
    ).all()
    stats["top_funders"] = [
        {"funder_openalex_id": r.funder_openalex_id, "name": r.name, "works": r.works} for r in top
    ]
    logger.info("harvest_work_funders: %s", stats)
    # Finalize after the last chunk so a mid-run crash cannot leave a
    # "completed" run whose later chunks rolled back.
    final = await ingest.finish_run("completed", dict(stats))
    await session.commit()
    return final
