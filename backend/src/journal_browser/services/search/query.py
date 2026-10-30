from typing import Any

from sqlalchemy import (
    Numeric,
    Text,
    case,
    cast,
    exists,
    func,
    or_,
    select,
    text,
    type_coerce,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import IssnMap, Journal, JournalApcAggregate, JournalFlags
from .classify import _oa_type
from .currency import _to_eur

# Sort keys: relevance | title | publisher | institution_works | quartile |
# topic | apc | 2yr_mean_citedness
SortKey = str

#: Sort keys whose order column is numeric; their keyset cursors must cast
#: the cursor value to Numeric in both directions (text keys cast to String).
NUMERIC_SORTS = frozenset({"relevance", "institution_works", "2yr_mean_citedness", "apc"})
#: Global corpus cutoff (owner decision 2026-10-23, superseding decision
#: 12): journals with <= 3 works in the 2020+ window. Used by corpus counts
#: and the embed job; serving reads the per-institution journal_flags row
#: (works_window_plus), which applies the scoped institution's window.
WORKS_CUTOFF = Journal.works_2020_plus > 3

#: Trigram similarity threshold for the fuzzy fallback; pg_trgm's built-in
#: default, which the % operator uses via pg_trgm.similarity_threshold.
FUZZY_THRESHOLD = 0.3
#: Any displayable APC info: an OpenAlex list price in any currency, or
#: OpenAPC rows with an observed cost. The has_apc filter matches this; the
#: oa_type gold/diamond split keys on DOAJ's own charge declaration plus
#: observed prices (owner decision 2026-10-28, supersedes the OpenAPC-only
#: split of 2026-10-23).
APC_COST_EXISTS = exists(
    select(1).where(
        JournalApcAggregate.issn_l == Journal.issn_l,
        JournalApcAggregate.euro_max.is_not(None),
    )
)
APC_SHOWN = or_(
    func.coalesce(func.jsonb_array_length(Journal.apc_prices), 0) > 0,
    APC_COST_EXISTS,
)


def _list_price(currency: str) -> Any:
    """OpenAlex list-price APC in one currency; None without an entry."""
    path = text(f"'$[*] ? (@.currency == \"{currency}\")'::jsonpath")
    return cast(
        func.jsonb_path_query_first(Journal.apc_prices, path).op("->>")("price"),
        Numeric,
    )
def _like(term: str) -> str:
    """Escapes LIKE wildcards so user input matches literally."""
    return term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def _norm_issn(term: str) -> str:
    return term.replace("-", "").replace(" ", "").upper()
def base_query(
    *,
    institution_id: int,
    q: str | None = None,
    search_in: str = "all",
    deal: str = "any",
    oa: bool | None = None,
    doaj: bool | None = None,
    quartile: str | None = None,
    topic: str | None = None,
    publisher: str | None = None,
    has_apc: bool | None = None,
    has_works: bool | None = None,
    oa_types: list[str] | None = None,
    fuzzy: bool = False,
):
    """Filtered select with computed columns; search + facet counts share it.

    Scoped to one institution's journal_flags row: the per-institution
    corpus cutoff (works_window_plus > 3) and proceedings exclusion always
    apply."""
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
        select(F.issn_l, F.works_count, F.deal_covered, F.works_window_plus, F.browse_excluded)
        .where(F.institution_id == institution_id)
        .subquery()
    )
    covered = flags.c.deal_covered
    if q and not fuzzy:
        qstr = q.strip()
        # Relevance = title-prefix match tier + FTS rank + prominence nudge
        # from corpus size (works_count). One expression so keyset
        # pagination can compare (rank, issn_l) tuples; the tier spacing
        # dwarfs the other ranges, so title matches always sort first, and
        # within a tier an established flagship outranks a niche journal
        # with a momentarily higher citedness metric.
        rank = (
            case((J.title.ilike(f"{_like(qstr)}%", escape="\\"), 100.0), else_=0.0)
            + func.ts_rank(J.search_vector, func.websearch_to_tsquery(text("'english'"), qstr))
            + func.least(func.coalesce(J.works_count, 0), 100000) * 0.00001
        ).label("rank")
    else:
        rank = cast(text("0"), Numeric).label("rank")
    oa_type = _oa_type(covered)
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
            flags.c.works_count.label("works"),
            J.latest_quartile.label("quartile"),
            twoyr,
            oa_type,
            rank,
            # OpenAlex lists topics primary-first; first entry = primary topic.
            func.coalesce(J.topics.op("->")(0).op("->>")("display_name"), "").label(
                "primary_topic"
            ),
            # Display/sort price: OpenAlex list price (EUR, then USD), else
            # the OpenAPC latest cost. apc_prices order is unspecified, so
            # the currency match goes through jsonb_path_query_first.
            func.coalesce(
                _list_price("EUR"), _list_price("USD"), J.latest_apc_euro
            ).label("apc_price"),
            # Any-source APC presence; the facet pass filters on this.
            APC_SHOWN.label("apc_any"),
        )
        .select_from(J)
        .join(flags, flags.c.issn_l == J.issn_l)
        .where(
            J.type == "journal",
            J.issn_l.is_not(None),
            flags.c.works_window_plus > 3,
            flags.c.browse_excluded.is_not(True),
            *([J.issn_l.not_in(sorted(set(ignored)))] if ignored else []),
        )
    )
    if oa_types:
        query = query.where(oa_type.in_(oa_types))
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
                norm = _norm_issn(qstr)
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
                        J.search_text.ilike(f"{_like(qstr)}%", escape="\\"),
                        *issn_conds,
                    )
                )
            if search_in in ("all", "publisher"):
                conds.append(J.publisher_name.ilike(f"%{_like(qstr)}%", escape="\\"))
            # Topic stays an explicit scope: casting topics to text per row
            # defeats every index, and inside the all-scope OR it forced a
            # seq scan (2s). search_in=topic uses the trgm expression index.
            if search_in == "topic":
                conds.append(cast(J.topics, Text).ilike(f"%{_like(qstr)}%", escape="\\"))
            query = query.where(or_(*conds))
    if deal == "covered":
        query = query.where(flags.c.deal_covered.is_(True))
    elif deal == "not_covered":
        query = query.where(flags.c.deal_covered.is_(False))
    if oa is not None:
        query = query.where(J.is_oa.is_(oa))
    if doaj is not None:
        query = query.where(J.is_in_doaj.is_(doaj))
    if quartile in {"Q1", "Q2", "Q3", "Q4"}:
        query = query.where(J.latest_quartile == quartile)
    if topic:
        query = query.where(J.topics.contains([{"display_name": topic}]))
    if publisher:
        query = query.where(J.publisher_name == publisher)
    if has_apc is not None:
        query = query.where(APC_SHOWN if has_apc else ~APC_SHOWN)
    if has_works is not None:
        query = query.where(
            flags.c.works_count > 0 if has_works else flags.c.works_count == 0
        )
    return query


