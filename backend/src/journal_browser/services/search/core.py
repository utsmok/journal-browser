from typing import Any

from sqlalchemy import Numeric, String, cast, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Journal
from ...vocab import GreenOa
from ..funder_fit import JournalFacts, compute_funder_fit
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
    green_oa: GreenOa | str | None = None,
    pub_type: str | None = None,
    languages: list[str] | None = None,
    sort: SortKey = "relevance",
    dir: str | None = None,
    cursor: str | None = None,
    limit: int = 20,
    include_facets: bool = True,
    funder_struct: dict[str, Any] | None = None,
    funder_fit: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
) -> dict[str, Any]:
    # Kwargs bag forwarded to base_query/facet_counts; Any value type keeps
    # the **-unpack out of ty's per-key argument checks (the bag is keyed).
    filters: dict[str, Any] = {
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
        "green_oa": green_oa,
        "pub_type": pub_type,
        "languages": languages,
        "funder_fit_value": funder_fit,
        "year_from": year_from,
        "year_to": year_to,
    }
    fuzzy = False
    subq = base_query(**filters).subquery()
    # The count is only needed when facets will not supply it (page turns)
    # or the fuzzy fallback fired. Zero-hit detection is a LIMIT 1 probe:
    # a full count to learn "empty" costs a whole base pass before the
    # fuzzy retry even starts.
    need_total = not include_facets
    if q and q.strip():
        hit = await session.scalar(select(1).select_from(subq).limit(1))
        if hit is None:
            fuzzy = True
            subq = base_query(**{**filters, "fuzzy": True}).subquery()
            need_total = True
    total: int | None = None
    if need_total:
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

    # Funder fit: the tier engine runs in Python on the page rows; oa_type
    # and deal_covered are already in each item, one keyed query fetches
    # the Jisc green-route columns. funder_struct=None leaves the field off.
    if funder_struct is not None and items:
        jrows = await session.execute(
            select(
                Journal.issn_l,
                Journal.jisc_oa_prohibited,
                Journal.jisc_allows_sa_submitted,
                Journal.jisc_allows_sa_accepted,
                Journal.jisc_allows_sa_published,
            ).where(Journal.issn_l.in_([i["issn_l"] for i in items]))
        )
        jf = {r.issn_l: r for r in jrows}
        for item in items:
            j = jf.get(item["issn_l"])
            fit = compute_funder_fit(
                funder_struct,
                JournalFacts(
                    oa_type=item["oa_type"],
                    prohibited=j.jisc_oa_prohibited if j else None,
                    sa_submitted=j.jisc_allows_sa_submitted if j else None,
                    sa_accepted=j.jisc_allows_sa_accepted if j else None,
                    sa_published=j.jisc_allows_sa_published if j else None,
                    deal_covered=bool(item["deal_covered"]),
                    publisher_name=item["publisher_name"],
                ),
            )
            item["funder_fit"] = {"status": fit.status, "reasons": fit.reasons}

    # Facets only depend on the filter set, never on cursor/page/sort — page
    # turns skip the aggregate and pass the count through instead.
    if include_facets:
        facets, facet_total = await facet_counts(session, funder_struct=funder_struct, **filters)
    else:
        facets, facet_total = {}, total
    return {
        "items": items,
        # The facet base aggregate counts the identical filter set; the only
        # divergence is the fuzzy retry (facets reflect the exact query), so
        # a fuzzy response reports the fuzzy subquery's own count. total is
        # None exactly when the facets will supply the identical number.
        "total": int(total if total is not None else facet_total),
        "next_cursor": next_cursor,
        "fuzzy": fuzzy,
        "facets": facets,
    }
