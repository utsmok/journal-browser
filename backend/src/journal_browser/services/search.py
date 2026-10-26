"""Journal search: Postgres FTS + facets + keyset pagination."""

import asyncio
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

from ..models import IssnMap, Journal, JournalApcAggregate, JournalFlags

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

#: Per-journal OA type (owner-approved 2026-10-23). DOAJ = fully-OA venue;
#: OpenAPC evidence on a DOAJ journal splits gold vs diamond; a covered
#: non-DOAJ journal is hybrid via the agreement; rest is subscription.
#: Per-work Work oa_status is deliberately unused: it only covers the
#: scoped institution's publications, not the venue.
def _oa_type(deal_covered: Any) -> Any:
    return case(
        (and_(Journal.is_in_doaj.is_(True), APC_EXISTS), "gold"),
        (Journal.is_in_doaj.is_(True), "diamond"),
        (deal_covered.is_(True), "hybrid"),
        else_="subscription",
    ).label("oa_type")

#: Journal OA-type vocabulary (the OA_TYPE values); the oa_type facet
#: multi-selects these with OR semantics.
OA_TYPES = ("gold", "diamond", "hybrid", "subscription")


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
            J.latest_apc_euro.label("latest_apc"),
        )
        .select_from(J)
        .join(flags, flags.c.issn_l == J.issn_l)
        .where(
            J.type == "journal",
            J.issn_l.is_not(None),
            flags.c.works_window_plus > 3,
            flags.c.browse_excluded.is_not(True),
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
        query = query.where(APC_EXISTS if has_apc else ~APC_EXISTS)
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
        return func.coalesce(subq.c.latest_apc, 0), "desc"
    if sort == "institution_works":
        return func.coalesce(subq.c.works, 0), "desc"
    if sort == "2yr_mean_citedness":
        return func.coalesce(subq.c.twoyr, 0), "desc"
    return func.coalesce(subq.c.rank, 0), "desc"  # relevance


async def attach_latest_apc(session: AsyncSession, items: list[dict[str, Any]]) -> None:
    """Stamps apc_period/apc_euro_latest (highest single reported APC in the
    journal's newest OpenAPC period with cost evidence) onto each item dict
    in place; one keyed query for the whole page."""
    apc_rows = (
        await session.execute(
            select(
                JournalApcAggregate.issn_l,
                JournalApcAggregate.period,
                JournalApcAggregate.euro_max,
            )
            .where(
                JournalApcAggregate.issn_l.in_([i["issn_l"] for i in items]),
                JournalApcAggregate.euro_max.is_not(None),
            )
            .order_by(JournalApcAggregate.issn_l, JournalApcAggregate.period.desc())
        )
    ).all()
    latest: dict[str, tuple[Any, Any]] = {}
    for r in apc_rows:
        latest.setdefault(r.issn_l, (r.period, r.euro_max))
    for item in items:
        hit = latest.get(item["issn_l"])
        item["apc_period"] = str(hit[0]) if hit else None
        item["apc_euro_latest"] = float(hit[1]) if hit and hit[1] is not None else None


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
        await attach_latest_apc(session, items)

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
    reflect the scoped institution."""

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
    # Every variant drops exactly its own filter and keeps the rest, so each
    # chip shows what selecting it would yield under the other filters.
    all_filters = dict(
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

    def variant_subq(*drop: str) -> Any:
        kept = {k: v for k, v in all_filters.items() if k not in drop}
        return base_query(**kept).subquery()

    if deal != "any":
        d = variant_subq("deal")
        d_total, (d_covered,) = await _one(d, d.c.deal_covered.is_(True))
        facets["deal_coverage"] = {"covered": d_covered, "not_covered": d_total - d_covered}
    if oa is not None:
        o = variant_subq("oa")
        o_total, (o_true,) = await _one(o, o.c.is_oa.is_(True))
        facets["oa"] = {"true": o_true, "false": o_total - o_true}
    if doaj is not None:
        dj = variant_subq("doaj")
        dj_total, (dj_true,) = await _one(dj, dj.c.is_in_doaj.is_(True))
        facets["doaj"] = {"true": dj_true, "false": dj_total - dj_true}
    if quartile in {"Q1", "Q2", "Q3", "Q4"}:
        qt = variant_subq("quartile")
        qt_total, (w1, w2, w3, w4) = await _one(
            qt,
            qt.c.quartile == "Q1",
            qt.c.quartile == "Q2",
            qt.c.quartile == "Q3",
            qt.c.quartile == "Q4",
        )
        facets["quartile"] = {"Q1": w1, "Q2": w2, "Q3": w3, "Q4": w4}
    # OA-type facet: counts per oa_type with the oa_type filter itself
    # excluded, so every option stays visible while selected.
    oa_type_subq = variant_subq("oa_types")
    oa_type_rows = await session.execute(
        select(oa_type_subq.c.oa_type, func.count().label("n")).group_by(oa_type_subq.c.oa_type)
    )
    facets["oa_type"] = {row.oa_type: int(row.n) for row in oa_type_rows}

    elem = func.jsonb_array_elements(
        func.coalesce(Journal.topics, text("'[]'::jsonb"))
    ).table_valued("value", name="t")
    topic_subq = variant_subq("topic")
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
    pub_subq = variant_subq("publisher")
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
        apc_base = variant_subq("has_apc")
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

    # Institution-works facet: journals with/without at least one known
    # institution publication, own filter excluded so both options stay
    # visible.
    if has_works is None:
        works_base, works_total = base, total
    else:
        works_base = variant_subq("has_works")
        works_total = await session.scalar(select(func.count()).select_from(works_base)) or 0
    works_true = (
        await session.scalar(
            select(func.count()).select_from(works_base).where(works_base.c.works > 0)
        )
        or 0
    )
    facets["works"] = {"true": int(works_true), "false": int(works_total) - int(works_true)}
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
    # Exact ranking: the HNSW index yields at most hnsw.ef_search tuples
    # (default 40), which silently caps any LIMIT above that and corrupts
    # offset paging. Planner flags scope to this request's transaction; the
    # exact scan + top-N sort over 129k rows costs tens of milliseconds.
    await session.execute(text("SET LOCAL enable_indexscan = off"))
    await session.execute(text("SET LOCAL enable_indexonlyscan = off"))
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
        await attach_latest_apc(session, items)
    return {
        "items": items,
        "total": total,
        "next_cursor": str(offset + limit) if has_more else None,
    }
