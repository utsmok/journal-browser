from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any

from sqlalchemy import (
    Numeric,
    Text,
    and_,
    case,
    cast,
    func,
    or_,
    select,
    text,
    type_coerce,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    DealInstitution,
    DealJournal,
    InstitutionWorksStats,
    IssnMap,
    Journal,
    JournalApcAggregate,
    JournalFlags,
)
from ...vocab import ApcSource, GreenOa
from ..deal_coverage import dj_scope
from ..funder_fit import fit_case
from .classify import oa_type_case
from .recommendable import active_clause, vouched_clause

# Sort keys: relevance | title | publisher | institution_works | quartile |
# topic | apc | 2yr_mean_citedness
SortKey = str

#: Sort keys whose order column is numeric; their keyset cursors must cast
#: the cursor value to Numeric in both directions (text keys cast to String).
NUMERIC_SORTS = frozenset({"relevance", "institution_works", "2yr_mean_citedness", "apc"})
#: Global corpus cutoff (owner decision 2026-10-23, superseding decision
#: 12): journals with <= 3 works in the 2020+ window. Used by corpus counts
#: and the embed job; serving reads the scoped institution's journal_flags
#: row (works_window_plus), whose value is the journal's own OpenAlex works
#: in that institution's window — materialized from counts_by_year, not
#: the institution's works.
WORKS_CUTOFF = Journal.works_2020_plus > 3

#: Trigram similarity threshold for the fuzzy fallback; pg_trgm's built-in
#: default, which the % operator uses via pg_trgm.similarity_threshold.
FUZZY_THRESHOLD = 0.3

#: A price to show: a publisher list price (OpenAlex or DOAJ) or an observed
#: OpenAPC paid amount, both denormalized by harvest.denorm.refresh_apcs.
#: The has_apc filter and its facet count this. The oa_type gold/diamond
#: split keeps its own evidence rule in classify.py (owner decision
#: 2026-10-28).
APC_SHOWN = or_(Journal.list_price_source.is_not(None), Journal.latest_apc_euro.is_not(None))
#: Sort and filter price in EUR, the same choice shown_price labels: the
#: list price, else the mean amount actually paid. NULL when the list
#: price is in a currency without an exchange rate; such journals sort
#: after every EUR price.
APC_PRICE_EURO = case(
    (Journal.list_price_source.is_not(None), Journal.list_price_euro),
    else_=Journal.latest_apc_euro,
)
#: Denormalized columns behind the shown price (harvest.denorm), selected
#: on every results row and read by shown_price.
APC_SHOWN_FIELDS = (
    "apc_source",
    "apc_currency",
    "apc_price",
    "apc_year",
    "apc_original_currency",
    "apc_original_price",
)
#: Green-OA route buckets over the Jisc OPF columns. The facet counts the
#: best allowed route (submitted > accepted > published; "none" = swept but
#: no route, or OA prohibited); the search filter matches the literal
#: per-column mapping from the design doc. jisc columns NULL (never swept)
#: land in no bucket, never in "none" (DOAJ tri-state convention).
GREEN_OA_BEST_ROUTE = case(
    (
        and_(Journal.jisc_in_opf.is_(True), Journal.jisc_oa_prohibited.is_(True)),
        GreenOa.NONE,
    ),
    (Journal.jisc_allows_sa_submitted.is_(True), GreenOa.SUBMITTED),
    (Journal.jisc_allows_sa_accepted.is_(True), GreenOa.ACCEPTED),
    (Journal.jisc_allows_sa_published.is_(True), GreenOa.PUBLISHED),
    (Journal.jisc_in_opf.is_(True), GreenOa.NONE),
    else_=None,
)
GREEN_OA_CONDS: dict[GreenOa, Any] = {
    GreenOa.SUBMITTED: and_(
        Journal.jisc_oa_prohibited.is_not(True),
        Journal.jisc_allows_sa_submitted.is_(True),
    ),
    GreenOa.ACCEPTED: and_(
        Journal.jisc_oa_prohibited.is_not(True),
        Journal.jisc_allows_sa_accepted.is_(True),
    ),
    GreenOa.PUBLISHED: and_(
        Journal.jisc_oa_prohibited.is_not(True),
        Journal.jisc_allows_sa_published.is_(True),
    ),
    GreenOa.NONE: and_(
        Journal.jisc_in_opf.is_(True),
        or_(
            Journal.jisc_oa_prohibited.is_(True),
            and_(
                Journal.jisc_allows_sa_submitted.is_not(True),
                Journal.jisc_allows_sa_accepted.is_not(True),
                Journal.jisc_allows_sa_published.is_not(True),
            ),
        ),
    ),
}


