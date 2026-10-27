"""Publisher browsing: browsable journals aggregated per canonical publisher.

Mirror of the journal/author surfaces: the browsable cutoffs are the same
predicates as search.base_query (type='journal', per-institution
works_window_plus > 3, not browse_excluded, not admin-ignored). The
grouping key is COALESCE(NULLIF(publisher_canonical, ''), publisher_name)
— the OpenAlex lineage root resolved by jobs/harvest_publishers.py, so
sub-brands group under their root publisher; rows without a canonical
group by publisher_name as before.

Per request the service reads one cached snapshot per institution: a
single SQL statement aggregates the browsable join per publisher (counts,
quartiles, APC range) and explodes the topics jsonb into works-weighted
topic mass (harvest.authors.topic_mass semantics) plus the topic label
set. Filters, sorting, pagination and the drop-own-dimension facets then
run in Python over the snapshot; the ~5-min TTL mirrors
services/search.py's _FACET_CACHE.
"""

import time
import warnings
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Numeric, case, func, select, text
from sqlalchemy import exc as sa_exc
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..harvest.common import cache_epoch
from ..models import (
    Deal,
    DealInstitution,
    DealJournal,
    Institution,
    InstitutionWorksStats,
    Journal,
    JournalFlags,
    Publisher,
)
from .search import APC_SHOWN, OA_TYPES, _oa_type, _order, attach_apc_display, base_query

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
JOURNAL_CAP = 200
DEAL_DISCREPANCY_CAP = 10
TOPIC_FACET_LIMIT = 10
TOPICS_PER_ITEM = 3
TOPICS_PER_DETAIL = 5
SNAPSHOT_TTL = 86400  # seconds; a harvest bump invalidates sooner
SNAPSHOT_WORK_MEM = "128MB"  # cold-build-only, see _snapshot

QUARTILES = ("Q1", "Q2", "Q3", "Q4")
SIZE_BUCKETS = ("1", "2-4", "5-9", "10+")
SORT_KEYS = ("relevance", "name", "journals", "works", "deals", "apc")

# institution_id + ignored-issns hash -> (monotonic time, publisher rows)
_SNAPSHOT_CACHE: dict[tuple, tuple[float, dict[str, "_Pub"]]] = {}


def grouping_key() -> Any:
    """Publisher grouping key: canonical when set, else publisher_name."""
    return func.coalesce(func.nullif(Journal.publisher_canonical, ""), Journal.publisher_name)


@dataclass(slots=True)
class _Pub:
    """One publisher row of the cached snapshot."""

    name: str
    n_journals: int
    n_works: int
    deal_journals: int
    oa_counts: dict[str, int]
    quartile_counts: dict[str, int]  # q1..q4
    apc_journals: int
    eur_min: float | None
    eur_max: float | None
    # Works-weighted topic mass, top 5: [{"name": label, "n": mass}].
    topics: list[dict[str, Any]]
    # Topic display_names present in the group's journals (facet/filter
    # vocabulary), plus a lower-cased copy for case-insensitive matching.
    labels: frozenset[str]
    labels_lower: frozenset[str]
    # Sub-brand publisher_names in the group, lower-cased for q matching.
    members_lower: frozenset[str]


