import asyncio
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Journal
from .query import attach_apc_display, base_query

#: Similar-journal list sizes: the Twente/deal-cut lists are teasers, the
#: general list carries the full ten.
SIMILAR_FILTERED_LIMIT = 5
SIMILAR_ALL_LIMIT = 10
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
