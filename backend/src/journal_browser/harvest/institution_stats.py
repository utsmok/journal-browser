"""Institution publication statistics (2020+ window, collect only).

One cursor-paged works harvest for the home institution with a minimal
select; payloads land verbatim in source_records, then per-journal x
year x OA-status counts and yearly trend totals are aggregated locally
(never per-request JSONB aggregation). Corresponding-author counts come
from native group_by-style count queries per year (keyless, kept as the
known approximation).
"""

import logging
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from aletheca import AlethecaClient
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..ingest import IngestSession
from ..models import InstitutionTrend, InstitutionWorksStats, Journal, UtWork
from .common import get_home_institution
from .openalex_journals import resolve_home_institution_id

logger = logging.getLogger(__name__)

SOURCE = "openalex"
ENTITY_TYPE = "works_stats"
WINDOW_START = "2020-01-01"
PER_PAGE = 100
OA_FIELDS = ("gold", "hybrid", "green", "bronze", "diamond", "closed")



def openalex_id_to_pk(openalex_id: str | None) -> str:
    return (openalex_id or "").rsplit("/", 1)[-1]


def _oa_status(work: dict[str, Any]) -> str:
    status = ((work.get("open_access") or {}).get("oa_status")) or "closed"
    return status if status in OA_FIELDS else "closed"


async def _source_issn_map(session: AsyncSession) -> dict[str, str]:
    rows = await session.execute(select(Journal.openalex_id, Journal.issn_l))
    return {openalex_id_to_pk(s): issn_l for s, issn_l in rows.all() if s and issn_l}


async def harvest_institution_stats(
    session: AsyncSession, limit: int | None = None
) -> dict[str, Any]:
    settings = get_settings()
    home = await get_home_institution(session)
    client_kwargs: dict[str, Any] = {}
    if settings.openalex_api_key:
        client_kwargs["api_key"] = settings.openalex_api_key

    async with AlethecaClient(**client_kwargs) as client:
        inst_id = settings.institution_openalex_id or await resolve_home_institution_id(
            client, session
        )
        filter_set = f"institutions.id={inst_id}"
        await session.commit()

        ingest = IngestSession(session)
        config = {"filter": filter_set, "from": WINDOW_START}
        await ingest.start_run(SOURCE, ENTITY_TYPE, filter_set, config)

        async def commit_page(_page: int, _cursor: str | None) -> None:
            await ingest.commit()

        issn_by_source = await _source_issn_map(session)
        per_journal_year: Counter[tuple[str, int, str]] = Counter()
        per_year: Counter[tuple[int, str]] = Counter()
        unlinked = 0
        current_year = datetime.now(UTC).year

        # aletheca's iterate does not support field selection; the full
        # work payload lands verbatim in source_records.
        async for item in client.works.iterate(
            page_size=PER_PAGE,
            filters={"institutions.id": inst_id, "from_publication_date": WINDOW_START},
            on_page=commit_page,
        ):
            payload = (
                item
                if isinstance(item, dict)
                else (item.model_dump(mode="json") if hasattr(item, "model_dump") else None)
            )
            if not payload or not payload.get("id"):
                await ingest.record_parse_failure(
                    {"source_pk": None, "reason": "work parse failure"}
                )
                continue
            await ingest.ingest_record(openalex_id_to_pk(payload.get("id")), payload)

            year = payload.get("publication_year")
            if isinstance(year, int) and 2020 <= year <= current_year:
                status = _oa_status(payload)
                per_year[(year, status)] += 1
                source_pk = openalex_id_to_pk(
                    ((payload.get("primary_location") or {}).get("source") or {}).get("id")
                )
                issn_l = issn_by_source.get(source_pk)
                if issn_l:
                    per_journal_year[(issn_l, year, status)] += 1
                else:
                    unlinked += 1
            if limit is not None and ingest.records_seen >= limit:
                logger.info("Reached --limit %s", limit)
                break

        stats = await ingest.finish_run("completed", {"works_unlinked_to_journal": unlinked})

        await _write_journal_stats(session, home.id, per_journal_year)
        corresponding = await _corresponding_counts(client, inst_id)
        await _write_trends(session, home.id, per_year, corresponding)
        await session.commit()
    return stats


