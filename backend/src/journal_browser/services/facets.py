"""Drop-own-dimension facet rule: shared helper plus the three facet
implementations (author SQL, orgunit SQL, publisher in-memory)."""

from typing import TYPE_CHECKING, Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Author
from .works_query import WORKS_STRATA, strata_bound

if TYPE_CHECKING:
    from .publishers import _Pub


def others(conds: dict, own: str) -> list:
    """Every active filter condition except the facet's own dimension."""
    return [c for key, c in conds.items() if key != own]


def works_expr() -> Any:
    return case(
        (Author.n_works >= 50, "50+"),
        (Author.n_works >= 20, "20-49"),
        (Author.n_works >= 5, "5-19"),
        (Author.n_works >= 1, "1-4"),
    )


def last_pub_expr() -> Any:
    return case(
        (Author.last_pub_year.is_(None), "none"),
        (Author.last_pub_year >= 2025, "2025-2026"),
        (Author.last_pub_year >= 2022, "2022-2024"),
        (Author.last_pub_year >= 2020, "2020-2021"),
    )


async def author_facets(
    session: AsyncSession, base: list[Any], conds: dict[str, Any]
) -> dict[str, Any]:
    """Author search facets: one GROUP BY pass per dimension over the
    filtered base, each dropping its own filter."""
    exprs = {
        "faculty": Author.faculty,
        "org": Author.research_group,
        "works": works_expr(),
        "last_pub": last_pub_expr(),
        "topic": Author.primary_topic,
    }
    out: dict[str, Any] = {}
    for name, expr in exprs.items():
        rows = (
            await session.execute(
                select(expr, func.count().label("n"))
                .where(*base, *others(conds, name), expr.is_not(None))
                .group_by(expr)
                .order_by(func.count().desc(), expr)
            )
        ).all()
        out[name] = [{"value": value, "count": n} for value, n in rows if value is not None]
    return out


async def orgunit_facets(
    session: AsyncSession,
    units: Any,
    conds: dict[str, Any],
    q_cond: Any | None,
    level: str,
) -> dict[str, dict[str, int]]:
    """Org-unit facets: faculty (group level), size strata, deal usage; each
    variant drops its own filter and keeps q."""
    q_extra = [q_cond] if q_cond is not None else []
    facets: dict[str, dict[str, int]] = {}
    if level == "group":
        rows_ = (
            await session.execute(
                select(units.c.faculty, func.count())
                .where(*others(conds, "faculty"), *q_extra, units.c.faculty.is_not(None))
                .group_by(units.c.faculty)
                .order_by(func.count().desc(), units.c.faculty)
            )
        ).all()
        facets["faculty"] = {r.faculty: int(r[1]) for r in rows_}
    row = (
        await session.execute(
            select(
                *[
                    func.count().filter(strata_bound(units.c.n_works, stratum))
                    for stratum in WORKS_STRATA
                ]
            )
            .select_from(units)
            .where(*others(conds, "works"), *q_extra)
        )
    ).one()
    facets["size"] = dict(zip(WORKS_STRATA, (int(v or 0) for v in row), strict=True))
    row = (
        await session.execute(
            select(
                func.count().filter(units.c.deal_works > 0),
                func.count().filter(units.c.deal_works == 0),
            )
            .select_from(units)
            .where(*others(conds, "uses_deals"), *q_extra)
        )
    ).one()
    facets["uses_deals"] = {"yes": int(row[0] or 0), "no": int(row[1] or 0)}
    return facets


def publisher_predicates(
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


def passes(p: "_Pub", preds: dict[str, Any], skip: str | None = None) -> bool:
    return all(fn(p) for key, fn in preds.items() if key != skip)


def publisher_facets(
    pubs: list["_Pub"], preds: dict[str, Any], *, quartiles: tuple[str, ...], oa_types: tuple
) -> dict[str, dict[str, int]]:
    """Drop-own-dimension publisher counts per facet (topic separate)."""

    def _count(skip: str | None, *flags: Any) -> list[int]:
        rows = [p for p in pubs if passes(p, preds, skip)]
        return [sum(1 for p in rows if flag(p)) for flag in flags]

    out: dict[str, dict[str, int]] = {}
    counts = _count("oa_type", *[lambda p, t=t: p.oa_counts[t] > 0 for t in oa_types])
    out["oa_type"] = dict(zip(oa_types, counts, strict=True))
    covered, none = _count("deal", lambda p: p.deal_journals > 0, lambda p: p.deal_journals == 0)
    out["deal"] = {"covered": covered, "none": none}
    counts = _count(
        "quartile", *[lambda p, q=q: p.quartile_counts[q.lower()] > 0 for q in quartiles]
    )
    out["quartile"] = dict(zip(quartiles, counts, strict=True))
    yes, no = _count("has_apc", lambda p: p.apc_journals > 0, lambda p: p.apc_journals == 0)
    out["has_apc"] = {"yes": yes, "no": no}
    counts = _count(
        "size",
        lambda p: p.n_journals == 1,
        lambda p: 2 <= p.n_journals <= 4,
        lambda p: 5 <= p.n_journals <= 9,
        lambda p: p.n_journals >= 10,
    )
    out["size"] = dict(zip(("1", "2-4", "5-9", "10+"), counts, strict=True))
    return out


def publisher_topic_facet(
    pubs: list["_Pub"], preds: dict[str, Any], limit: int
) -> dict[str, int]:
    """Publishers (under every filter except topic) with >=1 journal per
    topic label; top `limit` by publisher count."""
    counts: dict[str, int] = {}
    for p in pubs:
        if not passes(p, preds, "topic"):
            continue
        for label in p.labels:
            counts[label] = counts.get(label, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return dict(top)
