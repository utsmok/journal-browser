"""Author browsing: search, profile bundle, embedding-based recommendations.

All journal-level views reuse search.base_query, so the per-institution
corpus cutoff (works_window_plus > 3), proceedings exclusion and ignore-list
apply to every suggestion; the oa_type case is shared via search._oa_type."""

from typing import Any

from sqlalchemy import case, false, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings, work_type_excluded
from ..harvest.authors import topic_mass
from ..harvest.common import normalize_doi
from ..harvest.people_utwente import PEOPLE_BASE_URL
from ..models import (
    Author,
    AuthorIdentity,
    AuthorWork,
    Institution,
    Journal,
    JournalFlags,
    PeopleUtwentePerson,
    PurePersonOrg,
    Work,
)
from .authorship import (
    OPENALEX_URL,
    journal_publisher_map,
    ut_authors_for_authorships,
    ut_roster_by_aids,
)
from .facets import author_facets
from .search import _like, _oa_type, base_query
from .work_sources import openalex_only_works_for_author
from .works_query import (
    YEAR_BUCKETS,
    author_works_join,
    empty_year_buckets,
    strata_cond,
    unit_work_join,
    work_window,
    work_year_window,
)

#: Search page + recommendation list sizes.
DEFAULT_LIMIT = 25
MAX_LIMIT = 100
SIMILAR_ALL_LIMIT = 8
SIMILAR_FILTERED_LIMIT = 5
ALTERNATIVE_JOURNALS = 5
ALTERNATIVE_OPTIONS = 3
WORKS_CAP = 200
#: Safety cap for the openalex_only section's item list, mirroring the
#: venue gap-list cap (authorship.GAP_ITEM_CAP): the UI renders "Showing
#: N most recent" and links works.csv?scope=missed for the full list.
#: total stays exact beyond the cap; enriching only the shown slice also
#: keeps prolific authors (600+ missed works) fast to serve.
OPENALEX_ONLY_CAP = 50

# European diacritics folded to plain ASCII on both sides of author-name
# search, so umlaut-free queries match umlauted names ("follmer" -> "Föllmer").
_FOLD_SRC = "áàâäãåéèêëíìîïóòôöõúùûüýÿñçšž"
_FOLD_DST = "aaaaaaeeeeiiiioooooouuuuyyncsz"

#: Response buckets of works.oa_status are shared (works_query.YEAR_BUCKETS);
#: the contract's year split historically had no diamond column but now does.

LAST_PUB_BUCKETS = ("2025-2026", "2022-2024", "2020-2021", "none")

_LAST_PUB_BOUNDS = {"2025-2026": (2025, 2026), "2022-2024": (2022, 2024), "2020-2021": (2020, 2021)}


def _last_pub_cond(column: Any, values: list[str]) -> Any:
    parts = []
    for value in values:
        if value == "none":
            parts.append(column.is_(None))
        elif bounds := _LAST_PUB_BOUNDS.get(value):
            parts.append(column.between(*bounds))
    return or_(*parts) if parts else false()


def _has_orcid_cond(value: str) -> Any:
    if value == "yes":
        return Author.orcid.is_not(None)
    if value == "no":
        return Author.orcid.is_(None)
    return false()


def _filter_conds(
    faculty: list[str] | None,
    org: list[str] | None,
    has_orcid: str | None,
    works: list[str] | None,
    last_pub: list[str] | None,
    topic: list[str] | None,
    n_col: Any | None = None,
    last_col: Any | None = None,
) -> dict[str, Any]:
    """One condition per active facet dimension; keyed so a facet's counts
    can drop its own dimension while keeping all others. n_col/last_col
    override the works strata and last-pub columns (the year-scoped
    aggregates when a publication-year range is active)."""
    n_col = n_col if n_col is not None else Author.n_works
    last_col = last_col if last_col is not None else Author.last_pub_year
    conds: dict[str, Any] = {}
    if faculty:
        conds["faculty"] = Author.faculty.in_(faculty)
    if org:
        conds["org"] = Author.research_group.in_(org)
    if topic:
        conds["topic"] = Author.primary_topic.in_(topic)
    if works:
        conds["works"] = strata_cond(n_col, works)
    if last_pub:
        conds["last_pub"] = _last_pub_cond(last_col, last_pub)
    if has_orcid:
        conds["has_orcid"] = _has_orcid_cond(has_orcid)
    return conds


