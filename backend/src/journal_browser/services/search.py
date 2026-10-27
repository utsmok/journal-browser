"""Journal search: Postgres FTS + facets + keyset pagination."""

import asyncio
import base64
import json
import time
import warnings
from datetime import date
from typing import Any

from currency_converter import CurrencyConverter
from sqlalchemy import (
    Numeric,
    String,
    Text,
    and_,
    case,
    cast,
    exists,
    func,
    or_,
    select,
    text,
    tuple_,
    type_coerce,
)
from sqlalchemy import exc as sa_exc
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..harvest.common import cache_epoch
from ..models import IssnMap, Journal, JournalApcAggregate, JournalFlags

_converter: CurrencyConverter | None = None
_converter_year: int | None = None


def _year_rate(currency: str) -> float | None:
    """EUR units per 1 `currency` at Jan 1 of the current year.

    The ECB publishes no fixing on Jan 1 (holiday), so missing-rate linear
    interpolation supplies the Jan 1 rate; fallback_on_wrong_date handles
    dates outside a currency's quoted range. Bundled ECB data refreshes with
    the package; None means "cannot convert" and callers keep the source
    currency.
    """
    global _converter, _converter_year
    year = date.today().year
    if _converter is None or _converter_year != year:
        try:
            _converter = CurrencyConverter(
                fallback_on_missing_rate=True, fallback_on_wrong_date=True
            )
            _converter_year = year
        except Exception:
            return None
    try:
        return float(_converter.convert(1, currency, "EUR", date=date(year, 1, 1)))
    except Exception:
        return None


def _to_eur(price: float, currency: str) -> tuple[str, float]:
    """Standardize a list price to EUR; keep the source currency on failure.

    Returns (currency, price), matching the list_price tuple convention.
    """
    if currency == "EUR":
        return currency, price
    rate = _year_rate(currency)
    if rate is None or rate <= 0:
        return currency, price
    return "EUR", round(price * rate, 2)

# institution_id -> (monotonic time, facets, total); unfiltered browse facets only
_FACET_CACHE: dict[tuple, tuple[float, dict[str, dict[str, int]], int]] = {}

# Sort keys: relevance | title | publisher | institution_works | quartile |
# topic | apc | 2yr_mean_citedness
SortKey = str

#: Sort keys whose order column is numeric; their keyset cursors must cast
#: the cursor value to Numeric in both directions (text keys cast to String).
NUMERIC_SORTS = frozenset({"relevance", "institution_works", "2yr_mean_citedness", "apc"})


def parse_cursor(cursor: str | None) -> tuple[str, str] | None:
    """Decodes a page cursor; raises ValueError when malformed (router → 400)."""
    if not cursor:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        v, k = data["v"], data["k"]
        if not isinstance(v, (str, int, float)) or not isinstance(k, str):
            raise KeyError("bad shape")
        return str(v), k
    except Exception as exc:
        raise ValueError(f"malformed cursor: {cursor[:32]!r}") from exc


def encode_cursor(value: Any, issn_l: str) -> str:
    raw = json.dumps({"v": value, "k": issn_l}, default=str)
    return base64.urlsafe_b64encode(raw.encode()).decode()


#: Global corpus cutoff (owner decision 2026-10-23, superseding decision
#: 12): journals with <= 3 works in the 2020+ window. Used by corpus counts
#: and the embed job; serving reads the per-institution journal_flags row
#: (works_window_plus), which applies the scoped institution's window.
WORKS_CUTOFF = Journal.works_2020_plus > 3

#: Trigram similarity threshold for the fuzzy fallback; pg_trgm's built-in
#: default, which the % operator uses via pg_trgm.similarity_threshold.
FUZZY_THRESHOLD = 0.3

#: Similar-journal list sizes: the Twente/deal-cut lists are teasers, the
#: general list carries the full ten.
SIMILAR_FILTERED_LIMIT = 5
SIMILAR_ALL_LIMIT = 10

APC_EXISTS = exists(select(1).where(JournalApcAggregate.issn_l == Journal.issn_l))

#: Any displayable APC info: an OpenAlex list price in any currency, or
#: OpenAPC rows with an observed cost. The has_apc filter matches this; the
#: oa_type gold/diamond split deliberately stays on APC_EXISTS (OpenAPC
#: evidence only, owner decision 2026-10-23).
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

