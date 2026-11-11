"""Refresh denormalized search state.

Global columns on journals (latest_quartile, latest_apc_euro) and the
per-institution journal_flags rows (works_count, deal_covered,
works_window_plus, browse_excluded). One idempotent statement per column.
Call the matching refresh at the end of any job that changes the underlying
rows:
- refresh_institution_stats   after stats writes (jobs/harvest_stats.py,
                              the pure full sweep in jobs/harvest_pure.py,
                              admin window edits)
- refresh_quartiles           after scimago ingest (jobs/ingest_scimagojr.py)
- refresh_deal_flags          after deal-register changes (curation)
- refresh_apcs                after OpenAPC ingest

The SQL lives here so the alembic backfill and the jobs share one source.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..ingest import bump_cache_epoch
from ..models import Institution

# Decision 16 (docs/decisions.md): proceedings-like titles with no deal and
# no institution works are hidden from browse. Recomputed wholesale so deal
# or works changes clear the flag too. The IS DISTINCT FROM guard skips the
# row write when the value is unchanged: PostgreSQL versions EVERY update,
# so an unguarded refresh of 352k flags rows writes ~2.1 GB of dead tuples
# nightly (the journal_flags bloat reclaimed by migration 0039).
BROWSE_EXCLUDED_SQL = text(
    """
    UPDATE journal_flags f SET browse_excluded =
        (coalesce(j.title, '') ~*
         '\\y(conference|proceedings|symposium|workshop|abstracts|meetings)\\y')
        AND NOT f.deal_covered
        AND f.works_count = 0
    FROM journals j
    WHERE j.issn_l = f.issn_l AND f.institution_id = :iid
      AND f.browse_excluded IS DISTINCT FROM (
          (coalesce(j.title, '') ~*
           '\\y(conference|proceedings|symposium|workshop|abstracts|meetings)\\y')
          AND NOT f.deal_covered
          AND f.works_count = 0)
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

