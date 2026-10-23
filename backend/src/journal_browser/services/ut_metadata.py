"""ut-metadata Postgres: canonical Twente publications.

Second, read-only database (container ut-metadata-db-1, host 5434). Enabled
by JB_UT_METADATA_DSN; empty DSN or an unreachable server degrades to
"unavailable" (None) and every endpoint keeps its works_stats-only behavior.

Data path for one journal (all names verified live 2026-10-23):
    venue.issn_l
      -> source_identity (entity_type='venues', canonical_id=venue.id)
         source_pk is an upper-case S-id, work_venues stores it lower-cased
      -> work_venues (source_s_id)
      -> work (canonical works)
      -> merged_work_attrs (view; canonical_id = work.id) for the merged
         oa_status / cited_by_count / is_retracted attributes.
"""

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ..config import get_settings

logger = logging.getLogger(__name__)

#: oa_status values observed in merged_work_attrs; anything else (incl.
#: NULL) lands in "unknown".
OA_BUCKETS = ("gold", "hybrid", "green", "bronze", "diamond", "closed", "unknown")

_WORKS_SQL = text(
    """
    SELECT DISTINCT
        w.id,
        coalesce(m.doi, w.doi) AS doi,
        coalesce(m.title, m.canonical_display_name, w.display_name) AS title,
        coalesce(m.publication_year, w.publication_year) AS year,
        coalesce(m.work_type, w.work_type) AS work_type,
        m.oa_status,
        coalesce(m.cited_by_count, 0) AS cited_by_count,
        m.is_retracted
    FROM venue v
    JOIN source_identity si
      ON si.canonical_id = v.id AND si.entity_type = 'venues'
    JOIN work_venues wv ON wv.source_s_id = lower(si.source_pk)
    JOIN work w ON w.id = wv.work_id
    LEFT JOIN merged_work_attrs m ON m.canonical_id = w.id
    WHERE lower(v.issn_l) = lower(:issn_l)
    """
)

_engines: dict[str, AsyncEngine] = {}


def _get_engine(dsn: str) -> AsyncEngine:
    """Build (once per DSN) the read-only ut-metadata engine.

    default_transaction_read_only makes the server reject writes even on
    bug-induced statements; discipline is belt and braces.
    """
    engine = _engines.get(dsn)
    if engine is None:
        if dsn.startswith("postgresql://"):
            dsn = "postgresql+asyncpg://" + dsn[len("postgresql://") :]
        engine = create_async_engine(
            dsn,
            connect_args={"server_settings": {"default_transaction_read_only": "true"}},
            pool_pre_ping=True,
        )
        _engines[dsn] = engine
    return engine


async def ut_works_for_journal(issn_l: str, dsn: str | None = None) -> list[dict[str, Any]] | None:
    """Canonical UT works for the journal; None = not configured/unreachable.

    The DSN parameter exists for tests; production always uses the setting.
    """
    if dsn is None:
        dsn = get_settings().ut_metadata_dsn
    if not dsn:
        return None
    try:
        async with _get_engine(dsn).connect() as conn:
            rows = (await conn.execute(_WORKS_SQL, {"issn_l": issn_l})).mappings().all()
    except Exception:
        logger.warning("ut-metadata unavailable for %s; serving works_stats-only", issn_l)
        return None
    # DISTINCT dedupes venue-identity overlap; key by id for safety.
    return list({row["id"]: dict(row) for row in rows}.values())


def normalize_doi(doi: str | None) -> str | None:
    """Lower-cased bare DOI form for cross-source dedupe ('', None -> None)."""
    if not doi:
        return None
    value = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    return value or None


def oa_buckets(rows: list[dict[str, Any]]) -> dict[str, int]:
    """oa_status distribution over ut-metadata rows; null/other -> unknown."""
    buckets = dict.fromkeys(OA_BUCKETS, 0)
    for row in rows:
        buckets[row["oa_status"] if row["oa_status"] in buckets else "unknown"] += 1
    return buckets


def merge_work_lists(
    ut_rows: list[dict[str, Any]], stats_items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Union of ut-metadata and works_stats work items, deduped by DOI.

    DOI present in both: the ut-metadata row wins its own fields and is
    enriched with the works_stats id/url/fwci/type/cited_by_count.
    works_stats-only items pass through; ut-metadata rows without DOI (or
    without a DOI match) are kept as-is.
    """
    by_doi = {
        doi: item
        for item in stats_items
        if (doi := normalize_doi(item.get("doi"))) is not None
    }
    seen_dois: set[str] = set()
    merged: list[dict[str, Any]] = []
    for row in ut_rows:
        doi = normalize_doi(row["doi"])
        item: dict[str, Any]
        if doi is not None and doi in by_doi:
            stats = by_doi[doi]
            seen_dois.add(doi)
            item = {
                "id": stats["id"],
                "url": stats["url"],
                "doi": row["doi"] or stats["doi"],
                "title": row["title"] or stats["title"],
                "year": row["year"] if row["year"] is not None else stats["year"],
                "oa_status": row["oa_status"],
                "fwci": stats["fwci"],
                "cited_by_count": stats["cited_by_count"],
                "is_retracted": row["is_retracted"],
                "type": stats["type"],
                "work_type": row["work_type"],
                "in_openalex": True,
            }
        else:
            item = {
                "id": f"ut-{row['id']}",
                "url": f"https://doi.org/{row['doi']}" if row["doi"] else None,
                "doi": row["doi"],
                "title": row["title"],
                "year": row["year"],
                "oa_status": row["oa_status"],
                "fwci": None,
                "cited_by_count": row["cited_by_count"] or 0,
                "is_retracted": row["is_retracted"],
                "type": None,
                "work_type": row["work_type"],
                "in_openalex": False,
            }
        merged.append(item)
    merged.extend(item for item in stats_items if normalize_doi(item.get("doi")) not in seen_dois)
    return merged


def sort_work_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """year desc nulls last, cited_by_count desc, title asc."""
    return sorted(
        items,
        key=lambda i: (
            i.get("year") is None,
            -(i.get("year") or 0),
            -(i.get("cited_by_count") or 0),
            (i.get("title") or "").lower(),
        ),
    )
