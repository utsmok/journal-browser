import warnings
from typing import Any

from sqlalchemy import exc as sa_exc
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...harvest.common import cache_epoch
from ...models import Journal
from ..cache import FACET_CACHE, cache_get, cache_put
from .query import base_query


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
    cacheable = not any(
        [
            q,
            oa,
            doaj,
            quartile,
            topic,
            publisher,
            has_apc is not None,
            has_works is not None,
            oa_types,
            deal != "any",
            search_in != "all",
        ]
    )
    # The ignore-list and the harvest epoch shape the counts; either change
    # invalidates immediately instead of serving stale facets for 24h.
    # Deferred get_settings keeps the search-module monkeypatch seam
    # (tests/test_admin_deals.py) live.
    from journal_browser.services import search

    cache_key = (
        "facets",
        institution_id,
        hash(tuple(sorted(search.get_settings().ignored_issns))),
        await cache_epoch(session),
    )
    if cacheable:
        hit = cache_get(FACET_CACHE, cache_key, 86400)
        if hit is not None:
            return hit
    defaults = {
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
                func.jsonb_object_agg(counted.c.oa_type, counted.c.oa_n).label("oa_type_counts"),
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
        _qt_total, (w1, w2, w3, w4) = await _flag_counts(
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
        cache_put(FACET_CACHE, cache_key, (facets, total))
    return facets, total