# The card counts the canonical (Pure) corpus only — the same population the
# works tab serves. openalex_institution_filter rows stay in the table for
# the OA split; letting them fill years the canon pass has no row for is what
# made the card show 1112 where the tab showed 1018 (LNCS, 2026-11-08). The
# LEFT JOIN supplies 0 for journals without canon stats rows (the former
# reset statement's job) so one guarded write replaces two full-table rewrites.
WORKS_COUNT_SQL = text(
    """
    UPDATE journal_flags f SET works_count = coalesce(s.n, 0)
    FROM journals j
    LEFT JOIN (
        SELECT issn_l, sum(works_count) AS n
        FROM institution_works_stats
        WHERE institution_id = :iid AND source = 'pure_canon'
        GROUP BY issn_l
    ) s ON s.issn_l = j.issn_l
    WHERE f.issn_l = j.issn_l AND f.institution_id = :iid
      AND f.works_count IS DISTINCT FROM coalesce(s.n, 0)
    """
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
      AND f.works_window_plus IS DISTINCT FROM coalesce(p.total, 0)
    """
)

# Same guard pattern on the shared journals columns: the RIGHT JOIN keeps
# journals that dropped out of the source table so their column clears,
# and unchanged rows skip the write entirely.
QUARTILES_SQL = text(
    """
    UPDATE journals j SET latest_quartile = q.best
    FROM (
        SELECT DISTINCT ON (issn_l) issn_l, best_quartile AS best
        FROM scimagojr_metrics
        WHERE best_quartile IS NOT NULL
        ORDER BY issn_l, year DESC
    ) q
    RIGHT JOIN journals jj ON jj.issn_l = q.issn_l
    WHERE j.issn_l = jj.issn_l
      AND j.latest_quartile IS DISTINCT FROM q.best
    """
)

# Mirrors the OpenAPC fallback in attach_apc_display: the newest period with
# a known cost wins, and the value is that period's highest single reported
# APC (a real observed price — period means average multi-article years).
APC_SQL = text(
    """
    UPDATE journals j SET latest_apc_euro = a.euro_max
    FROM (
        SELECT DISTINCT ON (issn_l) issn_l, euro_max
        FROM journal_apc_aggregates
        WHERE euro_max IS NOT NULL
        ORDER BY issn_l, period DESC
    ) a
    RIGHT JOIN journals jj ON jj.issn_l = a.issn_l
    WHERE j.issn_l = jj.issn_l
      AND j.latest_apc_euro IS DISTINCT FROM a.euro_max
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
      AND f.deal_covered IS DISTINCT FROM EXISTS (
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
    """
)

# A deal counts cap-reached when its cap_usage has an entry for the latest
# entry year whose used >= total; without cap_usage data a deal is never
# cap-reached (never stamp without data). The flag is true only when EVERY
# effective covering deal is cap-reached.
DEAL_CAP_REACHED_SQL = text(
    """
    UPDATE journal_flags f SET deal_cap_reached =
        f.deal_covered AND NOT EXISTS (
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
              AND NOT (
                  d.cap_usage IS NOT NULL
                  AND EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements(d.cap_usage) e
                      WHERE (e->>'year')::int = (
                                SELECT max((x->>'year')::int)
                                FROM jsonb_array_elements(d.cap_usage) x
                            )
                        AND e->>'used' IS NOT NULL
                        AND (e->>'used')::int >= (e->>'total')::int
                  )
              )
        )
    WHERE f.institution_id = :iid
      AND f.deal_cap_reached IS DISTINCT FROM (
          f.deal_covered AND NOT EXISTS (
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
              AND NOT (
                  d.cap_usage IS NOT NULL
                  AND EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements(d.cap_usage) e
                      WHERE (e->>'year')::int = (
                                SELECT max((x->>'year')::int)
                                FROM jsonb_array_elements(d.cap_usage) x
                            )
                        AND e->>'used' IS NOT NULL
                        AND (e->>'used')::int >= (e->>'total')::int
                  )
              )
        )
      )
    """
)


async def refresh_institution_stats(session: AsyncSession, institution: Institution) -> None:
    """Recompute one institution's works_count + window cutoff + exclusion.

    Every statement carries an IS DISTINCT FROM change guard, so an
    unchanged corpus writes zero new row versions (the nightly refresh used
    to churn every flags row non-HOT and bloat the table ~100x)."""
    iid = institution.id
    await session.execute(MATERIALIZE_SQL, {"iid": iid})
    await session.execute(WORKS_COUNT_SQL, {"iid": iid})
    window_end = institution.data_window_end if institution.data_window_end is not None else 9999
    await session.execute(
        WORKS_WINDOW_SQL, {"iid": iid, "ws": institution.data_window_start, "we": window_end}
    )
    await session.execute(DEAL_FLAGS_SQL, {"iid": iid})
    await session.execute(BROWSE_EXCLUDED_SQL, {"iid": iid})
    await bump_cache_epoch(session)


async def refresh_quartiles(session: AsyncSession) -> None:
    # The guarded QUARTILES_SQL clears journals that dropped out of
    # scimagojr_metrics via its RIGHT JOIN; the old blanket reset would
    # rewrite all 144k journals every run.
    await session.execute(QUARTILES_SQL)
    await bump_cache_epoch(session)


async def refresh_apcs(session: AsyncSession) -> None:
    await session.execute(APC_SQL)
    await bump_cache_epoch(session)


async def refresh_deal_flags(session: AsyncSession, institution_id: int) -> None:
    """Recompute one institution's effective coverage + browse exclusion."""
    await session.execute(MATERIALIZE_SQL, {"iid": institution_id})
    await session.execute(DEAL_FLAGS_SQL, {"iid": institution_id})
    await session.execute(DEAL_CAP_REACHED_SQL, {"iid": institution_id})
    await session.execute(BROWSE_EXCLUDED_SQL, {"iid": institution_id})
    await bump_cache_epoch(session)