def _snapshot_query(institution_id: int) -> Any:
    """One statement: browsable join -> per-publisher aggregates + topic
    mass (count-share weighted per journal, topic_mass semantics) + topic
    label set, all over the same rows CTE."""
    J, F = Journal, JournalFlags
    ignored = get_settings().ignored_issns
    rows = (
        select(
            J.issn_l,
            grouping_key().label("name"),
            J.publisher_name.label("member"),
            F.works_count.label("works"),
            F.deal_covered.label("deal_covered"),
            _oa_type(F.deal_covered).label("oa_type"),
            J.latest_quartile.label("quartile"),
            APC_SHOWN.label("apc_any"),
            J.latest_apc_euro.label("apc_euro"),
            J.topics,
        )
        .join(F, (F.institution_id == institution_id) & (F.issn_l == J.issn_l))
        .where(
            J.type == "journal",
            J.issn_l.is_not(None),
            F.works_window_plus > 3,
            F.browse_excluded.is_not(True),
            J.publisher_name.is_not(None),
            J.publisher_name != "",
            *([J.issn_l.not_in(sorted(set(ignored)))] if ignored else []),
        )
        .cte("rows")
    )
    agg = (
        select(
            rows.c.name,
            func.count().label("n_journals"),
            func.coalesce(func.sum(rows.c.works), 0).label("n_works"),
            func.count().filter(rows.c.deal_covered.is_(True)).label("deal_journals"),
            *[func.count().filter(rows.c.oa_type == t).label(t) for t in OA_TYPES],
            *[func.count().filter(rows.c.quartile == q).label(q.lower()) for q in QUARTILES],
            func.count().filter(rows.c.apc_any).label("apc_journals"),
            func.min(rows.c.apc_euro).label("eur_min"),
            func.max(rows.c.apc_euro).label("eur_max"),
        )
        .group_by(rows.c.name)
        .cte("agg")
    )
    # Journal topic entries (display_name required; label = subfield or the
    # topic name itself, matching topic_mass). Set-returning function in
    # FROM: Postgres lateralizes these implicitly.
    entries_tv = (
        func.jsonb_array_elements(func.coalesce(rows.c.topics, text("'[]'::jsonb")))
        .table_valued("value", with_ordinality="ord", name="t")
        .render_derived()
    )
    entries = (
        select(
            rows.c.name,
            rows.c.issn_l,
            rows.c.works,
            entries_tv.c.value.op("->>")("display_name").label("dn"),
            func.coalesce(
                func.nullif(entries_tv.c.value.op("->>")("subfield"), ""),
                entries_tv.c.value.op("->>")("display_name"),
            ).label("label"),
            func.coalesce(entries_tv.c.value.op("->>")("count"), "0").cast(Numeric).label("cnt"),
            entries_tv.c.ord,
        )
        .select_from(rows, entries_tv)
        .where(entries_tv.c.value.op("->>")("display_name").is_not(None))
        .cte("entries")
    )
    # Per-journal count-share weighting in one window pass (topic_mass
    # semantics): positive-count venues spread works across their entries;
    # zero-count venues (rows stored before `count` was persisted) pile
    # all works onto the first entry's label.
    weighted = select(
        entries.c.name,
        entries.c.label,
        func.sum(entries.c.cnt)
        .over(partition_by=(entries.c.name, entries.c.issn_l))
        .label("total"),
        case(
            (
                func.sum(entries.c.cnt).over(partition_by=(entries.c.name, entries.c.issn_l)) > 0,
                entries.c.works
                * entries.c.cnt
                / func.sum(entries.c.cnt).over(partition_by=(entries.c.name, entries.c.issn_l)),
            ),
            else_=None,
        ).label("m"),
        func.first_value(entries.c.label)
        .over(partition_by=(entries.c.name, entries.c.issn_l), order_by=entries.c.ord)
        .label("first_label"),
        func.row_number()
        .over(partition_by=(entries.c.name, entries.c.issn_l), order_by=entries.c.ord)
        .label("rn"),
        entries.c.works.label("works"),
    ).cte("weighted")
    mass = (
        select(weighted.c.name, weighted.c.label, weighted.c.m)
        .where(weighted.c.total > 0)
        .union_all(
            select(
                weighted.c.name,
                weighted.c.first_label.label("label"),
                weighted.c.works.label("m"),
            ).where((weighted.c.total <= 0) & (weighted.c.rn == 1))
        )
        .subquery()
    )
    massagg = (
        select(mass.c.name, mass.c.label, func.sum(mass.c.m).label("m"))
        .group_by(mass.c.name, mass.c.label)
        .cte("massagg")
    )
    ranked = select(
        massagg.c.name,
        massagg.c.label,
        massagg.c.m,
        func.row_number()
        .over(
            partition_by=massagg.c.name,
            order_by=(massagg.c.m.desc(), massagg.c.label.asc()),
        )
        .label("rn"),
    ).subquery()
    topics5 = (
        select(
            ranked.c.name,
            func.jsonb_object_agg(ranked.c.label, ranked.c.m).cast(JSONB).label("topics"),
        )
        .where(ranked.c.rn <= TOPICS_PER_DETAIL)
        .group_by(ranked.c.name)
        .subquery()
    )
    # Facet/filter vocabulary: display_names per publisher; duplicates are
    # collapsed into a frozenset during snapshot build (cheaper than a SQL
    # DISTINCT over the ~376k exploded entries).
    labels = (
        select(entries.c.name, func.jsonb_agg(entries.c.dn).cast(JSONB).label("labels"))
        .group_by(entries.c.name)
        .subquery()
    )
    # Sub-brand publisher_names in the group, so search q can reach a
    # canonical group through any of its member names ("IEEE" -> the IEEE
    # group whose display name is the spelled-out institute).
    members = (
        select(
            rows.c.name,
            func.jsonb_agg(func.distinct(rows.c.member)).cast(JSONB).label("members"),
        )
        .group_by(rows.c.name)
        .subquery()
    )
    return (
        select(
            agg,
            func.coalesce(topics5.c.topics, text("'[]'::jsonb")).label("topics"),
            func.coalesce(labels.c.labels, text("'[]'::jsonb")).label("labels"),
            func.coalesce(members.c.members, text("'[]'::jsonb")).label("members"),
        )
        .select_from(agg)
        .outerjoin(topics5, topics5.c.name == agg.c.name)
        .outerjoin(labels, labels.c.name == agg.c.name)
        .outerjoin(members, members.c.name == agg.c.name)
    )


