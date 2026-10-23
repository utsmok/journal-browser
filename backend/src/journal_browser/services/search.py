"""Journal search: Postgres FTS + facets + keyset pagination."""

import base64
import json
from typing import Any

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
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import IssnMap, Journal, JournalApcAggregate

SortKey = str  # relevance | title | institution_works | 2yr_mean_citedness


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


#: Corpus cutoff (owner decision 2026-10-23, superseding decision 12):
#: journals with <= 3 works in the 2020+ window are presentation-excluded.
WORKS_CUTOFF = Journal.works_2020_plus > 3

#: Paper-mill cleanup (owner-approved 2026-10-23): conference-like titles
#: with no deal coverage and no UT works are presentation-excluded (data
#: stays in the table). 943 journals on the dev DB. The flag is a
#: denormalized column kept fresh by the denorm refreshes
#: (harvest/denorm.py) — the live regex it replaces cost ~4x on every
#: unscoped search.
PROCEEDINGS_EXCLUSION = Journal.browse_excluded.is_not(True)

#: Trigram similarity threshold for the fuzzy fallback; pg_trgm's built-in
#: default, which the % operator uses via pg_trgm.similarity_threshold.
FUZZY_THRESHOLD = 0.3

APC_EXISTS = exists(select(1).where(JournalApcAggregate.issn_l == Journal.issn_l))

#: Per-journal OA type (owner-approved 2026-10-23). DOAJ = fully-OA venue;
#: OpenAPC evidence on a DOAJ journal splits gold vs diamond; a covered
#: non-DOAJ journal is hybrid via the agreement; rest is subscription.
#: Per-work UtWork oa_status is deliberately unused: it only covers Twente
#: publications, not the venue.
OA_TYPE = case(
    (and_(Journal.is_in_doaj.is_(True), APC_EXISTS), "gold"),
    (Journal.is_in_doaj.is_(True), "diamond"),
    (Journal.deal_covered_home.is_(True), "hybrid"),
    else_="subscription",
).label("oa_type")


def oa_type_value(is_in_doaj: bool | None, has_apc: bool, deal_covered: bool) -> str:
    """Python mirror of the OA_TYPE SQL case, for the detail endpoint."""
    if is_in_doaj:
        return "gold" if has_apc else "diamond"
    return "hybrid" if deal_covered else "subscription"


def _like(term: str) -> str:
    """Escapes LIKE wildcards so user input matches literally."""
    return term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def _norm_issn(term: str) -> str:
    return term.replace("-", "").replace(" ", "").upper()


def base_query(
    *,
    q: str | None = None,
    search_in: str = "all",
    deal: str = "any",
    oa: bool | None = None,
    doaj: bool | None = None,
    quartile: str | None = None,
    topic: str | None = None,
    publisher: str | None = None,
    has_apc: bool | None = None,
    fuzzy: bool = False,
):
    """Filtered select with computed columns; search + facet counts share it.

    The corpus cutoff (works_2020_plus > 3) always applies."""
    J = Journal
    # OpenAlex publishes this metric as "two_yr_mean_citedness".
    twoyr = cast(J.summary_stats.op("->>")("two_yr_mean_citedness"), Numeric).label("twoyr")
    covered = J.deal_covered_home.label("deal_covered")
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
    query = select(
        J.issn_l,
        J.title,
        J.publisher_name,
        J.is_oa,
        J.is_in_doaj,
        J.in_scimago,
        J.last_active_year,
        covered,
        func.coalesce(J.home_works_count, 0).label("twente_works"),
        J.latest_quartile.label("quartile"),
        twoyr,
        OA_TYPE,
        rank,
    ).where(WORKS_CUTOFF, J.type == "journal", J.issn_l.is_not(None), PROCEEDINGS_EXCLUSION)
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
        query = query.where(J.deal_covered_home.is_(True))
    elif deal == "not_covered":
        query = query.where(J.deal_covered_home.is_(False))
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
        query = query.where(APC_EXISTS if has_apc else ~APC_EXISTS)
    return query


def _order(sort: SortKey, subq: Any) -> tuple[Any, str]:
    """Returns (order expression, direction)."""
    if sort == "title":
        return func.lower(func.coalesce(subq.c.title, "")), "asc"
    if sort == "institution_works":
        return func.coalesce(subq.c.twente_works, 0), "desc"
    if sort == "2yr_mean_citedness":
        return func.coalesce(subq.c.twoyr, 0), "desc"
    return func.coalesce(subq.c.rank, 0), "desc"  # relevance


