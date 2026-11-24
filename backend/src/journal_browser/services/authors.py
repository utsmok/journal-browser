"""Author browsing: search, profile bundle, embedding-based recommendations.

All journal-level views reuse search.base_query, so the global corpus
cutoff (works_window_plus > 3: the journal's own OpenAlex works in the
window, materialized from counts_by_year — not the institution's works),
proceedings exclusion and ignore-list apply to every suggestion; the
oa_type case is shared via search.oa_type_case."""

from typing import Any

from sqlalchemy import case, false, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import PEOPLE_BASE_URL, get_settings, work_type_excluded
from ..identifiers import normalize_doi
from ..models import (
    Author,
    AuthorIdentity,
    AuthorWork,
    Institution,
    Journal,
    JournalFlags,
    OpenalexWork,
    PeopleUtwentePerson,
    PurePersonOrg,
    Work,
    WorkPureAuthor,
)
from ..queries import cache_epoch, work_type_normalized
from ..topics import topic_mass
from .authorship import (
    OPENALEX_URL,
    group_gap_entries,
    journal_publisher_map,
    tag_pure_matches,
    ut_authors_for_authorships,
    ut_roster_by_aids,
)
from .cache import SWR_CACHE, swr_get, swr_put, swr_schedule
from .facets import author_facets
from .search import base_query, escape_like, oa_type_case
from .work_sources import authorships_by_wid, openalex_only_works_for_author
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

#: Trigram word-similarity thresholds for q matching: names stay strict
#: (0.5 so a 40k-row roster surfaces plausible near-names without noise),
#: topic and research-group fallbacks use pg_trgm's default (0.3). Set
#: per pass via SET LOCAL so the %> operator stays index-accelerated.
_NAME_SIMILARITY_THRESHOLD = 0.5
_FALLBACK_SIMILARITY_THRESHOLD = 0.3

#: Where q can still match after zero name hits: what the author works
#: on, then where they sit. The response reports the field that matched
#: (q_match) so the UI can label the result set ("authors working on X").
_Q_FALLBACK_FIELDS = (("primary_topic", "topic"), ("research_group", "group"))


def _fold(column: Any) -> Any:
    """Diacritics fold so "Follmer" finds "Föllmer"; translate() keeps
    this extension-free."""
    return func.translate(func.lower(column), _FOLD_SRC, _FOLD_DST)