#: OpenAlex "fully open access" venue flag, an OA-evidence source beside
#: DOAJ membership (2026-10-27): OpenAlex misses DOAJ membership for real
#: OA journals (e.g. MDPI Water), which used to fall through to
#: "subscription". Known charges split gold from diamond.
_OA_EVIDENCE = or_(Journal.is_in_doaj.is_(True), Journal.is_oa.is_(True))
_CHARGED = or_(APC_EXISTS, Journal.latest_apc_euro.is_not(None))

#: Per-journal OA type (owner-approved 2026-10-23; is_oa evidence added
#: 2026-10-27). DOAJ or fully-OA = open venue; known charges split gold vs
#: diamond; a covered non-OA journal is hybrid via the agreement; rest is
#: subscription. Per-work Work oa_status is deliberately unused: it only
#: covers the scoped institution's publications, not the venue.
def _oa_type(deal_covered: Any) -> Any:
    return case(
        (and_(_OA_EVIDENCE, _CHARGED), "gold"),
        (_OA_EVIDENCE, "diamond"),
        (deal_covered.is_(True), "hybrid"),
        else_="subscription",
    ).label("oa_type")

#: Journal OA-type vocabulary (the OA_TYPE values); the oa_type facet
#: multi-selects these with OR semantics.
OA_TYPES = ("gold", "diamond", "hybrid", "subscription")


def oa_type_value(
    is_in_doaj: bool | None, is_oa: bool | None, has_charges: bool, deal_covered: bool
) -> str:
    """Python mirror of the OA_TYPE SQL case, for the detail endpoint."""
    if is_in_doaj or is_oa:
        return "gold" if has_charges else "diamond"
    return "hybrid" if deal_covered else "subscription"


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
    ignored = get_settings().ignored_issns
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


async def search_journals(
    session: AsyncSession,
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
    sort: SortKey = "relevance",
    dir: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
    include_facets: bool = True,
) -> dict[str, Any]:
    filters = dict(
        institution_id=institution_id,
        q=q,
        search_in=search_in,
        deal=deal,
        oa=oa,
        doaj=doaj,
        quartile=quartile,
        topic=topic,
        publisher=publisher,
        has_apc=has_apc,
        has_works=has_works,
        oa_types=oa_types,
    )
    subq = base_query(**filters).subquery()
    total = await session.scalar(select(func.count()).select_from(subq)) or 0
    fuzzy = False
    if not total and q and q.strip():
        # Zero hits for a real query: retry once, fuzzily.
        fuzzy = True
        subq = base_query(**{**filters, "fuzzy": True}).subquery()
        total = await session.scalar(select(func.count()).select_from(subq)) or 0

    order_col, direction = _order(sort, subq)
    if dir in ("asc", "desc"):
        direction = dir
    tiebreak = subq.c.issn_l
    keyset = parse_cursor(cursor)
    # The cursor value type must match the ordering expression: numeric
    # sorts compare against Numeric, text sorts against String.
    value_cast = Numeric if sort in NUMERIC_SORTS else String

    if direction == "desc":
        page_q = select(subq).order_by(order_col.desc(), tiebreak.desc())
        if keyset:
            page_q = page_q.where(
                tuple_(order_col, tiebreak) < tuple_(cast(keyset[0], value_cast), keyset[1])
            )
    else:
        page_q = select(subq).order_by(order_col.asc(), tiebreak.asc())
        if keyset:
            page_q = page_q.where(
                tuple_(order_col, tiebreak) > tuple_(cast(keyset[0], value_cast), keyset[1])
            )
    # The labeled copy of the ordering expression becomes the cursor value:
    # Postgres itself computed it, so it matches the sort collation exactly
    # (Python .lower() and SQL lower() diverge on non-ASCII under C locale).
    page_q = page_q.add_columns(order_col.label("cursor_value"))
    rows = (await session.execute(page_q.limit(limit + 1))).all()

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        value = last._mapping["cursor_value"]
        if value is None:  # only the topic sort orders on a nullable column
            value = ""
        next_cursor = encode_cursor(
            float(value) if isinstance(value, (int, float)) else value, last.issn_l
        )

    items = []
    for row in rows:
        item = dict(row._mapping)
        item.pop("cursor_value", None)
        item["twoyr_mean_citedness"] = (
            float(item.pop("twoyr")) if item.get("twoyr") is not None else None
        )
        item.pop("rank", None)
        items.append(item)

    # Most-recent OpenAPC period per journal for the page only (<= limit
    # rows); one extra keyed query beats a lateral join on every page.
    if rows:
        await attach_apc_display(session, items)

    # Facets only depend on the filter set, never on cursor/page/sort — page
    # turns skip the aggregate and pass the count through instead.
    if include_facets:
        facets, facet_total = await facet_counts(session, **filters)
    else:
        facets, facet_total = {}, total
    return {
        "items": items,
        # The facet base aggregate counts the identical filter set; the only
        # divergence is the fuzzy retry (facets reflect the exact query).
        "total": int(total if fuzzy else facet_total),
        "next_cursor": next_cursor,
        "fuzzy": fuzzy,
        "facets": facets,
    }