async def _snapshot(session: AsyncSession, institution_id: int) -> dict[str, _Pub]:
    """Publisher aggregation for one institution, cached until the next
    harvest bump or 24h."""
    cache_key = (
        institution_id,
        hash(tuple(sorted(get_settings().ignored_issns))),
        await cache_epoch(session),
    )
    hit = _SNAPSHOT_CACHE.get(cache_key)
    if hit and time.monotonic() - hit[0] < SNAPSHOT_TTL:
        return hit[1]
    snap: dict[str, _Pub] = {}
    # The entries CTE's set-returning join is implicitly lateral in
    # Postgres; SQLAlchemy mistakes it for a cartesian product.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=".*cartesian product.*", category=sa_exc.SAWarning
        )
        # One-off build: keep the ~400k-entry hash aggregates and sorts
        # in memory instead of spilling at the 4MB default. SET LOCAL dies
        # with the request's transaction, so the pool is unaffected.
        await session.execute(text(f"SET LOCAL work_mem = '{SNAPSHOT_WORK_MEM}'"))
        result = await session.execute(_snapshot_query(institution_id))
    for r in result.all():
        topics = sorted(
            ({"name": name, "n": float(n)} for name, n in (r.topics or {}).items()),
            key=lambda t: (-t["n"], t["name"]),
        )
        labels = frozenset(r.labels or ())
        snap[r.name] = _Pub(
            name=r.name,
            n_journals=r.n_journals,
            n_works=int(r.n_works or 0),
            deal_journals=r.deal_journals,
            oa_counts={t: getattr(r, t) for t in OA_TYPES},
            quartile_counts={q.lower(): getattr(r, q.lower()) for q in QUARTILES},
            apc_journals=r.apc_journals,
            eur_min=float(r.eur_min) if r.eur_min is not None else None,
            eur_max=float(r.eur_max) if r.eur_max is not None else None,
            topics=topics,
            labels=labels,
            labels_lower=frozenset(lab.lower() for lab in labels),
            members_lower=frozenset(m.lower() for m in (r.members or ())),
        )
    _SNAPSHOT_CACHE[cache_key] = (time.monotonic(), snap)
    return snap