def _q_cond(column: Any, qstr: str) -> Any:
    """Substring match OR trigram word similarity for typos ("vermoer"
    finds "Vermeer"); the folded expression hits the trigram GIN index
    on both arms."""
    fold = _fold(column)
    return or_(
        fold.like(
            func.translate(func.lower(f"%{escape_like(qstr)}%"), _FOLD_SRC, _FOLD_DST),
            escape="\\",
        ),
        fold.op("%>")(qstr),
    )


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
    of the sorted matches.

    q first matches names (substring + trigram typos). When that finds
    nothing and the user typed a q, it falls back to primary_topic, then
    research_group, so "philosophy" surfaces the authors working on
    philosophy or sitting in the Philosophy group. Each response carries
    q_match: the field that produced the results ("name", "topic" or
    "group"), which the UI turns into a label."""
    result = await _search_authors(
        session,
        institution_id,
        q,
        limit,
        require_confirmed,
        faculty=faculty,
        org=org,
        has_orcid=has_orcid,
        works=works,
        last_pub=last_pub,
        topic=topic,
        sort=sort,
        offset=offset,
        year_range=year_range,
    )
    if not (q and q.strip()) or result["total"] > 0:
        return result
    for field, match in _Q_FALLBACK_FIELDS:
        result = await _search_authors(
            session,
            institution_id,
            q,
            limit,
            require_confirmed,
            faculty=faculty,
            org=org,
            has_orcid=has_orcid,
            works=works,
            last_pub=last_pub,
            topic=topic,
            sort=sort,
            offset=offset,
            year_range=year_range,
            q_field=field,
            q_match=match,
        )
        if result["total"] > 0:
            break
    if result["total"] == 0:
        # No pass matched: report the default field, not the last attempt.
        result["q_match"] = "name"
    return result


async def _search_authors(
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
    q_field: str = "name",
    q_match: str = "name",
) -> dict[str, Any]:
    """One q pass over a single Author column (name, primary_topic or
    research_group). When the confirmed-affiliation gate empties a q
    search, the query reruns without it so a real (unconfirmed)
    researcher stays findable; total, items and facets then all come from
    the ungated pass. Facet counts and total describe the filtered set,
    never the page.

    With an active publication-year range, n_works / last_pub_year (payload,
    sorts, strata and last-pub filters, facet buckets) become query-time
    aggregates over the author's stored work edges inside the range instead
    of the denormalized snapshot columns — the same edge population the
    snapshot counts. Without a range nothing joins: the queries stay
    byte-identical to the snapshot-serving path."""
    target_col = getattr(Author, q_field)
    roster = await session.scalar(
        select(func.count()).select_from(Author).where(Author.institution_id == institution_id)
    )
    if not roster:
        return {"enabled": False, "total": 0, "items": [], "facets": {}, "q_match": q_match}
    base: list[Any] = [Author.institution_id == institution_id]
    if require_confirmed:
        base.append(Author.confirmed.is_(True))
    q_cond = None
    if q and q.strip():
        qstr = q.strip()
        q_cond = _q_cond(target_col, qstr)
        # Index-accelerated %> needs the session threshold; SET LOCAL dies
        # with the request's transaction, so the pool is unaffected.
        threshold = (
            _NAME_SIMILARITY_THRESHOLD if q_field == "name" else _FALLBACK_SIMILARITY_THRESHOLD
        )
        await session.execute(text(f"SET LOCAL pg_trgm.word_similarity_threshold = {threshold}"))
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
    if require_confirmed and q_cond is not None:
        # The confirmed gate hides a real (unconfirmed) q match in two ways:
        # it can empty the search entirely, or — now that q also matches
        # trigram cousins — leave only a fuzzy confirmed hit (confirmed
        # "Harmen van Corbach" for q=loorbach) masking the exact-name
        # person (unconfirmed "Nicole Loorbach"). One LIKE count answers
        # both cases (the trgm index serves the arm), FILTERed by
        # confirmed. An exact-field match is strong evidence a user typed
        # a real name, so the search reruns ungated; fuzzy-only confirmed
        # matches alone never trigger it.
        like_arm = _fold(target_col).like(
            func.translate(func.lower(f"%{escape_like(qstr)}%"), _FOLD_SRC, _FOLD_DST),
            escape="\\",
        )
        ungated_sub, gated_sub = (
            await session.execute(
                select(
                    func.count(),
                    func.count().filter(Author.confirmed.is_(True)),
                )
                .select_from(Author)
                .where(Author.institution_id == institution_id, like_arm)
            )
        ).one()
        if total == 0 or (ungated_sub > 0 and gated_sub == 0):
            # Rerun the same query ungated so total, page and facets
            # describe what the caller gets.
            return await _search_authors(
                session,
                institution_id,
                q,
                limit,
                require_confirmed=False,
                faculty=faculty,
                org=org,
                has_orcid=has_orcid,
                works=works,
                last_pub=last_pub,
                topic=topic,
                sort=sort,
                offset=offset,
                year_range=year_range,
                q_field=q_field,
                q_match=q_match,
            )
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
            case((target_col.ilike(f"{escape_like(qstr)}%", escape="\\"), 1), else_=0).desc(),
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
        "q_match": q_match,
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
        select(JournalFlags.issn_l, JournalFlags.deal_covered, JournalFlags.openaire_diamond)
        .where(JournalFlags.institution_id == iid)
        .subquery()
    )
    return (
        await session.execute(
            select(
                Work.journal_issn_l.label("issn_l"),
                Journal.title.label("title"),
                func.count().label("n_works"),
                oa_type_case(flags.c.deal_covered, flags.c.openaire_diamond),
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
                flags.c.openaire_diamond,
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
    """Recommendable base_query + cosine distance to `vector`, author journals excluded."""
    return (
        base_query(institution_id=institution_id, active=True, vouched=True)
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


async def author_gap_works(
    session: AsyncSession,
    institution: Institution,
    author: Author,
    year_range: tuple[int, int] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """One definition of the author's OpenAlex-only gap population: store
    rows attributed to the author that survive the institution's
    publication-year window (an explicit clamped range replaces the
    bounds) and the excluded work types, deduped by DOI against the
    author's whole Pure list (uncapped — DOI identity does not stop at
    the works cap), then tagged by tag_pure_matches so rows a Pure record
    explains stay distinguishable. Returns (gated, missing); missing is
    the untagged subset, the likely misses. The profile section, its
    total/likely_missing counts, and the missed-works CSV export all
    consume these two lists, so the card headline, its sub-count and the
    download can never quote three different numbers. None = the works
    source could not answer (foreign DSN institution); callers degrade."""
    rows = await openalex_only_works_for_author(session, institution, author)
    if rows is None:
        return None
    if year_range is not None:
        year_start, year_end_bound = year_range
    else:
        year_start = institution.data_window_start
        year_end_bound = (
            institution.data_window_end if institution.data_window_end is not None else 9999
        )
    seen_dois = set(
        await session.scalars(
            select(Work.doi_normalized)
            .join(AuthorWork, author_works_join(institution.id, author.pure_uuid))
            .where(
                Work.institution_id == institution.id,
                Work.retired_at.is_(None),
                Work.doi_normalized.is_not(None),
            )
        )
    )
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
                "authorships": row.get("authorships"),
                # Work parts (OpenAlex, Nov 2026); the DSN path's rows
                # lack them and default to []/False.
                "parent_works": row.get("parent_works") or [],
                "is_part": bool(row.get("is_part")),
            }
        )
    # Explain rows that are in fact in Pure: a DOI belonging to a Pure
    # record outside the author's list (a book, or a record not linked to
    # them), a chapter whose parent book is in Pure, or a same-title Pure
    # record sharing the author. Tagged over the WHOLE gated list so the
    # counts stay exact beyond the shown slice; untagged rows — the likely
    # misses — carry pure_match=None. Every tag must share an author:
    # this author themself.
    await tag_pure_matches(
        session,
        institution,
        gated,
        [{author.pure_uuid}] * len(gated),
        check_own_doi=True,
    )
    missing = [g for g in gated if g.get("pure_match") is None]
    return gated, missing


async def _openalex_only_section(
    session: AsyncSession,
    institution: Institution,
    author: Author,
    year_range: tuple[int, int] | None = None,
) -> tuple[dict[str, Any], int | None]:
    """The profile's openalex_only section: OpenAlex-attributed works the
    Pure population does not hold, as their own list — never truncated by
    the works cap (that split-off fixes authors with >= 200 Pure works,
    whose missed works used to render zero items while the count said
    otherwise). author_gap_works owns the population and both counts
    (total = gated rows, likely_missing = the untagged subset); this
    section adds the grouped entries and the shown-slice enrichment.

    Returns the section plus the exact gated count (None when the source
    could not answer — the caller then leaves openalex_only_count unset
    and the section degrades to available=False)."""
    gap = await author_gap_works(session, institution, author, year_range)
    if gap is None:
        return (
            {"total": 0, "likely_missing": 0, "entries_total": 0, "items": [], "available": False},
            None,
        )
    gated, missing = gap
    if not gated:
        return (
            {"total": 0, "likely_missing": 0, "entries_total": 0, "items": [], "available": True},
            0,
        )
    likely_missing = len(missing)
    # total is the exact gated count; missing parts group under their main
    # work and only the shown entries' parts get the authorships,
    # publisher and roster enrichment (the bulk fetch stays scalar).
    total = len(gated)
    entries, entries_total = await group_gap_entries(session, institution, gated)
    shown = entries[:OPENALEX_ONLY_CAP]
    to_serve = [e for e in shown if e["kind"] == "single"]
    to_serve += [p for e in shown if e["kind"] == "group" for p in e["parts"]]
    need_ash = [d["openalex_id"] for d in to_serve if d.get("authorships") is None]
    ash_map = await authorships_by_wid(session, institution, need_ash) if need_ash else {}
    for d in to_serve:
        if d.get("authorships") is None:
            d["authorships"] = ash_map.get(d["openalex_id"]) or []
    publishers = await journal_publisher_map(session, [d["journal_issn_l"] for d in to_serve])
    roster = await ut_roster_by_aids(
        session,
        institution,
        {
            aid.lower()
            for d in to_serve
            for entry in d.get("authorships") or []
            if (aid := str((entry or {}).get("a") or ""))
        },
    )
    for d in to_serve:
        authorships = d.pop("authorships")
        w_id = d["openalex_id"]
        d["pure_uuid"] = None
        d["openalex_url"] = f"{OPENALEX_URL}/{w_id}" if w_id else None
        d["publisher_name"] = publishers.get(d["journal_issn_l"])
        d["in_pure"] = False
        d["ut_authors"] = ut_authors_for_authorships(authorships, roster)
    return {
        "total": total,
        "likely_missing": likely_missing,
        "entries_total": entries_total,
        "items": shown,
        "available": True,
    }, total


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
    """Full profile bundle; None = unknown author (404 upstream). Cached via SWR."""
    iid = institution.id
    swr_key = (
        "author_profile",
        iid,
        pure_uuid,
        year_range,
        institution.research_portal_url,
    )
    epoch = await cache_epoch(session)
    fresh, bundle = swr_get(SWR_CACHE, swr_key, epoch)
    if fresh:
        return bundle
    if bundle is not None:
        swr_schedule(SWR_CACHE, swr_key, _author_profile_factory(iid, pure_uuid, year_range))
        return bundle
    epoch, built = await _build_author_profile(
        session, institution, pure_uuid, year_range=year_range
    )
    if built is None:
        return None
    swr_put(SWR_CACHE, swr_key, epoch, built)
    return built


def _author_profile_factory(iid: int, pure_uuid: str, year_range: tuple[int, int] | None):
    async def _factory():
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from ..db import get_engine

        async with async_sessionmaker(get_engine(), expire_on_commit=False)() as session:
            inst = (await session.scalars(select(Institution).where(Institution.id == iid))).one()
            return await _build_author_profile(session, inst, pure_uuid, year_range=year_range)

    return _factory


async def _build_author_profile(
    session: AsyncSession,
    institution: Institution,
    pure_uuid: str,
    *,
    year_range: tuple[int, int] | None = None,
) -> tuple[Any, dict[str, Any] | None]:
    """Uncached profile build; returns (epoch, bundle | None)."""
    iid = institution.id
    author = await session.scalar(
        select(Author).where(Author.institution_id == iid, Author.pure_uuid == pure_uuid)
    )
    if author is None:
        return await cache_epoch(session), None

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
                Work.work_type,
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

    # The author's Pure books ride along in the works list. harvest drops
    # author_works edges to book types, so the join above never sees them
    # — but the records exist (linked via work_pure_authors) and belong on
    # the page. They stay OUT of every count: n_works, oa_by_year and the
    # journals table aggregate over the AuthorWork edges below, untouched.
    book_rows = (
        await session.execute(
            select(
                Work.pure_uuid,
                Work.title,
                Work.year,
                Work.doi_normalized,
                Work.oa_status,
                Work.work_type,
                Work.journal_issn_l,
                Journal.title.label("journal_title"),
            )
            .join(
                WorkPureAuthor,
                (WorkPureAuthor.institution_id == iid)
                & (WorkPureAuthor.work_pure_uuid == Work.pure_uuid),
            )
            .outerjoin(Journal, Journal.issn_l == Work.journal_issn_l)
            .where(
                Work.institution_id == iid,
                Work.retired_at.is_(None),
                *work_year_window(institution, year_range),
                WorkPureAuthor.person_uuid == pure_uuid,
                work_type_normalized(Work.work_type).in_(("book", "monograph")),
            )
            .order_by(Work.year.desc(), func.lower(Work.title))
        )
    ).all()
    known_uuids = {row.pure_uuid for row in work_rows}
    all_work_rows = sorted(
        [*work_rows, *(r for r in book_rows if r.pure_uuid not in known_uuids)],
        key=lambda r: (-(r.year or 0), (r.title or "").lower()),
    )

    # One batched OpenAlex store lookup for every DOI on the page: lowest
    # w_id wins deterministically when several store rows share a DOI.
    oa_ids_by_doi: dict[str, str] = {}
    works_dois = sorted({row.doi_normalized for row in all_work_rows if row.doi_normalized})
    if works_dois:
        oa_rows = (
            await session.execute(
                select(OpenalexWork.doi_normalized, func.min(OpenalexWork.w_id).label("w_id"))
                .where(
                    OpenalexWork.institution_id == iid,
                    OpenalexWork.doi_normalized.in_(works_dois),
                )
                .group_by(OpenalexWork.doi_normalized)
            )
        ).all()
        oa_ids_by_doi = {row.doi_normalized: row.w_id for row in oa_rows}

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
        # topics.topic_mass).
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
        session, institution, author, year_range
    )
    from .collaborations import top_partners_for_author

    top_partners = await top_partners_for_author(session, institution, author.pure_uuid, year_range)

    return await cache_epoch(session), {
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
                "work_type": row.work_type,
                "journal_issn_l": row.journal_issn_l,
                "journal_title": row.journal_title,
                "pure_url": (
                    f"{institution.research_portal_url}/en/publications/{row.pure_uuid}"
                    if institution.research_portal_url
                    else None
                ),
                "openalex_url": (
                    f"{OPENALEX_URL}/{oa_ids_by_doi[row.doi_normalized]}"
                    if row.doi_normalized in oa_ids_by_doi
                    else None
                ),
                "in_pure": True,
                # The OpenAlex oa_status sync only overwrites DOI-matched
                # rows; a green status on a DOI-less record is Pure's own
                # access flag — the venue's OA model is unverified.
                "oa_status_source": "pure" if row.doi_normalized is None else "openalex",
            }
            for row in all_work_rows
        ],
        "top_partners": top_partners,
        "openalex_only": openalex_section,
        "openalex_only_count": openalex_only_count,
    }
