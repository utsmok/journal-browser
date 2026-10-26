"""Refresh denormalized search state.

Global columns on journals (latest_quartile, latest_apc_euro) and the
per-institution journal_flags rows (works_count, deal_covered,
works_window_plus, browse_excluded). One idempotent statement per column.
Call the matching refresh at the end of any job that changes the underlying
rows:
- refresh_institution_stats   after stats writes (jobs/harvest_stats.py)
- refresh_quartiles           after scimago ingest (jobs/ingest_scimagojr.py)
- refresh_deal_flags          after deal-register changes (curation)
- refresh_apcs                after OpenAPC ingest

The SQL lives here so the alembic backfill and the jobs share one source.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Institution

# Decision 16 (docs/decisions.md): proceedings-like titles with no deal and
# no institution works are hidden from browse. Recomputed wholesale so deal
# or works changes clear the flag too.
BROWSE_EXCLUDED_SQL = text(
    """
    UPDATE journal_flags f SET browse_excluded =
        (coalesce(j.title, '') ~*
         '\\y(conference|proceedings|symposium|workshop|abstracts|meetings)\\y')
        AND NOT f.deal_covered
        AND f.works_count = 0
    FROM journals j
    WHERE j.issn_l = f.issn_l AND f.institution_id = :iid
    """
)

# One flags row per journal per hosted institution (full materialization:
# the search path stays a simple indexed join with no missing-row cases).
MATERIALIZE_SQL = text(
    """
    INSERT INTO journal_flags (institution_id, issn_l)
    SELECT :iid, issn_l FROM journals
    ON CONFLICT (institution_id, issn_l) DO NOTHING
    """
)

# Pure-canonical primary per year (phase 10): one row per (issn_l, year),
# the pure_canon row when the year has one.
WORKS_COUNT_SQL = text(
    """
    UPDATE journal_flags f SET works_count = s.n
    FROM (
        SELECT issn_l, sum(works_count) AS n
        FROM (
            SELECT DISTINCT ON (issn_l, year) issn_l, year, works_count
            FROM institution_works_stats
            WHERE institution_id = :iid
            ORDER BY issn_l, year, (source = 'pure_canon') DESC
        ) per_year
        GROUP BY issn_l
    ) s
    WHERE f.issn_l = s.issn_l AND f.institution_id = :iid
    """
)

RESET_WORKS_COUNT_SQL = text(
    "UPDATE journal_flags SET works_count = 0 WHERE institution_id = :iid"
)

# Journal's own works inside THIS institution's data window (the >3 corpus
# cutoff, owner decision 2026-10-23). Left-joined so journals with empty
# counts_by_year reset to 0.
WORKS_WINDOW_SQL = text(
    """
    UPDATE journal_flags f SET works_window_plus = coalesce(p.total, 0)
    FROM journals j
    LEFT JOIN (
        SELECT j2.issn_l,
               sum(CASE WHEN e->>'works_count' ~ '^[0-9]+$'
                        THEN (e->>'works_count')::int ELSE 0 END) AS total
        FROM journals j2, jsonb_array_elements(j2.counts_by_year) e
        WHERE e->>'year' ~ '^[0-9]+$'
          AND (e->>'year')::int BETWEEN :ws AND :we
        GROUP BY j2.issn_l
    ) p ON p.issn_l = j.issn_l
    WHERE f.issn_l = j.issn_l AND f.institution_id = :iid
    """
)

RESET_QUARTILES_SQL = text("UPDATE journals SET latest_quartile = NULL")

QUARTILES_SQL = text(
    """
    UPDATE journals j SET latest_quartile = q.best
    FROM (
        SELECT DISTINCT ON (issn_l) issn_l, best_quartile AS best
        FROM scimagojr_metrics
        WHERE best_quartile IS NOT NULL
        ORDER BY issn_l, year DESC
    ) q
    WHERE j.issn_l = q.issn_l
    """
)

# Mirrors the OpenAPC fallback in attach_apc_display: the newest period with
# a known cost wins, and the value is that period's highest single reported
# APC (a real observed price — period means average multi-article years).
RESET_APC_SQL = text("UPDATE journals SET latest_apc_euro = NULL")

APC_SQL = text(
    """
    UPDATE journals j SET latest_apc_euro = a.euro_max
    FROM (
        SELECT DISTINCT ON (issn_l) issn_l, euro_max
        FROM journal_apc_aggregates
        WHERE euro_max IS NOT NULL
        ORDER BY issn_l, period DESC
    ) a
    WHERE j.issn_l = a.issn_l
    """
)

# Effective per-institution coverage: a current deal the institution
# participates in, via the shared sheet rows — or, when the relation marks
# journal_override, via that institution's scoped deal_journals rows.
DEAL_FLAGS_SQL = text(
    """
    UPDATE journal_flags f SET deal_covered = EXISTS (
        SELECT 1
        FROM deal_journals dj
        JOIN deals d ON d.id = dj.deal_id
        JOIN deal_institutions di ON di.deal_id = d.id
             AND di.institution_id = f.institution_id
        WHERE dj.issn_l = f.issn_l
          AND d.status = 'current'
          AND NOT dj.excluded
          AND dj.institution_id IS NOT DISTINCT FROM
              (CASE WHEN di.journal_override THEN di.institution_id ELSE NULL END)
    )
    WHERE f.institution_id = :iid
    """
)


async def refresh_institution_stats(session: AsyncSession, institution: Institution) -> None:
    """Recompute one institution's works_count + window cutoff + exclusion."""
    iid = institution.id
    await session.execute(MATERIALIZE_SQL, {"iid": iid})
    await session.execute(RESET_WORKS_COUNT_SQL, {"iid": iid})
    await session.execute(WORKS_COUNT_SQL, {"iid": iid})
    window_end = institution.data_window_end or 9999
    await session.execute(
        WORKS_WINDOW_SQL, {"iid": iid, "ws": institution.data_window_start, "we": window_end}
    )
    await session.execute(DEAL_FLAGS_SQL, {"iid": iid})
    await session.execute(BROWSE_EXCLUDED_SQL, {"iid": iid})


async def refresh_quartiles(session: AsyncSession) -> None:
    await session.execute(RESET_QUARTILES_SQL)
    await session.execute(QUARTILES_SQL)


async def refresh_apcs(session: AsyncSession) -> None:
    await session.execute(RESET_APC_SQL)
    await session.execute(APC_SQL)


async def refresh_deal_flags(session: AsyncSession, institution_id: int) -> None:
    """Recompute one institution's effective coverage + browse exclusion."""
    await session.execute(MATERIALIZE_SQL, {"iid": institution_id})
    await session.execute(DEAL_FLAGS_SQL, {"iid": institution_id})
    await session.execute(BROWSE_EXCLUDED_SQL, {"iid": institution_id})