def escape_like(term: str) -> str:
    """Escapes LIKE wildcards so user input matches literally."""
    return term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def normalize_issn(term: str) -> str:
    return term.replace("-", "").replace(" ", "").upper()


def as_filter_list(value: str | Sequence[str] | None) -> list[str] | None:
    """Normalize a scalar or sequence filter value to a non-empty list of strings."""
    if value is None:
        return None
    if isinstance(value, str):
        val = str(value.value) if isinstance(value, Enum) else value
        return [val] if val else None
    parts = [str(v.value) if isinstance(v, Enum) else str(v) for v in value if v]
    return parts or None


def base_query(
    *,
    institution_id: int,
    q: str | None = None,
    search_in: str = "all",
    deal: str = "any",
    deal_id: int | None = None,
    oa: bool | None = None,
    doaj: bool | None = None,
    quartile: str | Sequence[str] | None = None,
    topic: str | Sequence[str] | None = None,
    publisher: str | Sequence[str] | None = None,
    has_apc: bool | None = None,
    has_works: bool | None = None,
    oa_types: list[str] | None = None,
    green_oa: GreenOa | str | Sequence[GreenOa | str] | None = None,
    fuzzy: bool = False,
    funder_fit: bool | None = None,
    funder_fit_value: str | Sequence[str] | None = None,
    pub_type: str | Sequence[str] | None = None,
    languages: list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    active: bool = False,
    vouched: bool = False,
):
    """Filtered select with computed columns; search + facet counts share it.

    Browsable corpus: journals above the global window cutoff
    (works_window_plus > 3 — the journal's own OpenAlex works in the
    window, materialized from counts_by_year; not a per-institution
    works count, decision 24), plus every other OpenAlex venue type with at
    least one institution work (book series, conference, ...; owner
    decision 2026-11-04). Scoped to one institution's journal_flags row,
    and the proceedings exclusion always applies.

    An explicit publication-year range (clamped by the caller, both bounds
    set or both None) swaps the denormalized per-journal works count for a
    year-scoped SUM over institution_works_stats. The stats source mirrors
    the flags column's own pipeline (harvest.denorm WORKS_COUNT_SQL:
    pure_canon rows only, LEFT JOIN semantics -> 0 without rows); journal
    attributes, the corpus cutoff (works_window_plus) and the relevance
    rank's global-prominence term stay unfiltered.

    ``active`` and ``vouched`` narrow the corpus to journals the
    recommendation surfaces may suggest (see recommendable.py); both are on
    for every recommendation surface, and the browse list, facets and
    semantic search expose them as user toggles."""
    J = Journal
    F = JournalFlags
    # Admin ignore-list (settings.yaml): hidden from every listing, detail
    # by ISSN still works. Read at call time so admin edits land live.
    # Deferred: get_settings resolves through the package namespace, keeping
    # the search-module monkeypatch seam (tests/test_admin_deals.py) live.
    from journal_browser.services import search

    ignored = search.get_settings().ignored_issns
    # OpenAlex publishes this metric as "two_yr_mean_citedness".
    twoyr = cast(J.summary_stats.op("->>")("two_yr_mean_citedness"), Numeric).label("twoyr")
    flags = (
        select(
            F.issn_l,
            F.works_count,
            F.deal_covered,
            F.deal_cap_reached,
            F.openaire_diamond,
            F.works_window_plus,
            F.browse_excluded,
        )
        .where(F.institution_id == institution_id)
        .subquery()
    )
    # Year-scoped per-journal works (same pure_canon-only population the
    # denormalized column sums, bounded to the clamped range). Outer join:
    # journals without in-range stats rows keep their zero.
    year_active = year_from is not None
    yearly = None
    if year_active:
        yearly = (
            select(
                InstitutionWorksStats.issn_l.label("issn_l"),
                func.sum(InstitutionWorksStats.works_count).label("works_count"),
            )
            .where(
                InstitutionWorksStats.institution_id == institution_id,
                InstitutionWorksStats.source == "pure_canon",
                InstitutionWorksStats.year >= year_from,
                InstitutionWorksStats.year <= year_to,
            )
            .group_by(InstitutionWorksStats.issn_l)
            .subquery()
        )
    year_works = (
        func.coalesce(yearly.c.works_count, 0) if yearly is not None else flags.c.works_count
    )
    covered = flags.c.deal_covered
    openaire_diamond = flags.c.openaire_diamond
    if q and not fuzzy:
        qstr = q.strip()
        # Relevance = title-prefix match tier + FTS rank + two prominence
        # nudges: the journal's global corpus size (works_count) and the
        # scoped institution's own works count (decision 23), so journals
        # UT publishes in win ties over same-named titles with no UT
        # works. One expression so keyset pagination can compare
        # (rank, issn_l) tuples; the tier spacing dwarfs the other
        # ranges, so title matches always sort first, and within a tier
        # an established flagship outranks a niche journal with a
        # momentarily higher citedness metric.
        rank = (
            case((J.title.ilike(f"{escape_like(qstr)}%", escape="\\"), 100.0), else_=0.0)
            + func.ts_rank(J.search_vector, func.websearch_to_tsquery(text("'english'"), qstr))
            + func.least(func.coalesce(J.works_count, 0), 100000) * 0.00001
            + func.least(func.coalesce(year_works, 0), 100000) * 0.00001
        ).label("rank")
    else:
        rank = cast(text("0"), Numeric).label("rank")
    oa_type = oa_type_case(covered, openaire_diamond)
    query = (
        select(
            J.issn_l,
            J.title,
            J.publisher_name,
            J.publisher_canonical,
            J.is_oa,
            J.is_in_doaj,
            J.in_scimago,
            J.last_active_year,
            covered.label("deal_covered"),
            flags.c.deal_cap_reached.label("deal_cap_reached"),
            year_works.label("works"),
            J.latest_quartile.label("quartile"),
            twoyr,
            oa_type,
            rank,
            # OpenAlex lists topics primary-first; first entry = primary topic.
            func.coalesce(J.topics.op("->")(0).op("->>")("display_name"), "").label(
                "primary_topic"
            ),
            # OpenAlex venue type (journal, book series, conference, ...).
            J.type.label("pub_type"),
            # Modal work language (ISO 639-1); NULL = never observed.
            J.language.label("language"),
            # Denormalized price columns for the shown price and the sort
            # key: the list price in EUR, else the mean amount paid.
            J.list_price_source,
            J.list_price_currency,
            J.list_price_amount,
            J.list_price_year,
            J.list_price_euro,
            J.latest_apc_euro,
            J.latest_apc_period,
            APC_PRICE_EURO.label("apc_price"),
            # Any-source APC presence; the facet pass filters on this.
            APC_SHOWN.label("apc_any"),
            # Best green-OA route bucket (facet pass; NULL = never swept).
            GREEN_OA_BEST_ROUTE.label("green_oa"),
            *(
                [
                    # Funder-fit tier for a structured funder (facet pass
                    # only; SQL twin of services.funder_fit, keep in sync).
                    fit_case(
                        oa_type,
                        covered,
                        J.jisc_oa_prohibited,
                        J.jisc_allows_sa_submitted,
                        J.jisc_allows_sa_accepted,
                        J.jisc_allows_sa_published,
                    ).label("funder_fit")
                ]
                if funder_fit
                else []
            ),
        )
        .select_from(J)
        .join(flags, flags.c.issn_l == J.issn_l)
        .where(
            or_(
                and_(J.type == "journal", flags.c.works_window_plus > 3),
                and_(J.type.is_not(None), J.type != "journal", flags.c.works_count > 0),
            ),
            J.issn_l.is_not(None),
            flags.c.browse_excluded.is_not(True),
            *([J.issn_l.not_in(sorted(set(ignored)))] if ignored else []),
        )
    )
    if active:
        query = query.where(active_clause())
    if vouched:
        query = query.where(vouched_clause(covered))
    if yearly is not None:
        # Journals without in-range stats rows must stay listed (works: 0),
        # so the year sum joins outside.
        query = query.outerjoin(yearly, yearly.c.issn_l == J.issn_l)
    if oa_types:
        query = query.where(oa_type.in_(oa_types))
    funder_fit_values = as_filter_list(funder_fit_value)
    if funder_fit_values:
        query = query.where(
            fit_case(
                oa_type,
                covered,
                J.jisc_oa_prohibited,
                J.jisc_allows_sa_submitted,
                J.jisc_allows_sa_accepted,
                J.jisc_allows_sa_published,
            ).in_(funder_fit_values)
        )
    if q:
        qstr = q.strip()
        if fuzzy:
            # Fallback pass: trigram similarity over search_text; the
            # existing trgm GIN index serves the % operator at the
            # pg_trgm default threshold (see FUZZY_THRESHOLD). type_coerce
            # binds the param as text so the text % text operator resolves.
            query = query.where(J.search_text.op("%")(type_coerce(qstr, Text)))
        else:
            tsq = func.websearch_to_tsquery(text("'english'"), q)
            conds = []
            if search_in in ("all", "title"):
                norm = normalize_issn(qstr)
                # ISSN lookup: normalized comparison so hyphens/spaces/case
                # in the query never matter; IssnMap resolves print/online
                # variants to their ISSN-L.
                issn_conds = []
                if norm:
                    issn_conds = [
                        func.upper(func.replace(J.issn_l, "-", "")) == norm,
                        J.issn_l.in_(
                            select(IssnMap.issn_l).where(
                                func.upper(func.replace(IssnMap.issn, "-", "")) == norm
                            )
                        ),
                    ]
                conds.append(
                    or_(
                        J.search_vector.op("@@")(tsq),
                        J.search_text.ilike(f"{escape_like(qstr)}%", escape="\\"),
                        *issn_conds,
                    )
                )
            if search_in in ("all", "publisher"):
                conds.append(J.publisher_name.ilike(f"%{escape_like(qstr)}%", escape="\\"))
            # Topic stays an explicit scope: casting topics to text per row
            # defeats every index, and inside the all-scope OR it forced a
            # seq scan (2s). search_in=topic uses the trgm expression index.
            if search_in == "topic":
                conds.append(cast(J.topics, Text).ilike(f"%{escape_like(qstr)}%", escape="\\"))
            query = query.where(or_(*conds))
    if deal == "covered":
        query = query.where(flags.c.deal_covered.is_(True))
    elif deal == "not_covered":
        query = query.where(flags.c.deal_covered.is_(False))
    if deal_id is not None:
        query = query.where(
            J.issn_l.in_(
                select(DealJournal.issn_l)
                .select_from(DealJournal)
                .join(
                    DealInstitution,
                    (DealInstitution.deal_id == DealJournal.deal_id)
                    & (DealInstitution.institution_id == institution_id),
                )
                .where(
                    DealJournal.deal_id == deal_id,
                    dj_scope(institution_id),
                    DealJournal.excluded.is_not(True),
                )
            )
        )
    if oa is not None:
        query = query.where(J.is_oa.is_(oa))
    if doaj is not None:
        query = query.where(J.is_in_doaj.is_(doaj))
    quartiles = [q for q in (as_filter_list(quartile) or []) if q in {"Q1", "Q2", "Q3", "Q4"}]
    if quartiles:
        query = query.where(J.latest_quartile.in_(quartiles))
    topics = as_filter_list(topic)
    if topics:
        query = query.where(or_(*[J.topics.contains([{"display_name": t}]) for t in topics]))
    publishers = as_filter_list(publisher)
    if publishers:
        query = query.where(J.publisher_name.in_(publishers))
    pub_types = as_filter_list(pub_type)
    if pub_types:
        query = query.where(J.type.in_(pub_types))
    if languages:
        query = query.where(J.language.in_(languages))
    if has_apc is not None:
        query = query.where(APC_SHOWN if has_apc else ~APC_SHOWN)
    if has_works is not None:
        query = query.where(year_works > 0 if has_works else year_works == 0)
    green_oas = as_filter_list(green_oa)
    if green_oas:
        query = query.where(or_(*[GREEN_OA_CONDS[GreenOa(g)] for g in green_oas]))
    return query


