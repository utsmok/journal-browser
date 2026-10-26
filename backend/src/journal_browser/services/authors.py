"""Author browsing: search, profile bundle, embedding-based recommendations.

All journal-level views reuse search.base_query, so the per-institution
corpus cutoff (works_window_plus > 3), proceedings exclusion and ignore-list
apply to every suggestion; the oa_type case is shared via search._oa_type."""

from typing import Any

from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Author, AuthorWork, Journal, JournalFlags, Work
from .search import _like, _oa_type, base_query

#: Search page + recommendation list sizes.
DEFAULT_LIMIT = 25
MAX_LIMIT = 100
SIMILAR_ALL_LIMIT = 8
SIMILAR_FILTERED_LIMIT = 5
ALTERNATIVE_JOURNALS = 5
ALTERNATIVE_OPTIONS = 3
WORKS_CAP = 200

#: Response buckets of works.oa_status (diamond exists in works but the
#: contract's year split has no diamond column; it still counts in total).
_YEAR_BUCKETS = ("gold", "green", "hybrid", "bronze", "closed")


async def search_authors(
    session: AsyncSession, institution_id: int, q: str | None, limit: int
) -> dict[str, Any]:
    """Author roster for one institution. total is the q-filtered match
    count (the whole roster when q is empty); items are the top matches."""
    roster = await session.scalar(
        select(func.count()).select_from(Author).where(Author.institution_id == institution_id)
    )
    if not roster:
        return {"enabled": False, "total": 0, "items": []}
    query = select(Author).where(Author.institution_id == institution_id)
    if q and q.strip():
        qstr = q.strip()
        cond = Author.name.ilike(f"%{_like(qstr)}%", escape="\\")
        total = await session.scalar(select(func.count()).select_from(Author).where(cond))
        query = query.where(cond).order_by(
            case((Author.name.ilike(f"{_like(qstr)}%", escape="\\"), 1), else_=0).desc(),
            Author.n_works.desc(),
            func.lower(Author.name),
        )
    else:
        total = roster
        query = query.order_by(Author.n_works.desc(), func.lower(Author.name))
    rows = (await session.execute(query.limit(min(limit, MAX_LIMIT)))).scalars().all()
    return {
        "enabled": True,
        "total": total,
        "items": [
            {
                "pure_uuid": a.pure_uuid,
                "name": a.name,
                "faculty": a.faculty,
                "research_group": a.research_group,
                "n_works": a.n_works,
                "orcid": a.orcid,
            }
            for a in rows
        ],
    }


async def _author_journals(
    session: AsyncSession, institution_id: int, pure_uuid: str
) -> list[Any]:
    """The author's distinct venues with work counts + effective oa_type,
    works count desc (ties by issn for determinism)."""
    flags = (
        select(JournalFlags.issn_l, JournalFlags.deal_covered)
        .where(JournalFlags.institution_id == institution_id)
        .subquery()
    )
    return (
        await session.execute(
            select(
                Work.journal_issn_l.label("issn_l"),
                Journal.title.label("title"),
                func.count().label("n_works"),
                _oa_type(flags.c.deal_covered),
            )
            .select_from(Work)
            .join(
                AuthorWork,
                and_(
                    AuthorWork.institution_id == institution_id,
                    AuthorWork.work_pure_uuid == Work.pure_uuid,
                    AuthorWork.author_pure_uuid == pure_uuid,
                ),
            )
            .join(Journal, Journal.issn_l == Work.journal_issn_l)
            .join(flags, flags.c.issn_l == Journal.issn_l)
            .where(
                Work.institution_id == institution_id,
                Work.retired_at.is_(None),
            )
            .group_by(
                Work.journal_issn_l,
                Journal.issn_l,  # referenced by the oa_type APC EXISTS
                Journal.title,
                Journal.is_in_doaj,
                flags.c.deal_covered,
            )
            .order_by(func.count().desc(), Work.journal_issn_l)
        )
    ).all()