async def facet_counts(
    session: AsyncSession,
    *,
    institution_id: int,
    q: str | None,
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
) -> tuple[dict[str, dict[str, int]], int]:
    """Facet counts over the query-filtered set. Each facet's own filter is
    excluded so a chip shows what selecting it would yield; all other active
    filters apply. The corpus cutoff always applies, and deal counts always
    reflect the scoped institution.

    The whole facet set is one pass over the filtered base (the flags join
    dominates): window counts feed the histograms so no statement references
    the base twice, and the topic explode keeps its own statement because
    expanding ~130k topic arrays costs more than every other facet combined.
    Only facets with an active own filter cost a second variant pass."""
    # Unfiltered browse facets are identical for every visitor until the next
    # harvest, so cache them briefly; ~0.6s of aggregates per landing view was
    # the hot path. Bounded staleness (5 min) after a harvest is acceptable.
    cacheable = not any([q, oa, doaj, quartile, topic, publisher, has_apc is not None,
                         has_works is not None, oa_types, deal != "any", search_in != "all"])
    # The ignore-list and the harvest epoch shape the counts; either change
    # invalidates immediately instead of serving stale facets for 24h.
    cache_key = (
        "facets",
        institution_id,
        hash(tuple(sorted(get_settings().ignored_issns))),
        await cache_epoch(session),
    )
    if cacheable:
        hit = _FACET_CACHE.get(cache_key)
        if hit and time.monotonic() - hit[0] < 86400:
            return hit[1], hit[2]
    defaults = dict(
        institution_id=institution_id,
        q=q,
        search_in=search_in,
        deal=deal,
        oa=oa,
        doaj=doaj,
        quartile=quartile,
        topic=topic,
        publisher=publisher,
        has_apc=has_apc,
        has_works=has_works,
        oa_types=oa_types,
    )

    def base_sub(**override: Any) -> Any:
        return base_query(**{**defaults, **override}).subquery()

    def variant_sub(*drop: str) -> Any:
        """The filtered base minus the dropped facet's own filter."""
        restore: dict[str, Any] = {"deal": "any"}
        return base_sub(**{k: restore.get(k) for k in drop})

    async def _flag_counts(sub: Any, *conds: Any) -> tuple[int, list[int]]:
        row = (
            await session.execute(
                select(
                    func.count(),
                    *[func.count().filter(c).label(f"c{i}") for i, c in enumerate(conds)],
                ).select_from(sub)
            )
        ).one()
        return int(row[0] or 0), [int(v or 0) for v in row[1:]]

    def _topic_counts(sub: Any) -> Any:
        """Top-15 topic histogram as its own statement: exploding ~130k topic
        arrays dwarfs the other aggregates, so it must not inflate the shared
        aggregate statement for every request. Implicit LATERAL (valid
        PostgreSQL); the caller silences the lint."""
        elems = func.jsonb_array_elements(
            func.coalesce(Journal.topics, text("'[]'::jsonb"))
        ).table_valued("value", name="t")
        inner = (
            select(
                elems.c.value.op("->>")("display_name").label("k"),
                func.count().label("n"),
            )
            .select_from(sub, Journal, elems)
            .where(Journal.issn_l == sub.c.issn_l)
            .group_by(text("1"))
            .order_by(text("2 DESC"))
            .limit(15)
            .subquery()
        )
        return select(
            func.jsonb_agg(func.jsonb_build_array(inner.c.k, inner.c.n))
        ).scalar_subquery()

    async def _topic_facet(sub: Any) -> dict[str, int]:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=".*cartesian product.*", category=sa_exc.SAWarning
            )
            topics = (await session.execute(select(_topic_counts(sub)))).scalar_one()
        return {k: int(n) for k, n in (topics or [])}

    base = base_sub()
    # One pass over the join: window counts turn the histograms into plain
    # aggregates, so the base is evaluated exactly once with no multi-reference
    # materialization (a shared CTE scanned per aggregate measured ~3x this).
    # apc_any is a select-list column for the same reason the old apc_evidence
    # exists-subquery was: inside a count FILTER it correlates per row (~730ms);
    # as a column the planner uses one semi-join (~40ms).
    counted = (
        select(
            base,
            func.count().over(partition_by=base.c.oa_type).label("oa_n"),
            func.count().over(partition_by=base.c.publisher_name).label("pub_n"),
        )
        .select_from(base)
        .subquery()
    )
    row = (
        await session.execute(
            select(
                func.count().label("total"),
                func.count().filter(counted.c.deal_covered.is_(True)).label("covered"),
                func.count().filter(counted.c.is_oa.is_(True)).label("oa_true"),
                func.count().filter(counted.c.is_in_doaj.is_(True)).label("doaj_true"),
                func.count().filter(counted.c.quartile == "Q1").label("q1"),
                func.count().filter(counted.c.quartile == "Q2").label("q2"),
                func.count().filter(counted.c.quartile == "Q3").label("q3"),
                func.count().filter(counted.c.quartile == "Q4").label("q4"),
                func.count().filter(counted.c.apc_any).label("apc_true"),
                func.count().filter(counted.c.works > 0).label("works_true"),
                func.jsonb_object_agg(counted.c.oa_type, counted.c.oa_n).label(
                    "oa_type_counts"
                ),
                func.jsonb_object_agg(counted.c.publisher_name, counted.c.pub_n)
                .filter(counted.c.publisher_name.is_not(None))
                .label("publisher_counts"),
            ).select_from(counted)
        )
    ).one()
    total = int(row.total or 0)

    def split(n: Any) -> tuple[int, int]:
        t = int(n or 0)
        return t, total - t

    covered, not_covered = split(row.covered)
    oa_true, oa_false = split(row.oa_true)
    doaj_true, doaj_false = split(row.doaj_true)
    apc_true, apc_false = split(row.apc_true)
    works_true, works_false = split(row.works_true)
    facets: dict[str, dict[str, int]] = {
        "deal_coverage": {"covered": covered, "not_covered": not_covered},
        "oa": {"true": oa_true, "false": oa_false},
        "doaj": {"true": doaj_true, "false": doaj_false},
        "quartile": {
            "Q1": int(row.q1 or 0),
            "Q2": int(row.q2 or 0),
            "Q3": int(row.q3 or 0),
            "Q4": int(row.q4 or 0),
        },
        "apc": {"true": apc_true, "false": apc_false},
        "works": {"true": works_true, "false": works_false},
        "oa_type": dict(row.oa_type_counts or {}),
        # Payload bound: top 15 by count, then name (matches the old SQL LIMIT).
        "publisher": dict(
            sorted((row.publisher_counts or {}).items(), key=lambda kv: (-kv[1], kv[0]))[:15]
        ),
    }
    facets["topic"] = await _topic_facet(base)

    # Active own filters need a variant pass (chip shows what selecting it
    # would yield under the remaining filters); inactive facets keep the
    # base counts computed above.
    if deal != "any":
        d = variant_sub("deal")
        d_total, (d_covered,) = await _flag_counts(d, d.c.deal_covered.is_(True))
        facets["deal_coverage"] = {"covered": d_covered, "not_covered": d_total - d_covered}
    if oa is not None:
        o = variant_sub("oa")
        o_total, (o_true,) = await _flag_counts(o, o.c.is_oa.is_(True))
        facets["oa"] = {"true": o_true, "false": o_total - o_true}
    if doaj is not None:
        dj = variant_sub("doaj")
        dj_total, (dj_true,) = await _flag_counts(dj, dj.c.is_in_doaj.is_(True))
        facets["doaj"] = {"true": dj_true, "false": dj_total - dj_true}
    if quartile in {"Q1", "Q2", "Q3", "Q4"}:
        qt = variant_sub("quartile")
        qt_total, (w1, w2, w3, w4) = await _flag_counts(
            qt,
            qt.c.quartile == "Q1",
            qt.c.quartile == "Q2",
            qt.c.quartile == "Q3",
            qt.c.quartile == "Q4",
        )
        facets["quartile"] = {"Q1": w1, "Q2": w2, "Q3": w3, "Q4": w4}
    if oa_types:
        ot = base_sub(oa_types=None)
        counted_ot = (
            select(ot, func.count().over(partition_by=ot.c.oa_type).label("n"))
            .select_from(ot)
            .subquery()
        )
        counts = (
            await session.execute(
                select(func.jsonb_object_agg(counted_ot.c.oa_type, counted_ot.c.n))
            )
        ).scalar_one()
        facets["oa_type"] = dict(counts or {})
    if topic:
        tp = variant_sub("topic")
        facets["topic"] = await _topic_facet(tp)
    if publisher:
        pb = base_sub(publisher=None)
        counted_pb = (
            select(pb, func.count().over(partition_by=pb.c.publisher_name).label("n"))
            .select_from(pb)
            .subquery()
        )
        counts = (
            await session.execute(
                select(
                    func.jsonb_object_agg(counted_pb.c.publisher_name, counted_pb.c.n).filter(
                        counted_pb.c.publisher_name.is_not(None)
                    )
                )
            )
        ).scalar_one()
        # Payload bound: the UI shows the top 15 sorted by count, then name.
        facets["publisher"] = dict(
            sorted((counts or {}).items(), key=lambda kv: (-kv[1], kv[0]))[:15]
        )
    if has_apc is not None:
        apc = base_sub(has_apc=None)
        apc_total, (apc_true,) = await _flag_counts(apc, apc.c.apc_any)
        facets["apc"] = {"true": apc_true, "false": apc_total - apc_true}
    if has_works is not None:
        wk = variant_sub("has_works")
        wk_total, (wk_true,) = await _flag_counts(wk, wk.c.works > 0)
        facets["works"] = {"true": wk_true, "false": wk_total - wk_true}
    if cacheable:
        _FACET_CACHE[cache_key] = (time.monotonic(), facets, total)
    return facets, total