def sort_order(sort: SortKey, subq: Any, direction: str | None = None) -> tuple[Any, str]:
    """Returns (order expression, natural direction)."""
    if sort == "title":
        return func.lower(func.coalesce(subq.c.title, "")), "asc"
    if sort == "publisher":
        return func.lower(func.coalesce(subq.c.publisher_name, "")), "asc"
    if sort == "quartile":
        return func.coalesce(subq.c.quartile, ""), "asc"
    if sort == "topic":
        return subq.c.primary_topic, "asc"
    if sort == "apc":
        # Unpriced and unconvertible-currency journals (NULL apc_price) sort
        # after every EUR price in both directions.
        null_sentinel = 1_000_000_000_000.0 if direction == "asc" else 0
        return func.coalesce(subq.c.apc_price, null_sentinel), "desc"
    if sort == "institution_works":
        return func.coalesce(subq.c.works, 0), "desc"
    if sort == "2yr_mean_citedness":
        return func.coalesce(subq.c.twoyr, 0), "desc"
    return func.coalesce(subq.c.rank, 0), "desc"  # relevance


def shown_price(row: Mapping[str, Any]) -> dict[str, Any]:
    """The price shown for one journal, read from its denormalized columns.

    apc_source names the dataset the price comes from: openalex or doaj for
    a publisher list price, openapc for the mean amount actually paid
    (shown only for journals without a list price), None without either.
    apc_price and apc_currency are what to display: a list price in EUR,
    or in its own currency when no exchange rate exists. For a list price
    apc_original_currency and apc_original_price keep the source amount,
    and apc_year is the year that source was last harvested, since neither
    dates its prices. For openapc apc_price is the mean of the newest
    period with a paid article and apc_year that period.
    """
    if row.get("list_price_source"):
        euro = row.get("list_price_euro")
        return {
            "apc_source": row["list_price_source"],
            "apc_currency": "EUR" if euro is not None else row["list_price_currency"],
            "apc_price": float(euro if euro is not None else row["list_price_amount"]),
            "apc_year": row["list_price_year"],
            "apc_original_currency": row["list_price_currency"],
            "apc_original_price": float(row["list_price_amount"]),
        }
    if row.get("latest_apc_euro") is not None:
        return {
            "apc_source": ApcSource.OPENAPC,
            "apc_currency": "EUR",
            "apc_price": float(row["latest_apc_euro"]),
            "apc_year": row["latest_apc_period"],
            "apc_original_currency": None,
            "apc_original_price": None,
        }
    return dict.fromkeys(APC_SHOWN_FIELDS)


