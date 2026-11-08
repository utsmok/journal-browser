"""ut-metadata Postgres: canonical Twente publications (author pages).

Second, read-only database (container ut-metadata-db-1, host 5434). Enabled
by JB_UT_METADATA_DSN; empty DSN or an unreachable server degrades to
"unavailable" (None) and the author page keeps its Pure-only behavior.
(The journal works tab no longer reads this database — it serves the
works-table population; see services.detail_enrichment.)

Author openalex-only path (names verified live 2026-10-23):
    work_authors (author_a_id)
      -> work (canonical works)
      -> merged_work_attrs (view; canonical_id = work.id) for the merged
         oa_status / cited_by_count / is_retracted attributes.
"""

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ..config import get_settings
from .source_health import record_degraded

logger = logging.getLogger(__name__)

#: oa_status values observed in merged_work_attrs; anything else (incl.
#: NULL) lands in "unknown".
OA_BUCKETS = ("gold", "hybrid", "green", "bronze", "diamond", "closed", "unknown")

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


_AUTHOR_OPENALEX_ONLY_SQL = text(
    """
    SELECT DISTINCT ON (w.id)
        coalesce(nullif(m.title, ''), m.canonical_display_name, w.display_name) AS title,
        coalesce(m.publication_year, w.publication_year) AS year,
        coalesce(m.doi, w.doi) AS doi,
        m.oa_status,
        coalesce(m.work_type, w.work_type) AS work_type,
        m.venue AS venue_name,
        ven.issn_l
    FROM work_authors wa
    JOIN work w ON w.id = wa.work_id
    LEFT JOIN merged_work_attrs m ON m.canonical_id = w.id
    LEFT JOIN pure_item_population pop ON pop.canonical_id = w.id
    LEFT JOIN LATERAL (
        SELECT lower(v.issn_l) AS issn_l
        FROM work_venues wv
        JOIN source_identity si
          ON si.entity_type = 'venues' AND lower(si.source_pk) = wv.source_s_id
        JOIN venue v ON v.id = si.canonical_id
        WHERE wv.work_id = w.id
        LIMIT 1
    ) ven ON true
    WHERE pop.canonical_id IS NULL
      AND lower(wa.author_a_id) = ANY(:aids)
    """
)


async def ut_openalex_only_works_for_author(
    author_a_ids: list[str], dsn: str | None = None
) -> list[dict[str, Any]] | None:
    """Canonical works OpenAlex attributes to any of the author's A-ids
    but the Pure population does not hold; None = not configured or the
    source is unreachable. Raw rows — the caller applies the institution's
    window/type/DOI quality gates. The DSN parameter exists for tests;
    production always uses the setting."""
    if dsn is None:
        dsn = get_settings().ut_metadata_dsn
    if not dsn or not author_a_ids:
        return None
    try:
        async with _get_engine(dsn).connect() as conn:
            rows = (
                (
                    await conn.execute(
                        _AUTHOR_OPENALEX_ONLY_SQL,
                        {"aids": [a.lower() for a in author_a_ids]},
                    )
                )
                .mappings()
                .all()
            )
    except Exception:
        logger.exception("ut-metadata author query failed; serving pure-only works")
        record_degraded("ut-metadata", "author works query failed; serving pure-only")
        return None
    return [dict(row) for row in rows]


def oa_buckets(rows: list[dict[str, Any]]) -> dict[str, int]:
    """oa_status distribution over ut-metadata rows; null/other -> unknown."""
    buckets = dict.fromkeys(OA_BUCKETS, 0)
    for row in rows:
        buckets[row["oa_status"] if row["oa_status"] in buckets else "unknown"] += 1
    return buckets


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