async def search_journals(
    session: AsyncSession,
    *,
    q: str | None = None,
    search_in: str = "all",
    deal: str = "any",
    oa: bool | None = None,
    doaj: bool | None = None,
    quartile: str | None = None,
    topic: str | None = None,
    publisher: str | None = None,
    has_apc: bool | None = None,
    sort: SortKey = "relevance",
    cursor: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    filters = dict(
        q=q,
        search_in=search_in,
        deal=deal,
        oa=oa,
        doaj=doaj,
        quartile=quartile,
        topic=topic,
        publisher=publisher,
        has_apc=has_apc,
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
    tiebreak = subq.c.issn_l
    keyset = parse_cursor(cursor)

    if direction == "desc":
        page_q = select(subq).order_by(order_col.desc(), tiebreak.desc())
        if keyset:
            page_q = page_q.where(
                tuple_(order_col, tiebreak) < tuple_(cast(keyset[0], Numeric), keyset[1])
            )
    else:
        page_q = select(subq).order_by(order_col.asc(), tiebreak.asc())
        if keyset:
            page_q = page_q.where(
                tuple_(order_col, tiebreak) > tuple_(cast(keyset[0], String), keyset[1])
            )
    rows = (await session.execute(page_q.limit(limit + 1))).all()

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        value_col = {
            "title": "title",
            "institution_works": "twente_works",
            "2yr_mean_citedness": "twoyr",
            "relevance": "rank",
        }[sort]
        value = getattr(last, value_col)
        # Cursor value must mirror the ordering expression exactly, and can
        # never be NULL: coalesce like _order does (title sorts on
        # lower(title); twoyr/twente_works/rank coalesce to 0).
        if value is None:
            value = "" if sort == "title" else 0
        if sort == "title":
            value = value.lower()
        next_cursor = encode_cursor(
            float(value) if isinstance(value, (int, float)) else value, last.issn_l
        )

    items = []
    for row in rows:
        item = dict(row._mapping)
        item["twoyr_mean_citedness"] = (
            float(item.pop("twoyr")) if item.get("twoyr") is not None else None
        )
        item.pop("rank", None)
        items.append(item)

    # Most-recent OpenAPC period per journal for the page only (<= limit
    # rows); one extra keyed query beats a lateral join on every page.
    if rows:
        apc_rows = (
            await session.execute(
                select(
                    JournalApcAggregate.issn_l,
                    JournalApcAggregate.period,
                    JournalApcAggregate.euro_mean,
                )
                .where(JournalApcAggregate.issn_l.in_([r.issn_l for r in rows]))
                .order_by(JournalApcAggregate.issn_l, JournalApcAggregate.period.desc())
            )
        ).all()
        latest: dict[str, tuple[Any, Any]] = {}
        for r in apc_rows:
            latest.setdefault(r.issn_l, (r.period, r.euro_mean))
        for item in items:
            hit = latest.get(item["issn_l"])
            item["apc_period"] = str(hit[0]) if hit else None
            item["apc_euro_mean"] = float(hit[1]) if hit and hit[1] is not None else None

    facets, facet_total = await facet_counts(session, **filters)
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
    q: str | None,
    search_in: str = "all",
    deal: str = "any",
    oa: bool | None = None,
    doaj: bool | None = None,
    quartile: str | None = None,
    topic: str | None = None,
    publisher: str | None = None,
    has_apc: bool | None = None,
) -> tuple[dict[str, dict[str, int]], int]:
    """Facet counts over the query-filtered set. Each facet's own filter is
    excluded so a chip shows what selecting it would yield; all other active
    filters apply. The corpus cutoff always applies, and deal counts always
    reflect the home institution."""

    async def _one(subquery: Any, *counts: Any) -> tuple[int, list[int]]:
        row = (
            await session.execute(
                select(func.count(), *[func.sum(case((c, 1), else_=0)) for c in counts])
            )
        ).one()
        return int(row[0] or 0), [int(v or 0) for v in row[1:]]

    # One pass over the full filter set answers the total and every facet
    # whose own filter is inactive; only active filters need a second pass.
    base = base_query(
        q=q,
        search_in=search_in,
        deal=deal,
        oa=oa,
        doaj=doaj,
        quartile=quartile,
        topic=topic,
        publisher=publisher,
        has_apc=has_apc,
    ).subquery()
    total, (covered, oa_true, doaj_true, q1, q2, q3, q4) = await _one(
        base,
        base.c.deal_covered.is_(True),
        base.c.is_oa.is_(True),
        base.c.is_in_doaj.is_(True),
        base.c.quartile == "Q1",
        base.c.quartile == "Q2",
        base.c.quartile == "Q3",
        base.c.quartile == "Q4",
    )
    facets: dict[str, dict[str, int]] = {
        "deal_coverage": {"covered": covered, "not_covered": total - covered},
        "oa": {"true": oa_true, "false": total - oa_true},
        "doaj": {"true": doaj_true, "false": total - doaj_true},
        "quartile": {"Q1": q1, "Q2": q2, "Q3": q3, "Q4": q4},
    }
    # Variants drop exactly their own filter and keep everything else.
    common = dict(q=q, search_in=search_in, deal=deal, oa=oa, doaj=doaj, quartile=quartile)
    if deal != "any":
        d = base_query(
            **{**common, "topic": topic, "publisher": publisher, "has_apc": has_apc}
        ).subquery()
        d_total, (d_covered,) = await _one(d, d.c.deal_covered.is_(True))
        facets["deal_coverage"] = {"covered": d_covered, "not_covered": d_total - d_covered}
    if oa is not None:
        o = base_query(
            **{**common, "topic": topic, "publisher": publisher, "has_apc": has_apc}
        ).subquery()
        o_total, (o_true,) = await _one(o, o.c.is_oa.is_(True))
        facets["oa"] = {"true": o_true, "false": o_total - o_true}
    if doaj is not None:
        dj = base_query(
            **{**common, "topic": topic, "publisher": publisher, "has_apc": has_apc}
        ).subquery()
        dj_total, (dj_true,) = await _one(dj, dj.c.is_in_doaj.is_(True))
        facets["doaj"] = {"true": dj_true, "false": dj_total - dj_true}
    if quartile in {"Q1", "Q2", "Q3", "Q4"}:
        qt = base_query(
            **{**common, "topic": topic, "publisher": publisher, "has_apc": has_apc}
        ).subquery()
        qt_total, (w1, w2, w3, w4) = await _one(
            qt,
            qt.c.quartile == "Q1",
            qt.c.quartile == "Q2",
            qt.c.quartile == "Q3",
            qt.c.quartile == "Q4",
        )
        facets["quartile"] = {"Q1": w1, "Q2": w2, "Q3": w3, "Q4": w4}
    elem = func.jsonb_array_elements(
        func.coalesce(Journal.topics, text("'[]'::jsonb"))
    ).table_valued("value", name="t")
    topic_subq = base_query(
        q=q,
        search_in=search_in,
        deal=deal,
        oa=oa,
        doaj=doaj,
        quartile=quartile,
        publisher=publisher,
        has_apc=has_apc,
    ).subquery()
    topic_rows = await session.execute(
        select(
            elem.c.value.op("->>")("display_name").label("topic"),
            func.count().label("n"),
        )
        .select_from(topic_subq, Journal, elem)
        .where(Journal.issn_l == topic_subq.c.issn_l)
        .group_by(text("1"))
        .order_by(text("2 DESC"))
        .limit(15)
    )
    facets["topic"] = {row.topic: int(row.n) for row in topic_rows}

    # Publisher facet: top publisher_name counts in the filtered set, own
    # exact-match filter excluded.
    pub_subq = base_query(
        q=q,
        search_in=search_in,
        deal=deal,
        oa=oa,
        doaj=doaj,
        quartile=quartile,
        topic=topic,
        has_apc=has_apc,
    ).subquery()
    pub_rows = await session.execute(
        select(pub_subq.c.publisher_name, func.count().label("n"))
        .where(pub_subq.c.publisher_name.is_not(None))
        .group_by(pub_subq.c.publisher_name)
        .order_by(func.count().desc(), pub_subq.c.publisher_name.asc())
        .limit(15)
    )
    facets["publisher"] = {row.publisher_name: int(row.n) for row in pub_rows}

    # APC facet: journals with/without JournalApcAggregate evidence, own
    # has_apc filter excluded so the chips always show both options.
    if has_apc is None:
        apc_base, apc_total = base, total
    else:
        apc_base = base_query(
            q=q,
            search_in=search_in,
            deal=deal,
            oa=oa,
            doaj=doaj,
            quartile=quartile,
            topic=topic,
            publisher=publisher,
        ).subquery()
        apc_total = await session.scalar(select(func.count()).select_from(apc_base)) or 0
    apc_true = (
        await session.scalar(
            select(func.count())
            .select_from(apc_base)
            .where(exists(select(1).where(JournalApcAggregate.issn_l == apc_base.c.issn_l)))
        )
        or 0
    )
    facets["apc"] = {"true": int(apc_true), "false": int(apc_total) - int(apc_true)}
    return facets, total


async def similar_journals(session: AsyncSession, issn_l: str) -> list[dict[str, Any]] | None:
    """Up to 10 cutoff-passing journals sharing >=1 topic with the given
    journal, ranked by shared-topic count then 2-yr citedness. None when
    the journal itself is unknown. Shares base_query, so the corpus cutoff
    and the proceedings exclusion apply here too."""
    self_row = (
        await session.execute(
            select(Journal.issn_l, Journal.topics).where(Journal.issn_l == issn_l.upper())
        )
    ).first()
    if self_row is None:
        return None
    names = [t["display_name"] for t in (self_row.topics or []) if t.get("display_name")]
    if not names:
        return []
    elems = func.jsonb_array_elements(Journal.topics).table_valued("value")
    shared = (
        select(func.count())
        .select_from(elems)
        .where(elems.c.value.op("->>")("display_name").in_(names))
        .scalar_subquery()
        .label("shared_topics")
    )
    subq = (
        base_query()
        .add_columns(shared)
        .where(Journal.issn_l != self_row.issn_l, shared > 0)
        .subquery()
    )
    rows = (
        await session.execute(
            select(subq)
            .order_by(
                subq.c.shared_topics.desc(),
                func.coalesce(subq.c.twoyr, 0).desc(),
                subq.c.issn_l.asc(),
            )
            .limit(10)
        )
    ).all()
    items = []
    for row in rows:
        item = dict(row._mapping)
        item["twoyr_mean_citedness"] = (
            float(item.pop("twoyr")) if item.get("twoyr") is not None else None
        )
        item.pop("rank", None)
        items.append(item)
    return items