def _predicates(
    *,
    oa_types: list[str] | None,
    deal: str,
    quartiles: list[str] | None,
    topic: list[str] | None,
    sizes: list[str] | None,
    has_apc: bool | None,
    has_works: bool | None,
) -> dict[str, Any]:
    """One predicate per active publisher-level dimension, keyed so a
    facet's counts can drop its own while keeping all others."""
    preds: dict[str, Any] = {}
    if oa_types:
        preds["oa_type"] = lambda p: any(p.oa_counts[t] > 0 for t in oa_types)
    if deal == "covered":
        preds["deal"] = lambda p: p.deal_journals > 0
    elif deal == "none":
        preds["deal"] = lambda p: p.deal_journals == 0
    if quartiles:
        preds["quartile"] = lambda p: any(p.quartile_counts[q.lower()] > 0 for q in quartiles)
    if topic:
        wanted = {t.lower() for t in topic}
        preds["topic"] = lambda p: any(lab in wanted for lab in p.labels_lower)
    if sizes:
        buckets = {
            "1": lambda p: p.n_journals == 1,
            "2-4": lambda p: 2 <= p.n_journals <= 4,
            "5-9": lambda p: 5 <= p.n_journals <= 9,
            "10+": lambda p: p.n_journals >= 10,
        }
        preds["size"] = lambda p: any(buckets[s](p) for s in sizes)
    if has_apc is not None:
        preds["has_apc"] = (
            (lambda p: p.apc_journals > 0) if has_apc else (lambda p: p.apc_journals == 0)
        )
    if has_works is not None:
        preds["has_works"] = (lambda p: p.n_works > 0) if has_works else (lambda p: p.n_works == 0)
    return preds


def _passes(p: _Pub, preds: dict[str, Any], skip: str | None = None) -> bool:
    return all(fn(p) for key, fn in preds.items() if key != skip)


def _order_pubs(pubs: list[_Pub], sort: str, q: str | None, dir: str | None) -> list[_Pub]:
    """Sort with the SQL convention: head direction, ties broken by
    (lower(name), name) ascending; two stable passes keep that intact."""

    def head(p: _Pub) -> Any:
        if sort == "name":
            return p.name.lower()
        if sort == "journals":
            return p.n_journals
        if sort == "deals":
            return p.deal_journals
        if sort == "apc":
            return p.eur_max or 0
        if sort == "relevance" and q:
            ql = q.strip().lower()
            prefix = p.name.lower().startswith(ql) or any(
                m.startswith(ql) for m in p.members_lower
            )
            return 1 if prefix else 0
        return p.n_works  # works, and relevance without q

    direction = dir if dir in ("asc", "desc") else "desc"
    pubs.sort(key=lambda p: (p.name.lower(), p.name))
    pubs.sort(key=head, reverse=direction == "desc")
    return pubs


def _item(p: _Pub, topics: list[dict[str, Any]]) -> dict[str, Any]:
    q = p.quartile_counts
    return {
        "name": p.name,
        "n_journals": p.n_journals,
        "n_works": p.n_works,
        "deal_journals": p.deal_journals,
        "oa_types": dict(p.oa_counts),
        "quartiles": {
            "q1": q["q1"],
            "q2": q["q2"],
            "q3": q["q3"],
            "q4": q["q4"],
            "none": p.n_journals - sum(q.values()),
        },
        "apc": {
            "n_journals": p.apc_journals,
            "eur_min": p.eur_min,
            "eur_max": p.eur_max,
        },
        "topics": topics,
    }