def paid_block(rows: Sequence[Any]) -> dict[str, Any]:
    """The OpenAPC paid-amount fields for one journal.

    `rows` are the journal's journal_apc_aggregates rows with a paid
    article, newest period first. apc_low/apc_high span the newest two
    periods and apc_stats list each one. A lowest amount of NULL (a
    period migration 0005 could not split) falls back to the period's
    highest amount.
    """
    window = [r for r in rows if r.period >= rows[0].period - 1] if rows else []
    return {
        "apc_low": min(
            (float(r.euro_min if r.euro_min is not None else r.euro_max) for r in window),
            default=None,
        ),
        "apc_high": max((float(r.euro_max) for r in window), default=None),
        "apc_stats": [
            {
                "period": r.period,
                "article_count": r.article_count,
                "paid_count": r.paid_count,
                "zero_count": r.zero_count,
                "euro_min": None if r.euro_min is None else float(r.euro_min),
                "euro_max": float(r.euro_max),
                "euro_mean": float(r.euro_mean),
            }
            for r in rows
        ],
    }


async def attach_apc_display(session: AsyncSession, items: list[dict[str, Any]]) -> None:
    """Stamp the APC fields onto each item dict in place (page-sized).

    The shown price comes from the row's denormalized columns (shown_price).
    One keyed query adds the OpenAPC paid block (paid_block), filled
    whenever the journal has paid articles, whatever the shown price is.
    """
    for item in items:
        item.update(shown_price(item))
    issns = [i["issn_l"] for i in items]
    aggs: dict[str, list[Any]] = {}
    for row in (
        await session.execute(
            select(
                JournalApcAggregate.issn_l,
                JournalApcAggregate.period,
                JournalApcAggregate.article_count,
                JournalApcAggregate.paid_count,
                JournalApcAggregate.zero_count,
                JournalApcAggregate.euro_min,
                JournalApcAggregate.euro_max,
                JournalApcAggregate.euro_mean,
            )
            .where(JournalApcAggregate.issn_l.in_(issns), JournalApcAggregate.euro_max > 0)
            .order_by(JournalApcAggregate.issn_l, JournalApcAggregate.period.desc())
        )
    ).all():
        aggs.setdefault(row.issn_l, []).append(row)

    for item in items:
        item.update(paid_block(aggs.get(item["issn_l"]) or []))