#: Author search sort keys (works_desc default).
SORT_KEYS = ("works_desc", "name_asc", "name_desc", "last_pub_desc")


async def search_authors(
    session: AsyncSession,
    institution_id: int,
    q: str | None,
    limit: int,
    require_confirmed: bool,
    faculty: list[str] | None = None,
    org: list[str] | None = None,
    has_orcid: str | None = None,
    works: list[str] | None = None,
    last_pub: list[str] | None = None,
    topic: list[str] | None = None,
    sort: str = "works_desc",
    offset: int = 0,
    year_range: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Author roster for one institution. total is the filter match count
    (the whole roster when nothing is set); items are the offset/limit page
    of the sorted matches. require_confirmed restricts the search list to
    authors.confirmed; profile endpoints stay unfiltered. Facet counts and
    total describe the filtered set, never the page.

    With an active publication-year range, n_works / last_pub_year (payload,
    sorts, strata and last-pub filters, facet buckets) become query-time
    aggregates over the author's stored work edges inside the range instead
    of the denormalized snapshot columns — the same edge population the
    snapshot counts. Without a range nothing joins: the queries stay
    byte-identical to the snapshot-serving path."""
    roster = await session.scalar(
        select(func.count()).select_from(Author).where(Author.institution_id == institution_id)
    )
    if not roster:
        return {"enabled": False, "total": 0, "items": [], "facets": {}}
    base: list[Any] = [Author.institution_id == institution_id]
    if require_confirmed:
        base.append(Author.confirmed.is_(True))
    q_cond = None
    if q and q.strip():
        qstr = q.strip()
        # Diacritics fold so "Follmer" finds "Föllmer"; translate() keeps
        # this extension-free, and the roster is small enough to scan.
        q_cond = func.translate(func.lower(Author.name), _FOLD_SRC, _FOLD_DST).like(
            func.translate(func.lower(f"%{_like(qstr)}%"), _FOLD_SRC, _FOLD_DST),
            escape="\\",
        )
    # Year-scoped per-author aggregates over the stored work edges (the
    # same population the snapshot counts, so the clamped full window
    # reproduces the denormalized columns exactly); None = no range, no join.
    scoped = None
    if year_range is not None:
        lo, hi = year_range
        scoped = (
            select(
                AuthorWork.author_pure_uuid.label("author_pure_uuid"),
                func.count().label("n"),
                func.max(Work.year).label("last_year"),
            )
            .select_from(AuthorWork)
            .join(Work, unit_work_join(institution_id))
            .where(AuthorWork.institution_id == institution_id, Work.year.between(lo, hi))
            .group_by(AuthorWork.author_pure_uuid)
            .subquery()
        )
    n_col = func.coalesce(scoped.c.n, 0) if scoped is not None else Author.n_works
    last_col = scoped.c.last_year if scoped is not None else Author.last_pub_year
    conds = _filter_conds(
        faculty, org, has_orcid, works, last_pub, topic, n_col=n_col, last_col=last_col
    )
    query = select(Author).where(*base, *conds.values())
    if scoped is not None:
        query = query.outerjoin(scoped, scoped.c.author_pure_uuid == Author.pure_uuid)
    if q_cond is not None:
        query = query.where(q_cond)
    total_stmt = (
        select(func.count())
        .select_from(Author)
        .where(*base, *conds.values(), *([q_cond] if q_cond is not None else []))
    )
    if scoped is not None:
        total_stmt = total_stmt.outerjoin(scoped, scoped.c.author_pure_uuid == Author.pure_uuid)
    total = await session.scalar(total_stmt)
    # Sort after filters; stable tiebreak by name, then pure_uuid. The q
    # prefix-rank boost only applies to the default works sort.
    if sort == "name_asc":
        order = (func.lower(Author.name).asc(), Author.pure_uuid)
    elif sort == "name_desc":
        order = (func.lower(Author.name).desc(), Author.pure_uuid)
    elif sort == "last_pub_desc":
        order = (
            last_col.desc().nulls_last(),
            func.lower(Author.name),
            Author.pure_uuid,
        )
    elif q_cond is not None:
        order = (
            case((Author.name.ilike(f"{_like(qstr)}%", escape="\\"), 1), else_=0).desc(),
            n_col.desc(),
            func.lower(Author.name),
            Author.pure_uuid,
        )
    else:
        order = (n_col.desc(), func.lower(Author.name), Author.pure_uuid)
    stmt = query.order_by(*order).offset(offset).limit(min(limit, MAX_LIMIT))
    if scoped is None:
        rows = [
            (a, a.n_works, a.last_pub_year) for a in (await session.execute(stmt)).scalars().all()
        ]
    else:
        rows = [
            (row[0], row.n_eff, row.last_eff)
            for row in (
                await session.execute(
                    stmt.add_columns(
                        n_col.label("n_eff"),
                        last_col.label("last_eff"),
                    )
                )
            ).all()
        ]
    facet_base = list(base) + ([q_cond] if q_cond is not None else [])
    facets = await author_facets(
        session, facet_base, conds, scoped=scoped, n_col=n_col, last_col=last_col
    )
    return {
        "enabled": True,
        "total": total,
        "offset": offset,
        "sort": sort,
        "items": [
            {
                "pure_uuid": a.pure_uuid,
                "name": a.name,
                "faculty": a.faculty,
                "research_group": a.research_group,
                "institute": a.institute,
                "n_works": n,
                "orcid": a.orcid,
                "confirmed": a.confirmed,
                "last_pub_year": last,
                "primary_topic": a.primary_topic,
            }
            for a, n, last in rows
        ],
        "facets": facets,
    }


async def _author_journals(
    session: AsyncSession, institution: Institution, pure_uuid: str
) -> list[Any]:
    """The author's distinct venues with work counts + effective oa_type,
    works count desc (ties by issn for determinism), inside the
    institution's publication-year window (topic weighting inherits it).
    Admin-ignored ISSNs are not venues."""
    iid = institution.id
    ignored = get_settings().ignored_issns
    flags = (
        select(JournalFlags.issn_l, JournalFlags.deal_covered)
        .where(JournalFlags.institution_id == iid)
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
                author_works_join(iid, pure_uuid),
            )
            .join(Journal, Journal.issn_l == Work.journal_issn_l)
            .join(flags, flags.c.issn_l == Journal.issn_l)
            .where(
                Work.institution_id == iid,
                Work.retired_at.is_(None),
                *work_window(institution),
                *([Journal.issn_l.not_in(sorted(set(ignored)))] if ignored else []),
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
    """Works-weighted average embedding; None without usable vectors.

    A zero (or numerically degenerate) vector is not usable: cosine distance
    to it is NaN, and NaN distances defeat hnsw.iterative_scan=strict_order
    early termination (measured 6.6 s scans with pgvector on live)."""
    usable = [(w, [float(x) for x in vec]) for w, vec in weighted if vec is not None]
    total = sum(w for w, _vec in usable)
    if not usable or total <= 0:
        return None
    out = [0.0] * len(usable[0][1])
    for w, vec in usable:
        for i, value in enumerate(vec):
            out[i] += w * value
    return [value / total for value in out]


def _is_degenerate(vector: list[float]) -> bool:
    """True when the vector's norm is ~0: every component underflows the
    weighted mean (or the mean itself cancelled out)."""
    return not any(abs(x) > 1e-12 for x in vector)


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
    # NaN cosine distances (zero/degenerate query vector) defeat the strict
    # iterative scan's early termination; skip HNSW entirely for them.
    if avg is not None and not _is_degenerate(avg):
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
            if row.oa_type in ("hybrid", "subscription")
            and row.issn_l in embeddings
            and not _is_degenerate([float(x) for x in embeddings[row.issn_l]])
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


async def _openalex_only_section(
    session: AsyncSession,
    institution: Institution,
    author: Author,
    work_rows: Any,
    year_range: tuple[int, int] | None = None,
) -> tuple[dict[str, Any], int | None]:
    """The profile's openalex_only section: OpenAlex-attributed works the
    Pure population does not hold, as their own list — never truncated by
    the works cap (that split-off fixes authors with >= 200 Pure works,
    whose missed works used to render zero items while the count said
    otherwise).

    Returns the section plus the exact gated count (None when the source
    could not answer — the caller then leaves openalex_only_count unset
    and the section degrades to available=False).

    Quality gates keep the section honest: the institution's
    publication-year window applies (an explicit clamped range replaces
    the bounds), excluded work types (preprints/books)
    drop out, and a DOI that matches a local work is skipped (same
    publication; the Pure copy stays the display record)."""
    rows = await openalex_only_works_for_author(session, institution, author)
    if rows is None:
        return {"total": 0, "items": [], "available": False}, None
    if not rows:
        return {"total": 0, "items": [], "available": True}, 0
    if year_range is not None:
        year_start, year_end_bound = year_range
    else:
        year_start = institution.data_window_start
        year_end_bound = (
            institution.data_window_end if institution.data_window_end is not None else 9999
        )
    seen_dois = {doi for row in work_rows if (doi := normalize_doi(row.doi_normalized))}
    gated: list[dict[str, Any]] = []
    for row in sorted(
        rows,
        key=lambda r: (r["year"] is None, -(r["year"] or 0), (r["title"] or "").lower()),
    ):
        year = row["year"]
        if year is None or not year_start <= year <= year_end_bound:
            continue
        if work_type_excluded(row["work_type"]):
            continue
        doi = normalize_doi(row["doi"])
        if doi is not None:
            if doi in seen_dois:
                continue
            seen_dois.add(doi)
        gated.append(
            {
                "title": row["title"] or "Untitled",
                "year": year,
                "doi": row["doi"],
                "oa_status": row["oa_status"] or "unknown",
                "work_type": row["work_type"],
                "journal_issn_l": row["issn_l"],
                "journal_title": row["venue_name"],
                "openalex_id": row.get("openalex_id"),
                "authorships": row.get("authorships") or [],
            }
        )
    # total is the exact gated count; publisher/roster enrichment only
    # covers the slice that ships to the client.
    total = len(gated)
    gated = gated[:OPENALEX_ONLY_CAP]
    publishers = await journal_publisher_map(session, [g["journal_issn_l"] for g in gated])
    roster = await ut_roster_by_aids(
        session,
        institution,
        {
            aid.lower()
            for g in gated
            for entry in g["authorships"]
            if (aid := str((entry or {}).get("a") or ""))
        },
    )
    items = []
    for g in gated:
        authorships = g.pop("authorships")
        w_id = g["openalex_id"]
        items.append(
            {
                "pure_uuid": None,
                **g,
                "openalex_url": f"{OPENALEX_URL}/{w_id}" if w_id else None,
                "publisher_name": publishers.get(g["journal_issn_l"]),
                "in_pure": False,
                "ut_authors": ut_authors_for_authorships(authorships, roster),
            }
        )
    return {"total": total, "items": items, "available": True}, total


async def author_avatar(
    session: AsyncSession, institution: Institution, pure_uuid: str
) -> tuple[bytes, str] | None:
    """The author's people.utwente.nl portrait bytes + media type: served
    for uuid-verified matches (or admin-confirmed candidates); None when
    absent or unverified."""
    iid = institution.id
    people_row = await session.scalar(
        select(PeopleUtwentePerson).where(
            PeopleUtwentePerson.institution_id == iid,
            PeopleUtwentePerson.person_uuid == pure_uuid,
        )
    )
    if people_row is None or not people_row.slug or people_row.photo_bytes is None:
        return None
    if people_row.status != "matched":
        confirmed = (
            await session.scalar(
                select(AuthorIdentity.author_pure_uuid).where(
                    AuthorIdentity.institution_id == iid,
                    AuthorIdentity.author_pure_uuid == pure_uuid,
                    AuthorIdentity.source == "people",
                    AuthorIdentity.status == "confirmed",
                )
            )
            is not None
        )
        if not confirmed:
            return None
    return people_row.photo_bytes, people_row.photo_media_type or "application/octet-stream"


async def author_profile(
    session: AsyncSession,
    institution: Institution,
    pure_uuid: str,
    year_range: tuple[int, int] | None = None,
) -> dict[str, Any] | None:
    """Full profile bundle; None = unknown author (404 upstream). All
    per-author work views are bounded to the institution's data window,
    or to the explicit publication-year range when one is active (the
    journals list, suggestions and topics keep the window: journal
    attributes stay unfiltered by the year range)."""
    iid = institution.id
    author = await session.scalar(
        select(Author).where(Author.institution_id == iid, Author.pure_uuid == pure_uuid)
    )
    if author is None:
        return None

    # people.utwente.nl profile: served when uuid-verified, or when the
    # admin confirmed the (name-only) candidate identity row.
    people_row = await session.scalar(
        select(PeopleUtwentePerson).where(
            PeopleUtwentePerson.institution_id == iid,
            PeopleUtwentePerson.person_uuid == pure_uuid,
        )
    )
    people_confirmed = people_row is not None and people_row.status == "matched"
    if not people_confirmed and people_row is not None:
        people_confirmed = (
            await session.scalar(
                select(AuthorIdentity.author_pure_uuid).where(
                    AuthorIdentity.institution_id == iid,
                    AuthorIdentity.author_pure_uuid == pure_uuid,
                    AuthorIdentity.source == "people",
                    AuthorIdentity.status == "confirmed",
                )
            )
            is not None
        )
    people_section = None
    research_portal_url = None
    if people_row is not None and people_confirmed and people_row.slug:
        people_section = {
            "slug": people_row.slug,
            "url": f"{PEOPLE_BASE_URL}{people_row.slug}",
            "canonical_name": people_row.canonical_name,
            "email": people_row.email,
            "orgs": [o.get("name") for o in people_row.orgs or [] if o.get("name")],
            "faculty_abbr": people_row.faculty_abbr,
            "has_photo": people_row.photo_bytes is not None,
        }
        research_portal_url = people_row.portal_person_url
    if research_portal_url is None:
        # No people profile (or unverified): the portal page still exists
        # when the portal persons listings carried this person.
        has_portal_binding = (
            await session.scalar(
                select(PurePersonOrg.person_uuid).where(
                    PurePersonOrg.institution_id == iid,
                    PurePersonOrg.person_uuid == pure_uuid,
                )
            )
            is not None
        )
        if has_portal_binding and institution.research_portal_url:
            research_portal_url = f"{institution.research_portal_url}/en/persons/{pure_uuid}"

    work_join = author_works_join(iid, pure_uuid)
    in_window = (
        Work.institution_id == iid,
        Work.retired_at.is_(None),
        *work_year_window(institution, year_range),
    )
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
            .where(*in_window)
            .order_by(Work.year.desc(), func.lower(Work.title))
            .limit(WORKS_CAP)
        )
    ).all()

    year_rows = (
        await session.execute(
            select(Work.year, Work.oa_status, func.count().label("n"))
            .join(AuthorWork, work_join)
            .where(*in_window)
            .group_by(Work.year, Work.oa_status)
        )
    ).all()
    by_year: dict[int, dict[str, int]] = {}
    for row in year_rows:
        bucket = by_year.setdefault(
            row.year, {"year": row.year, "total": 0, **empty_year_buckets()}
        )
        bucket["total"] += row.n
        if row.oa_status in YEAR_BUCKETS:
            bucket[row.oa_status] += row.n
    oa_by_year = [by_year[year] for year in sorted(by_year, reverse=True)]

    journal_rows = await _author_journals(session, institution, pure_uuid)
    if journal_rows:
        topic_rows = (
            await session.execute(
                select(Journal.issn_l, Journal.topics).where(
                    Journal.issn_l.in_([row.issn_l for row in journal_rows])
                )
            )
        ).all()
        topics_by_issn = {row.issn_l: row.topics or [] for row in topic_rows}
        # Same proportional spread as the ingest-time primary_topic (see
        # harvest.authors.topic_mass).
        mass = topic_mass({r.issn_l: r.n_works for r in journal_rows}, topics_by_issn)
    else:
        mass = {}
    top_topics = [
        {"name": name, "n": round(n)}
        for name, n in sorted(mass.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
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
    similar, alternatives = await _similar_sections(session, iid, journal_rows, embeddings)

    openalex_section, openalex_only_count = await _openalex_only_section(
        session, institution, author, work_rows, year_range
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
            "institute": author.institute,
            "orgs": author.orgs or [],
            "n_works": author.n_works,
            "people": people_section,
            "research_portal_url": research_portal_url,
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
                "in_pure": True,
            }
            for row in work_rows
        ],
        "openalex_only": openalex_section,
        "openalex_only_count": openalex_only_count,
    }
