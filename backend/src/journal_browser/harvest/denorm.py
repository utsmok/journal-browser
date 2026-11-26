"""Refresh denormalized search state.
Global columns on journals (latest_quartile, the APC columns) and the
per-institution journal_flags rows (works_count, deal_covered,
works_window_plus, browse_excluded). One idempotent statement per column.
Call the matching refresh at the end of any job that changes the underlying
rows:
- refresh_institution_stats   after stats writes (jobs/harvest_stats.py,
                              the pure full sweep in jobs/harvest_pure.py,
                              admin window edits)
- refresh_quartiles           after scimago ingest (jobs/ingest_scimagojr.py)
- refresh_deal_flags          after deal-register changes (curation)
- refresh_apcs                after OpenAPC ingest, and after the OpenAlex
                              journals or DOAJ harvest (they set list prices)

The SQL lives here so the alembic backfill and the jobs share one source.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from sqlalchemy import Integer, bindparam, cast, func, or_, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from .. import currency
from ..ingest import bump_cache_epoch
from ..models import Institution, Journal
from ..vocab import ApcSource

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
        -- Scimago marks a listed title without a quartile with "-".
        WHERE best_quartile IN ('Q1', 'Q2', 'Q3', 'Q4')
        ORDER BY issn_l, year DESC
    ) q
    RIGHT JOIN journals jj ON jj.issn_l = q.issn_l
    WHERE j.issn_l = jj.issn_l
      AND j.latest_quartile IS DISTINCT FROM q.best
    """
)

# Observed paid amount: the mean paid amount of the journal's newest OpenAPC
# period with at least one paid article. Articles paid under a deal reach
# OpenAPC as €0 and rows without an amount as NULL, so only periods whose
# highest amount is above zero qualify. A journal whose newest rows are all
# €0 keeps its last period with real payments instead of reading as free.
PAID_APC_SQL = text(
    """
    UPDATE journals j
    SET latest_apc_euro = a.euro_mean, latest_apc_period = a.period
    FROM (
        SELECT DISTINCT ON (issn_l) issn_l, period, euro_mean
        FROM journal_apc_aggregates
        WHERE euro_max > 0
        ORDER BY issn_l, period DESC
    ) a
    RIGHT JOIN journals jj ON jj.issn_l = a.issn_l
    WHERE j.issn_l = jj.issn_l
      AND (j.latest_apc_euro IS DISTINCT FROM a.euro_mean
           OR j.latest_apc_period IS DISTINCT FROM a.period)
    """
)

# The publisher's list price, separate from the paid amount above: journal
# column -> bound parameter of the bulk update (a parameter may not carry
# the name of a column the statement updates).
LIST_PRICE_BINDS = {
    "list_price_source": "b_source",
    "list_price_currency": "b_currency",
    "list_price_amount": "b_amount",
    "list_price_year": "b_year",
    "list_price_euro": "b_euro",
}


@dataclass(frozen=True)
class ListPrice:
    """One publisher list price.

    `euro` is None when the original currency has no exchange rate; the
    price is then shown in its own currency and sorts after every EUR price.
    """

    source: ApcSource
    currency: str
    amount: float
    year: int | None
    euro: float | None


def _price_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _openalex_entry(entries: list[dict[str, Any]]) -> tuple[str, float]:
    """(currency, price) of the entry to show from an OpenAlex apc_prices
    list. One source lists the same price in several currencies, so the
    EUR entry needs no conversion and USD is next. Beyond those, an entry
    that converts to EUR beats one in a currency without an exchange rate;
    the first entry breaks the remaining ties."""
    order = sorted(
        range(len(entries)),
        key=lambda i: (
            {"EUR": 0, "USD": 1}.get(entries[i]["currency"], 2),
            currency.year_rate(entries[i]["currency"]) is None,
            i,
        ),
    )
    chosen = entries[order[0]]
    return chosen["currency"], chosen["price"]


def _norm_currency(value: Any) -> str | None:
    code = str(value or "").strip().upper()
    return code if len(code) == 3 and code.isalpha() else None


def select_list_price(
    *,
    apc_prices: Any = None,
    doaj_apc_max: float | None = None,
    doaj_apc_currency: str | None = None,
    openalex_year: int | None = None,
    doaj_year: int | None = None,
) -> ListPrice | None:
    """Pick the publisher list price from the stored source payloads.

    OpenAlex apc_prices wins, else the DOAJ maximum APC. Neither source
    dates its price, so the year is the year that source was last
    harvested for the journal.
    """
    entries: list[dict[str, Any]] = []
    for p in apc_prices if isinstance(apc_prices, list) else []:
        if not isinstance(p, dict) or not _price_number(p.get("price")):
            continue
        amount = float(p["price"])
        code = _norm_currency(p.get("currency"))
        if amount > 0 and code is not None:
            entries.append({"currency": code, "price": amount})
    if entries:
        code, amount = _openalex_entry(entries)
        source, year = ApcSource.OPENALEX, openalex_year
    elif (
        doaj_apc_max is not None
        and float(doaj_apc_max) > 0
        and (code := _norm_currency(doaj_apc_currency)) is not None
    ):
        amount = float(doaj_apc_max)
        source, year = ApcSource.DOAJ, doaj_year
    else:
        return None
    shown_in, euro = currency.to_eur(amount, code)
    return ListPrice(source, code, amount, year, euro if shown_in == "EUR" else None)