async def similar_journals(
    session: AsyncSession, issn_l: str, institution_id: int
) -> dict[str, Any] | None:
    """Three cutoff-passing similar-journal lists, nearest first in embedding
    space (cosine; jobs/embed_journals.py backfills the vectors):

    - "institution": journals with at least one known institution publication
    - "deals": journals covered by a publication deal
    - "all": unfiltered apart from the base cutoffs

    Falls back to shared-topic ranking (same three lists) when the journal
    has no embedding yet. None when the journal itself is unknown. Shares
    base_query, so the corpus cutoff and proceedings exclusion always apply.
    """
    self_row = (
        await session.execute(
            select(Journal.issn_l, Journal.topics, Journal.embedding).where(
                Journal.issn_l == issn_l.upper()
            )
        )
    ).first()
    if self_row is None:
        return None

    # Scope filters apply to the flags columns exposed by base_query's
    # subquery (works_count / deal_covered are per-institution now).
    scopes = {
        "institution": (lambda s: s.c.works > 0, SIMILAR_FILTERED_LIMIT),
        "deals": (lambda s: s.c.deal_covered.is_(True), SIMILAR_FILTERED_LIMIT),
        "all": (None, SIMILAR_ALL_LIMIT),
    }
    out: dict[str, list[dict[str, Any]]] = {}
    if self_row.embedding is not None:
        # Same iterative HNSW scan as semantic search: the deal/institution
        # cuts filter most rows, exactly the case strict_order handles.
        await session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
        await session.execute(text(f"SET LOCAL hnsw.ef_search = {SIMILAR_ALL_LIMIT * 10}"))
        distance = Journal.embedding.cosine_distance(self_row.embedding).label("dist")
        for key, (cond, limit) in scopes.items():
            subq = (
                base_query(institution_id=institution_id)
                .add_columns(distance)
                .where(Journal.issn_l != self_row.issn_l, Journal.embedding.is_not(None))
                .subquery()
            )
            outer = select(subq).order_by(subq.c.dist.asc(), subq.c.issn_l.asc())
            if cond is not None:
                outer = outer.where(cond(subq))
            rows = (await session.execute(outer.limit(limit))).all()
            out[key] = [_similar_item(row, embedding=True) for row in rows]
        return out

    names = [t["display_name"] for t in (self_row.topics or []) if t.get("display_name")]
    if not names:
        return {"institution": [], "deals": [], "all": []}
    elems = func.jsonb_array_elements(Journal.topics).table_valued("value")
    shared = (
        select(func.count())
        .select_from(elems)
        .where(elems.c.value.op("->>")("display_name").in_(names))
        .scalar_subquery()
        .label("shared_topics")
    )
    for key, (cond, limit) in scopes.items():
        subq = (
            base_query(institution_id=institution_id)
            .add_columns(shared)
            .where(Journal.issn_l != self_row.issn_l, shared > 0)
            .subquery()
        )
        outer = select(subq).order_by(
            subq.c.shared_topics.desc(),
            func.coalesce(subq.c.twoyr, 0).desc(),
            subq.c.issn_l.asc(),
        )
        if cond is not None:
            outer = outer.where(cond(subq))
        rows = (await session.execute(outer.limit(limit))).all()
        out[key] = [_similar_item(row, embedding=False) for row in rows]
    return out