def _zero_row(institution_id: int, keys: dict[str, Any]) -> dict[str, Any]:
    row = {f"oa_{s}": 0 for s in OA_FIELDS}
    row.update(institution_id=institution_id, **keys)
    return row


async def _write_journal_stats(
    session: AsyncSession,
    institution_id: int,
    per_journal_year: Counter[tuple[str, int, str]],
    *,
    source: str = "openalex_institution_filter",
) -> None:
    """Full replace of this institution's per-journal stats rows."""
    rows: dict[tuple[str, int], dict[str, Any]] = {}
    for (issn_l, year, status), count in per_journal_year.items():
        row = rows.setdefault(
            (issn_l, year),
            _zero_row(institution_id, {"source": source, "issn_l": issn_l, "year": year}),
        )
        row[f"oa_{status}"] = count
    for row in rows.values():
        row["works_count"] = sum(row[f"oa_{s}"] for s in OA_FIELDS)
    await session.execute(
        delete(InstitutionWorksStats).where(
            InstitutionWorksStats.institution_id == institution_id,
            InstitutionWorksStats.source == source,
        )
    )
    if rows:
        await session.execute(insert(InstitutionWorksStats), list(rows.values()))
    logger.info("institution_works_stats[%s] rows: %d", source, len(rows))


async def write_pure_canon_stats(session: AsyncSession, institution_id: int) -> int:
    """Per-journal/year work counts straight from canonical ut_works.

    Cross-check dimension for the verify job: the OA split is left at zero
    because Pure's access states (eprints/COAR) are not OpenAlex-compatible;
    the OpenAlex dimension remains the OA-split source of truth.
    """
    rows = (
        await session.execute(
            select(
                UtWork.journal_issn_l,
                UtWork.year,
                func.count(),
            )
            .where(
                UtWork.retired_at.is_(None),
                UtWork.journal_issn_l.is_not(None),
            )
            .group_by(UtWork.journal_issn_l, UtWork.year)
        )
    ).all()
    payload = [
        {
            "institution_id": institution_id,
            "source": "pure_canon",
            "issn_l": issn_l,
            "year": year,
            "works_count": count,
        }
        for issn_l, year, count in rows
    ]
    await session.execute(
        delete(InstitutionWorksStats).where(
            InstitutionWorksStats.institution_id == institution_id,
            InstitutionWorksStats.source == "pure_canon",
        )
    )
    if payload:
        await session.execute(insert(InstitutionWorksStats), payload)
    logger.info("institution_works_stats[pure_canon] rows: %d", len(payload))
    return len(payload)


async def _corresponding_counts(client: AlethecaClient, inst_id: str) -> dict[int, int]:
    """Native per-year corresponding-author counts (known approximation)."""
    counts: dict[int, int] = {}
    current_year = datetime.now(UTC).year
    for year in range(2020, current_year + 1):
        try:
            counts[year] = await client.works.count(
                filters={
                    "institutions.id": inst_id,
                    "authorships.is_corresponding": "true",
                    "publication_year": year,
                }
            )
        except Exception as exc:
            logger.warning("corresponding count %s failed: %s", year, exc)
    return counts


async def _write_trends(
    session: AsyncSession,
    institution_id: int,
    per_year: Counter[tuple[int, str]],
    corresponding: dict[int, int],
) -> None:
    """Full replace of the institution's yearly totals."""
    years = {year for (year, _status) in per_year} | set(corresponding)
    rows = [_zero_row(institution_id, {"year": year}) for year in sorted(years)]
    for row in rows:
        row["works_count"] = sum(
            count for (year, status), count in per_year.items() if year == row["year"]
        )
        row["corresponding_count"] = corresponding.get(row["year"])
    await session.execute(
        delete(InstitutionTrend).where(InstitutionTrend.institution_id == institution_id)
    )
    if rows:
        await session.execute(insert(InstitutionTrend), rows)
    logger.info("institution_trends years: %d", len(rows))