def refresh_list_prices(conn: Connection | Session) -> int:
    """Recompute the list-price columns on journals; returns rows updated.

    Synchronous on purpose: the jobs call it through
    AsyncSession.run_sync (a Session) and the alembic backfill through
    op.get_bind() (a Connection). Only journals with a price in either
    source, or a stored list price that may have lost its source, are read.
    """
    stored = (
        select(
            Journal.issn_l,
            Journal.apc_prices,
            Journal.doaj_apc_max,
            Journal.doaj_apc_currency,
            cast(func.extract("year", Journal.harvested_at), Integer).label("openalex_year"),
            cast(func.extract("year", Journal.doaj_harvested_at), Integer).label("doaj_year"),
            *(getattr(Journal, name) for name in LIST_PRICE_BINDS),
        )
        .where(
            or_(
                func.coalesce(func.jsonb_array_length(Journal.apc_prices), 0) > 0,
                Journal.doaj_apc_max.is_not(None),
                Journal.list_price_source.is_not(None),
            )
        )
        .order_by(Journal.issn_l)
    )
    changed: list[dict[str, Any]] = []
    for row in conn.execute(stored).mappings():
        price = select_list_price(
            apc_prices=row.apc_prices,
            doaj_apc_max=row.doaj_apc_max,
            doaj_apc_currency=row.doaj_apc_currency,
            openalex_year=row.openalex_year,
            doaj_year=row.doaj_year,
        )
        values = _list_price_values(price)
        if any(row[name] != value for name, value in values.items()):
            changed.append(
                {
                    "b_issn_l": row.issn_l,
                    **{bind: values[name] for name, bind in LIST_PRICE_BINDS.items()},
                }
            )
    if changed:
        journals = Journal.__table__
        conn.execute(
            journals.update()
            .where(journals.c.issn_l == bindparam("b_issn_l"))
            .values(**{name: bindparam(bind) for name, bind in LIST_PRICE_BINDS.items()}),
            changed,
        )
    return len(changed)


def _list_price_values(price: ListPrice | None) -> dict[str, Any]:
    """Column values for one journal's list price (all NULL without one)."""
    return {
        "list_price_source": price.source.value if price else None,
        "list_price_currency": price.currency if price else None,
        "list_price_amount": _money(price.amount) if price else None,
        "list_price_year": price.year if price else None,
        "list_price_euro": _money(price.euro) if price and price.euro is not None else None,
    }


def _money(value: float) -> Decimal:
    """Two decimals, the storage scale. The comparison against the stored
    Numeric needs a Decimal: a float like 852.12 never equals it."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


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


# Diamond evidence from the OpenAIRE facts store: the journal carries at
# least one non-retired work whose OpenAIRE record says isInDiamondJournal.
# Second evidence source beside DOAJ in search/classify (2026-11-13).
OPENAIRE_DIAMOND_SQL = text(
    """
    UPDATE journal_flags f SET openaire_diamond = EXISTS (
        SELECT 1
        FROM openaire_work_facts oaf
        JOIN works w
          ON w.institution_id = oaf.institution_id
         AND w.pure_uuid = oaf.pure_uuid
        WHERE oaf.institution_id = f.institution_id
          AND oaf.diamond
          AND w.journal_issn_l = f.issn_l
          AND w.retired_at IS NULL
    )
    WHERE f.institution_id = :iid
      AND f.openaire_diamond IS DISTINCT FROM EXISTS (
        SELECT 1
        FROM openaire_work_facts oaf
        JOIN works w
          ON w.institution_id = oaf.institution_id
         AND w.pure_uuid = oaf.pure_uuid
        WHERE oaf.institution_id = f.institution_id
          AND oaf.diamond
          AND w.journal_issn_l = f.issn_l
          AND w.retired_at IS NULL
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
    await session.execute(OPENAIRE_DIAMOND_SQL, {"iid": iid})
    await session.execute(BROWSE_EXCLUDED_SQL, {"iid": iid})
    await bump_cache_epoch(session)


async def refresh_quartiles(session: AsyncSession) -> None:
    # The guarded QUARTILES_SQL clears journals that dropped out of
    # scimagojr_metrics via its RIGHT JOIN; the old blanket reset would
    # rewrite all 144k journals every run.
    await session.execute(QUARTILES_SQL)
    await bump_cache_epoch(session)


async def refresh_apcs(session: AsyncSession) -> None:
    """Recompute the paid amount and the list price on every journal."""
    await session.execute(PAID_APC_SQL)
    await session.run_sync(refresh_list_prices)
    await bump_cache_epoch(session)


async def refresh_deal_flags(session: AsyncSession, institution_id: int) -> None:
    """Recompute one institution's effective coverage + browse exclusion."""
    await session.execute(MATERIALIZE_SQL, {"iid": institution_id})
    await session.execute(DEAL_FLAGS_SQL, {"iid": institution_id})
    await session.execute(DEAL_CAP_REACHED_SQL, {"iid": institution_id})
    await session.execute(BROWSE_EXCLUDED_SQL, {"iid": institution_id})
    await bump_cache_epoch(session)