def _order(sort: SortKey, subq: Any) -> tuple[Any, str]:
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
        return func.coalesce(subq.c.apc_price, 0), "desc"
    if sort == "institution_works":
        return func.coalesce(subq.c.works, 0), "desc"
    if sort == "2yr_mean_citedness":
        return func.coalesce(subq.c.twoyr, 0), "desc"
    return func.coalesce(subq.c.rank, 0), "desc"  # relevance
async def attach_apc_display(session: AsyncSession, items: list[dict[str, Any]]) -> None:
    """Stamp display APC fields onto each item dict in place (page-sized).

    OpenAlex list price wins (EUR, then USD, else first entry), standardized
    to EUR at the Jan 1 rate of the current year (non-EUR sources keep their
    currency only when no rate is available); without one, the OpenAPC
    observed range over the newest two evidence periods, plus per-period
    stats for the tooltip. One keyed query per source table.
    """
    issns = [i["issn_l"] for i in items]
    list_price: dict[str, tuple[str, float]] = {}
    for issn_l, prices in (
        await session.execute(
            select(Journal.issn_l, Journal.apc_prices).where(Journal.issn_l.in_(issns))
        )
    ).all():
        entries = [
            p for p in (prices or []) if isinstance(p, dict) and p.get("price") is not None
        ]
        by_currency = {p.get("currency"): p["price"] for p in entries}
        matched = next((c for c in ("EUR", "USD") if c in by_currency), None)
        if matched:
            list_price[issn_l] = _to_eur(float(by_currency[matched]), matched)
        elif entries:
            list_price[issn_l] = _to_eur(
                float(entries[0]["price"]), str(entries[0].get("currency") or "")
            )

    aggs: dict[str, list[Any]] = {}
    for row in (
        await session.execute(
            select(
                JournalApcAggregate.issn_l,
                JournalApcAggregate.period,
                JournalApcAggregate.article_count,
                JournalApcAggregate.euro_min,
                JournalApcAggregate.euro_max,
                JournalApcAggregate.euro_mean,
            )
            .where(JournalApcAggregate.issn_l.in_(issns))
            .where(JournalApcAggregate.euro_max.is_not(None))
            .order_by(JournalApcAggregate.issn_l, JournalApcAggregate.period.desc())
        )
    ).all():
        aggs.setdefault(row.issn_l, []).append(row)

    for item in items:
        hit = list_price.get(item["issn_l"])
        if hit is not None:
            item.update(
                apc_source="openalex",
                apc_currency=hit[0],
                apc_price=hit[1],
                apc_low=None,
                apc_high=None,
                apc_stats=[],
            )
            continue
        rows = aggs.get(item["issn_l"]) or []
        if not rows:
            item.update(
                apc_source=None,
                apc_currency=None,
                apc_price=None,
                apc_low=None,
                apc_high=None,
                apc_stats=[],
            )
            continue
        window = [r for r in rows if r.period >= rows[0].period - 1]
        lows = [float(r.euro_min if r.euro_min is not None else r.euro_max) for r in window]
        item.update(
            apc_source="openapc",
            apc_currency=None,
            apc_price=None,
            apc_low=min(lows),
            apc_high=max(float(r.euro_max) for r in window),
            apc_stats=[
                {
                    "period": r.period,
                    "article_count": r.article_count,
                    "euro_min": None if r.euro_min is None else float(r.euro_min),
                    "euro_max": float(r.euro_max),
                    "euro_mean": None if r.euro_mean is None else float(r.euro_mean),
                }
                for r in rows
            ],
        )
