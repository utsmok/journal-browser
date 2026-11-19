"""Drop-own-dimension facet rule: shared helper plus the two facet
implementations (author SQL, publisher in-memory; orgunit facets moved
into the unit snapshot)."""

from typing import TYPE_CHECKING, Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Author

if TYPE_CHECKING:
    from .publishers import _Pub


def others(conds: dict, own: str) -> list:
    """Every active filter condition except the facet's own dimension."""
    return [c for key, c in conds.items() if key != own]


def works_expr(column: Any | None = None) -> Any:
    """Works-strata buckets over the given count column; None = the
    denormalized Author.n_works snapshot."""
    n = column if column is not None else Author.n_works
    return case(
        (n >= 50, "50+"),
        (n >= 20, "20-49"),
        (n >= 5, "5-19"),
        (n >= 1, "1-4"),
    )


def last_pub_expr(column: Any | None = None) -> Any:
    """Last-publication buckets over the given year column; None = the
    denormalized Author.last_pub_year snapshot."""
    year = column if column is not None else Author.last_pub_year
    return case(
        (year.is_(None), "none"),
        (year >= 2025, "2025-2026"),
        (year >= 2022, "2022-2024"),
        (year >= 2020, "2020-2021"),
    )


async def author_facets(
    session: AsyncSession,
    base: list[Any],
    conds: dict[str, Any],
    *,
    scoped: Any | None = None,
    n_col: Any | None = None,
    last_col: Any | None = None,
) -> dict[str, Any]:
    """Author search facets: one GROUP BY pass per dimension over the
    filtered base, each dropping its own filter. With an active
    publication-year range, `scoped` is the per-author year aggregation to
    LEFT JOIN in and n_col/last_col the year-scoped count/last-year
    expressions the works and last_pub buckets evaluate; the join rides on
    the shared base so every dimension's counts describe the same
    year-scoped population. Without a range nothing joins and the queries
    stay byte-identical to the snapshot-serving path."""
    exprs = {
        "faculty": Author.faculty,
        "org": Author.research_group,
        "works": works_expr(n_col),
        "last_pub": last_pub_expr(last_col),
        "topic": Author.primary_topic,
    }
    out: dict[str, Any] = {}
    for name, expr in exprs.items():
        stmt = select(expr, func.count().label("n")).where(
            *base, *others(conds, name), expr.is_not(None)
        )
        if scoped is not None:
            stmt = stmt.select_from(Author).outerjoin(
                scoped, scoped.c.author_pure_uuid == Author.pure_uuid
            )
        rows = (
            await session.execute(stmt.group_by(expr).order_by(func.count().desc(), expr))
        ).all()
        out[name] = [{"value": value, "count": n} for value, n in rows if value is not None]
    return out


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
    with_works, without_works = _count(
        "has_works", lambda p: p.n_works > 0, lambda p: p.n_works == 0
    )
    out["has_works"] = {"true": with_works, "false": without_works}
    counts = _count(
        "size",
        lambda p: p.n_journals == 1,
        lambda p: 2 <= p.n_journals <= 4,
        lambda p: 5 <= p.n_journals <= 9,
        lambda p: p.n_journals >= 10,
    )
    out["size"] = dict(zip(("1", "2-4", "5-9", "10+"), counts, strict=True))
    return out


def publisher_topic_facet(pubs: list["_Pub"], preds: dict[str, Any], limit: int) -> dict[str, int]:
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