def _facets(pubs: list[_Pub], preds: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Drop-own-dimension publisher counts per facet (topic separate)."""

    def _count(skip: str | None, *flags: Any) -> list[int]:
        rows = [p for p in pubs if _passes(p, preds, skip)]
        return [sum(1 for p in rows if flag(p)) for flag in flags]

    out: dict[str, dict[str, int]] = {}
    counts = _count("oa_type", *[lambda p, t=t: p.oa_counts[t] > 0 for t in OA_TYPES])
    out["oa_type"] = dict(zip(OA_TYPES, counts, strict=True))
    covered, none = _count("deal", lambda p: p.deal_journals > 0, lambda p: p.deal_journals == 0)
    out["deal"] = {"covered": covered, "none": none}
    counts = _count(
        "quartile", *[lambda p, q=q: p.quartile_counts[q.lower()] > 0 for q in QUARTILES]
    )
    out["quartile"] = dict(zip(QUARTILES, counts, strict=True))
    yes, no = _count("has_apc", lambda p: p.apc_journals > 0, lambda p: p.apc_journals == 0)
    out["has_apc"] = {"yes": yes, "no": no}
    counts = _count(
        "size",
        lambda p: p.n_journals == 1,
        lambda p: 2 <= p.n_journals <= 4,
        lambda p: 5 <= p.n_journals <= 9,
        lambda p: p.n_journals >= 10,
    )
    out["size"] = dict(zip(SIZE_BUCKETS, counts, strict=True))
    return out


def _topic_facet(pubs: list[_Pub], preds: dict[str, Any]) -> dict[str, int]:
    """Publishers (under every filter except topic) with >=1 journal per
    topic label; top 10 by publisher count."""
    counts: dict[str, int] = {}
    for p in pubs:
        if not _passes(p, preds, "topic"):
            continue
        for label in p.labels:
            counts[label] = counts.get(label, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOPIC_FACET_LIMIT]
    return dict(top)


async def search_publishers(
    session: AsyncSession,
    *,
    institution_id: int,
    q: str | None = None,
    oa_types: list[str] | None = None,
    deal: str = "any",
    quartiles: list[str] | None = None,
    topic: list[str] | None = None,
    sizes: list[str] | None = None,
    has_apc: bool | None = None,
    has_works: bool | None = None,
    sort: str | None = None,
    dir: str | None = None,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    include_facets: bool = True,
) -> dict[str, Any]:
    """Publisher roster for one institution: total is the filter match count,
    items the offset/limit page of the sorted matches (default sort
    relevance-with-q, else works desc)."""
    snap = await _snapshot(session, institution_id)
    q = q.strip() if q and q.strip() else None
    q_lower = q.lower() if q else None

    def q_hit(p: _Pub) -> bool:
        return q_lower in p.name.lower() or any(q_lower in m for m in p.members_lower)

    # The q filter rides along in facet counts; the dimension filters don't
    # (drop-own-dimension).
    q_base = (
        [p for p in snap.values() if q_hit(p)] if q_lower else list(snap.values())
    )
    preds = _predicates(
        oa_types=oa_types,
        deal=deal,
        quartiles=quartiles,
        topic=topic,
        sizes=sizes,
        has_apc=has_apc,
        has_works=has_works,
    )
    matches = [p for p in q_base if _passes(p, preds)]

    if sort is None:
        sort = "relevance" if q else "works"
    page = _order_pubs(matches, sort, q, dir)[offset : offset + min(limit, MAX_LIMIT)]
    items = [_item(p, p.topics[:TOPICS_PER_ITEM]) for p in page]
    facets: dict[str, dict[str, int]] = {}
    if include_facets:
        facets = _facets(q_base, preds)
        facets["topic"] = _topic_facet(q_base, preds)
    return {"items": items, "total": len(matches), "facets": facets}


async def publisher_detail(
    session: AsyncSession, institution: Institution, name: str
) -> dict[str, Any] | None:
    """Full publisher bundle; None = no browsable journal under this
    canonical key (404 upstream). Deals reuse the journal-detail
    participation join."""
    iid = institution.id
    pub = (await _snapshot(session, iid)).get(name)
    if pub is None:
        return None

    # Same page assembly as search_journals (no facets, no cursor), scoped
    # to the canonical key so sub-brand publisher_names join the group.
    subq = (
        base_query(institution_id=iid)
        .where(
            grouping_key() == name,
            Journal.publisher_name.is_not(None),
            Journal.publisher_name != "",
        )
        .subquery()
    )
    issns = [r.issn_l for r in (await session.execute(select(subq.c.issn_l))).all()]
    order_col, direction = _order("institution_works", subq)
    head = order_col.desc() if direction == "desc" else order_col.asc()
    journal_rows = (
        await session.execute(select(subq).order_by(head, subq.c.issn_l.desc()).limit(JOURNAL_CAP))
    ).all()
    journals = []
    for row in journal_rows:
        item = dict(row._mapping)
        item["twoyr_mean_citedness"] = (
            float(item.pop("twoyr")) if item.get("twoyr") is not None else None
        )
        item.pop("rank", None)
        journals.append(item)
    if journals:
        await attach_apc_display(session, journals)

    # Same participation/override semantics as the journal detail deals.
    dj_scope = DealJournal.institution_id.is_not_distinct_from(
        case((DealInstitution.journal_override.is_(True), iid), else_=None)
    )
    deal_rows = (
        await session.execute(
            select(Deal, Publisher.name)
            .select_from(Deal)
            .join(
                DealInstitution,
                (DealInstitution.deal_id == Deal.id) & (DealInstitution.institution_id == iid),
            )
            .join(
                DealJournal,
                (DealJournal.deal_id == Deal.id)
                & dj_scope
                & DealJournal.excluded.is_not(True)
                & DealJournal.issn_l.in_(issns),
            )
            .outerjoin(Publisher, Publisher.id == Deal.publisher_id)
            .where(Deal.status == "current")
            .distinct()
            .order_by(Deal.id)
        )
    ).all()

    stats_rows = (
        (
            await session.execute(
                select(InstitutionWorksStats)
                .where(
                    InstitutionWorksStats.institution_id == iid,
                    InstitutionWorksStats.issn_l.in_(issns),
                    InstitutionWorksStats.year >= institution.data_window_start,
                    InstitutionWorksStats.year <= (institution.data_window_end or 9999),
                )
                .order_by(InstitutionWorksStats.year)
            )
        )
        .scalars()
        .all()
    )
    by_source = {
        source: {s.year: s for s in stats_rows if s.source == source}
        for source in ("pure_canon", "openalex_institution_filter")
    }
    # Works count: Pure-canonical when present; OA split: always OpenAlex
    # (journal-detail convention).
    works_by_year = []
    for year in sorted({s.year for s in stats_rows}, reverse=True):
        oa_row = by_source["openalex_institution_filter"].get(year)
        primary = by_source["pure_canon"].get(year)
        if oa_row is None and primary is None:
            continue
        split = oa_row if oa_row is not None else primary
        works_by_year.append(
            {
                "year": year,
                "works_count": primary.works_count if primary is not None else split.works_count,
                "works_count_source": (
                    "pure_canon" if primary is not None else "openalex_institution_filter"
                ),
                "oa_gold": split.oa_gold,
                "oa_hybrid": split.oa_hybrid,
                "oa_green": split.oa_green,
                "oa_bronze": split.oa_bronze,
                "oa_diamond": split.oa_diamond,
                "oa_closed": split.oa_closed,
            }
        )

    return {
        "publisher": _item(pub, pub.topics[:TOPICS_PER_DETAIL]),
        "journals": journals,
        "deals": [(d, publisher_name) for d, publisher_name in deal_rows],
        "works_by_year": works_by_year,
    }
