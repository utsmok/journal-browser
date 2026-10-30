from typing import Any

from sqlalchemy import Numeric, String, cast, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from .cursors import encode_cursor, parse_cursor
from .facets import facet_counts
from .query import NUMERIC_SORTS, SortKey, _order, attach_apc_display, base_query


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
    filters = {
        "institution_id": institution_id,
        "q": q,
        "search_in": search_in,
        "deal": deal,
        "oa": oa,
        "doaj": doaj,
        "quartile": quartile,
        "topic": topic,
        "publisher": publisher,
        "has_apc": has_apc,
        "has_works": has_works,
        "oa_types": oa_types,
    }
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