def _similar_item(row: Any, *, embedding: bool) -> dict[str, Any]:
    item = dict(row._mapping)
    item["twoyr_mean_citedness"] = (
        float(item.pop("twoyr")) if item.get("twoyr") is not None else None
    )
    item.pop("rank", None)
    if embedding:
        item["similarity"] = round(1.0 - item.pop("dist"), 4)
        item["shared_topics"] = 0
    return item


async def semantic_search(
    session: AsyncSession,
    q: str,
    institution_id: int,
    limit: int = 40,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Free-text "find journals like this description": encode the query with
    the embedding model (fastembed ONNX, CPU) and rank by cosine distance.
    Shares base_query cutoffs and proceedings exclusion; journals without a
    stored vector are absent. Response rows match search_journals items so
    the frontend table renders them unchanged.

    The (distance, issn_l) order is deterministic for a fixed query and
    embedding set, so paging is a plain decimal offset into it — the cursor
    is only meaningful for the query that produced it, the same contract the
    frontend already honors by resetting on filter/query changes."""
    from .embeddings import encode_query

    offset = 0
    if cursor is not None:
        if not cursor.isdigit():
            raise ValueError("invalid cursor")
        offset = int(cursor)

    # ONNX inference (and the lazy ~130 MB model load) would stall the event
    # loop for every other request; run it in a worker thread.
    query_vec = await asyncio.to_thread(encode_query, q)
    distance = Journal.embedding.cosine_distance(query_vec).label("dist")
    subq = (
        base_query(institution_id=institution_id)
        .add_columns(distance)
        .where(Journal.embedding.is_not(None))
        .subquery()
    )
    # Iterative HNSW scan (pgvector 0.8): strict_order keeps distance
    # ordering exact across the flags join and offset paging, and iterates
    # past ef_search until enough tuples pass the filter, so no silent cap.
    # ef_search scales with paging depth (per-iteration batch); the exact
    # scan this replaced cost ~0.8 s over ~134k vectors.
    await session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
    await session.execute(
        text(f"SET LOCAL hnsw.ef_search = {max(200, offset + limit + 100)}")
    )
    total = (await session.execute(select(func.count()).select_from(subq))).scalar_one()
    rows = (
        await session.execute(
            select(subq)
            .order_by(subq.c.dist.asc(), subq.c.issn_l.asc())
            .offset(offset)
            .limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = []
    for row in rows:
        item = dict(row._mapping)
        item["twoyr_mean_citedness"] = (
            float(item.pop("twoyr")) if item.get("twoyr") is not None else None
        )
        item.pop("rank", None)
        item.pop("dist", None)
        items.append(item)
    if items:
        await attach_apc_display(session, items)
    return {
        "items": items,
        "total": total,
        "next_cursor": str(offset + limit) if has_more else None,
    }