def _similar_item(row: Any) -> dict[str, Any]:
    return {
        "issn_l": row.issn_l,
        "title": row.title,
        "score": round(1.0 - row.dist, 4),
        "oa_type": row.oa_type,
        "deal_covered": row.deal_covered,
    }


def _candidate_subquery(institution_id: int, exclude_issns: list[str], vector: Any) -> Any:
    """base_query + cosine distance to `vector`, author journals excluded."""
    return (
        base_query(institution_id=institution_id)
        .add_columns(Journal.embedding.cosine_distance(vector).label("dist"))
        .where(Journal.embedding.is_not(None), Journal.issn_l.not_in(exclude_issns))
        .subquery()
    )


def _weighted_mean(weighted: list[tuple[float, Any]]) -> list[float] | None:
    """Works-weighted average embedding; None without usable vectors."""
    usable = [(w, [float(x) for x in vec]) for w, vec in weighted if vec is not None]
    total = sum(w for w, _vec in usable)
    if not usable or total <= 0:
        return None
    out = [0.0] * len(usable[0][1])
    for w, vec in usable:
        for i, value in enumerate(vec):
            out[i] += w * value
    return [value / total for value in out]


async def _similar_sections(
    session: AsyncSession,
    institution_id: int,
    journal_rows: list[Any],
    embeddings: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """({"all","deals","diamond"}, alternatives) around the author's venues.

    all/deals/diamond rank candidates by cosine distance to the works-weighted
    average of the author's distinct journal embeddings. alternatives serve
    each non-OA venue's top diamond-or-deal-covered escapes."""
    author_issns = [row.issn_l for row in journal_rows]
    weighted = [
        (row.n_works, embeddings[row.issn_l]) for row in journal_rows if row.issn_l in embeddings
    ]
    avg = _weighted_mean(weighted)
    similar: dict[str, list[dict[str, Any]]] = {"all": [], "deals": [], "diamond": []}
    alternatives: list[dict[str, Any]] = []
    if avg is not None:
        # Same iterative HNSW scan as the journal similar endpoint: the
        # visibility cuts filter most rows.
        await session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
        await session.execute(text(f"SET LOCAL hnsw.ef_search = {SIMILAR_ALL_LIMIT * 10}"))
        cuts = {
            "all": (None, SIMILAR_ALL_LIMIT),
            "deals": (lambda c: c.deal_covered.is_(True), SIMILAR_FILTERED_LIMIT),
            "diamond": (lambda c: c.oa_type == "diamond", SIMILAR_FILTERED_LIMIT),
        }
        for key, (cond, limit) in cuts.items():
            subq = _candidate_subquery(institution_id, author_issns, avg)
            outer = select(subq).order_by(subq.c.dist.asc(), subq.c.issn_l.asc())
            if cond is not None:
                outer = outer.where(cond(subq.c))
            rows = (await session.execute(outer.limit(limit))).all()
            similar[key] = [_similar_item(row) for row in rows]

        sources = [
            row
            for row in journal_rows
            if row.oa_type in ("hybrid", "subscription") and row.issn_l in embeddings
        ]
        for row in sources:
            subq = _candidate_subquery(institution_id, author_issns, embeddings[row.issn_l])
            options = (
                await session.execute(
                    select(subq)
                    .where(or_(subq.c.oa_type == "diamond", subq.c.deal_covered.is_(True)))
                    .order_by(subq.c.dist.asc(), subq.c.issn_l.asc())
                    .limit(ALTERNATIVE_OPTIONS)
                )
            ).all()
            if options:
                alternatives.append(
                    {
                        "issn_l": row.issn_l,
                        "title": row.title,
                        "n_works": row.n_works,
                        "options": [_similar_item(option) for option in options],
                    }
                )
            if len(alternatives) >= ALTERNATIVE_JOURNALS:
                break
    return similar, alternatives


async def author_profile(
    session: AsyncSession, institution_id: int, pure_uuid: str
) -> dict[str, Any] | None:
    """Full profile bundle; None = unknown author (404 upstream)."""
    author = await session.scalar(
        select(Author).where(
            Author.institution_id == institution_id, Author.pure_uuid == pure_uuid
        )
    )
    if author is None:
        return None

    work_join = and_(
        AuthorWork.institution_id == institution_id,
        AuthorWork.work_pure_uuid == Work.pure_uuid,
        AuthorWork.author_pure_uuid == pure_uuid,
    )
    non_retired = (Work.institution_id == institution_id, Work.retired_at.is_(None))
    work_rows = (
        await session.execute(
            select(
                Work.pure_uuid,
                Work.title,
                Work.year,
                Work.doi_normalized,
                Work.oa_status,
                Work.journal_issn_l,
                Journal.title.label("journal_title"),
            )
            .join(AuthorWork, work_join)
            .outerjoin(Journal, Journal.issn_l == Work.journal_issn_l)
            .where(*non_retired)
            .order_by(Work.year.desc(), func.lower(Work.title))
            .limit(WORKS_CAP)
        )
    ).all()

    year_rows = (
        await session.execute(
            select(Work.year, Work.oa_status, func.count().label("n"))
            .join(AuthorWork, work_join)
            .where(*non_retired)
            .group_by(Work.year, Work.oa_status)
        )
    ).all()
    by_year: dict[int, dict[str, int]] = {}
    for row in year_rows:
        bucket = by_year.setdefault(
            row.year, {"year": row.year, "total": 0, **dict.fromkeys(_YEAR_BUCKETS, 0)}
        )
        bucket["total"] += row.n
        if row.oa_status in _YEAR_BUCKETS:
            bucket[row.oa_status] += row.n
    oa_by_year = [by_year[year] for year in sorted(by_year, reverse=True)]

    journal_rows = await _author_journals(session, institution_id, pure_uuid)
    topics: dict[str, int] = {}
    if journal_rows:
        topic_rows = (
            await session.execute(
                select(Journal.issn_l, Journal.topics).where(
                    Journal.issn_l.in_([row.issn_l for row in journal_rows])
                )
            )
        ).all()
        topics_by_issn = {row.issn_l: row.topics or [] for row in topic_rows}
        # Topic weighting: each venue contributes its works count to every
        # one of its OpenAlex topics.
        for row in journal_rows:
            for topic in topics_by_issn.get(row.issn_l, []):
                name = topic.get("display_name") if isinstance(topic, dict) else None
                if name:
                    topics[name] = topics.get(name, 0) + row.n_works
    top_topics = [
        {"name": name, "n": n}
        for name, n in sorted(topics.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    ]

    embeddings: dict[str, Any] = {}
    if journal_rows:
        emb_rows = (
            await session.execute(
                select(Journal.issn_l, Journal.embedding).where(
                    Journal.issn_l.in_([row.issn_l for row in journal_rows])
                )
            )
        ).all()
        embeddings = {row.issn_l: row.embedding for row in emb_rows if row.embedding is not None}
    similar, alternatives = await _similar_sections(
        session, institution_id, journal_rows, embeddings
    )

    return {
        "author": {
            "pure_uuid": author.pure_uuid,
            "name": author.name,
            "orcid": author.orcid,
            "openalex_author_id": author.openalex_author_id,
            "openaire_person_id": author.openaire_person_id,
            "crossref_orcid": author.crossref_orcid,
            "faculty": author.faculty,
            "research_group": author.research_group,
            "orgs": author.orgs or [],
            "n_works": author.n_works,
        },
        "oa_by_year": oa_by_year,
        "journals": [
            {
                "issn_l": row.issn_l,
                "title": row.title,
                "n_works": row.n_works,
                "oa_type": row.oa_type,
            }
            for row in journal_rows
        ],
        "topics": top_topics,
        "similar": similar,
        "alternatives": alternatives,
        "works": [
            {
                "pure_uuid": row.pure_uuid,
                "title": row.title,
                "year": row.year,
                "doi": row.doi_normalized,
                "oa_status": row.oa_status,
                "journal_issn_l": row.journal_issn_l,
                "journal_title": row.journal_title,
            }
            for row in work_rows
        ],
    }
