"""Refresh the denormalized search columns on journals (see models.Journal).

One idempotent UPDATE pair per column. Call the matching refresh at the end
of any job that changes the underlying rows:
- refresh_home_stats       after stats writes (jobs/harvest_stats.py)
- refresh_quartiles        after scimago ingest (jobs/ingest_scimagojr.py)
- refresh_home_deal_flags  after deal-register changes (curation, purge)

The SQL lives here so the alembic backfill and the jobs share one source.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Decision 16 (docs/decisions.md): proceedings-like titles with no deal and
# no UT works are hidden from browse. Recomputed wholesale so deal or UT
# changes clear the flag too. Depends on deal_covered_home and
# home_works_count, so the refresh functions below run it after those.
BROWSE_EXCLUDED_SQL = text(
    """
    UPDATE journals SET browse_excluded =
        (coalesce(title, '') ~*
         '\\y(conference|proceedings|symposium|workshop|abstracts|meetings)\\y')
        AND NOT deal_covered_home
        AND coalesce(home_works_count, 0) = 0
    """
)

RESET_HOME_WORKS_SQL = text("UPDATE journals SET home_works_count = NULL")

# Pure-canonical primary per year (phase 10): one row per (issn_l, year),
# the pure_canon row when the year has one.
HOME_WORKS_SQL = text(
    """
    UPDATE journals j SET home_works_count = s.n
    FROM (
        SELECT issn_l, sum(works_count) AS n
        FROM (
            SELECT DISTINCT ON (issn_l, year) issn_l, year, works_count
            FROM institution_works_stats
            WHERE institution_id = (SELECT id FROM institutions WHERE is_home)
            ORDER BY issn_l, year, (source = 'pure_canon') DESC
        ) per_year
        GROUP BY issn_l
    ) s
    WHERE j.issn_l = s.issn_l
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

# Mirrors attach_latest_apc semantics: the latest period row wins, even when
# its euro_mean is NULL (an aggregate row without amounts is still "latest").
RESET_APC_SQL = text("UPDATE journals SET latest_apc_euro = NULL")

APC_SQL = text(
    """
    UPDATE journals j SET latest_apc_euro = a.euro_mean
    FROM (
        SELECT DISTINCT ON (issn_l) issn_l, euro_mean
        FROM journal_apc_aggregates
        ORDER BY issn_l, period DESC
    ) a
    WHERE j.issn_l = a.issn_l
    """
)

# Full recompute, so deals removed from the register clear the flag too.
DEAL_FLAGS_SQL = text(
    """
    UPDATE journals j SET deal_covered_home = EXISTS (
        SELECT 1
        FROM deal_journals dj
        JOIN deals d ON d.id = dj.deal_id
        JOIN deal_institutions di ON di.deal_id = d.id
        JOIN institutions i ON i.id = di.institution_id AND i.is_home
        WHERE dj.issn_l = j.issn_l AND d.status = 'current'
    )
    """
)


async def refresh_home_stats(session: AsyncSession) -> None:
    await session.execute(RESET_HOME_WORKS_SQL)
    await session.execute(HOME_WORKS_SQL)
    await session.execute(BROWSE_EXCLUDED_SQL)


async def refresh_quartiles(session: AsyncSession) -> None:
    await session.execute(RESET_QUARTILES_SQL)
    await session.execute(QUARTILES_SQL)


async def refresh_apcs(session: AsyncSession) -> None:
    await session.execute(RESET_APC_SQL)
    await session.execute(APC_SQL)


async def refresh_home_deal_flags(session: AsyncSession) -> None:
    await session.execute(DEAL_FLAGS_SQL)
    await session.execute(BROWSE_EXCLUDED_SQL)
