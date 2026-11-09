"""UT authorship aggregates and CRIS-gap (OpenAlex-only) queries shared
by the journal, publisher, org-unit, and author detail views.

Two views over the same two stores:

- UT authorship: who at this institution authors a venue's canonical
  works. The population is the works-table set the search card counts
  (windowed, retired dropped, never-journal-output types excluded),
  joined through work_pure_authors → authors for faculty and research
  group attribution — the reverse view of the author and org-unit pages.
- OpenAlex-only ("not registered in Pure"): openalex_works store rows
  attributed to the venue (issn) or to the unit's member authors whose
  DOI matches no Pure work, gated like the author page's openalex-only
  merge: publication-year window, never-journal-output types dropped,
  NULL types kept (the store's vocabulary is sparser than Pure's).

Store-backed queries return available=False when the local
openalex_works projection has never run for the institution (the same
degradation the author page applies); the frontend hides the card
instead of showing a misleading zero.
"""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import column, exists, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from ..harvest.openalex_works import AUTHOR_SWEEP_PREFIX
from ..models import Author, Institution, Journal, OpenalexWork, Work, WorkPureAuthor
from .works_query import work_type_not_excluded, work_year_window, year_end

TOP_AUTHORS = 10
#: Items served per OpenalexOnly payload; total stays exact beyond it.
GAP_ITEM_CAP = 50
#: Canonical OpenAlex work url prefix (openalex.org/W...).
OPENALEX_URL = "https://openalex.org"


async def local_store_ready(session: AsyncSession, institution: Institution) -> bool:
    """True when the openalex_works projection has run for this
    institution at least once (store-backed cards may answer)."""
    return (
        await session.scalar(
            select(1).where(OpenalexWork.institution_id == institution.id).limit(1)
        )
    ) is not None


def _unavailable() -> dict[str, Any]:
    return {"total": 0, "items": [], "available": False}


def store_gates(institution: Institution, year_range: tuple[int, int] | None = None) -> list[Any]:
    """Window + type gates for store rows, mirroring the author page's
    openalex-only merge: NULL years drop (outside any window), NULL types
    stay (OpenAlex's vocabulary is sparser than Pure's). An explicit
    clamped year range replaces the window bounds."""
    start, end = (
        year_range if year_range else (institution.data_window_start, year_end(institution))
    )
    return [
        OpenalexWork.year.between(start, end),
        func.coalesce(work_type_not_excluded(OpenalexWork.work_type), True),
    ]


def not_in_pure() -> Any:
    """Anti-join: no Pure work holds this DOI. DOI-less store rows cannot
    match and therefore count — same rule the author page applies."""
    return ~exists(
        select(1).where(
            Work.institution_id == OpenalexWork.institution_id,
            Work.doi_normalized == OpenalexWork.doi_normalized,
        )
    )


def attributed_to_any(aids: list[str]) -> Any:
    """True when the store row names any of the given (lowercase) bare
    OpenAlex A-ids in its authorships array.

    Ids compare case-insensitively: authors.openalex_ids stores
    lowercase ids while the harvested authorships carry OpenAlex's
    canonical uppercase form (A1234567890)."""
    ash = func.jsonb_array_elements(OpenalexWork.authorships).table_valued(column("value", JSONB))
    return exists(
        select(1).select_from(ash).where(func.lower(ash.c.value.op("->>")("a")).in_(aids))
    )


async def ut_roster_by_aids(
    session: AsyncSession, institution: Institution, aids: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """Roster authors whose openalex_ids intersect the given bare A-ids,
    keyed by lowercase id, one map entry per (author, id) pair.

    Values carry pure_uuid for dedupe (merged A-ids point at one author);
    ut_authors_for_authorships projects them to the served shape. Ids
    compare case-insensitively — the store's authorships carry OpenAlex's
    canonical uppercase form, openalex_ids stores lowercase ids."""
    wanted = sorted({aid.lower() for aid in aids if aid})
    if not wanted:
        return {}
    ids = func.jsonb_array_elements_text(Author.openalex_ids).table_valued(column("value", JSONB))
    rows = (
        await session.execute(
            select(
                Author.pure_uuid,
                Author.name,
                Author.orcid,
                Author.faculty,
                Author.research_group,
                Author.institute,
                Author.openalex_ids,
            ).where(
                Author.institution_id == institution.id,
                exists(select(1).select_from(ids).where(func.lower(ids.c.value).in_(wanted))),
            )
        )
    ).all()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        entry = {
            "pure_uuid": r.pure_uuid,
            "name": r.name,
            "orcid": r.orcid,
            "faculty": r.faculty,
            "research_group": r.research_group,
            "institute": r.institute,
        }
        for aid in r.openalex_ids or []:
            out.setdefault(str(aid).lower(), entry)
    return out


def ut_authors_for_authorships(
    authorships: list[Any] | None, roster: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Roster attribution for one work's compact authorships, authorship
    order kept, one row per roster author even when merged A-ids repeat
    and blanks skipped."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in authorships or []:
        hit = roster.get(str((entry or {}).get("a") or "").lower())
        if hit is None or hit["pure_uuid"] in seen:
            continue
        seen.add(hit["pure_uuid"])
        out.append({k: hit[k] for k in ("name", "orcid", "faculty", "research_group", "institute")})
    return out


def work_authors_of(authorships: list[Any] | None) -> list[dict[str, Any]]:
    """Authors of one work from the compact authorships array, order
    kept, blank ids skipped."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in authorships or []:
        if not isinstance(entry, dict):
            continue
        aid = str(entry.get("a") or "").strip()
        if not aid or aid in seen:
            continue
        seen.add(aid)
        out.append({"openalex_id": aid, "name": entry.get("n"), "orcid": entry.get("o")})
    return out


async def journal_publisher_map(session: AsyncSession, issns: Iterable[str]) -> dict[str, str]:
    """issn_l -> display publisher (canonical when known, else the raw
    publisher_name) for the venue join."""
    wanted = sorted({issn for issn in issns if issn})
    if not wanted:
        return {}
    rows = (
        await session.execute(
            select(
                Journal.issn_l,
                func.coalesce(
                    func.nullif(Journal.publisher_canonical, ""), Journal.publisher_name
                ).label("publisher"),
            ).where(Journal.issn_l.in_(wanted))
        )
    ).all()
    return {r.issn_l: r.publisher for r in rows}


async def _store_gap_payload(
    session: AsyncSession, institution: Institution, predicate: list[Any]
) -> dict[str, Any]:
    """Shared shape: exact total + capped items over one store predicate
    (gates + attribution + anti-join), most recent first. Items carry the
    work identity (openalex id/url), the compact authorships, roster
    attribution for the institution's own authors, and venue context
    (journal + publisher)."""
    if not await local_store_ready(session, institution):
        return _unavailable()
    where = [OpenalexWork.institution_id == institution.id, *predicate]
    total = await session.scalar(select(func.count()).select_from(OpenalexWork).where(*where))
    rows = (
        await session.execute(
            select(
                OpenalexWork.w_id,
                OpenalexWork.title,
                OpenalexWork.year,
                OpenalexWork.doi_normalized,
                OpenalexWork.oa_status,
                OpenalexWork.work_type,
                OpenalexWork.venue_issn_l,
                OpenalexWork.venue_name,
                OpenalexWork.authorships,
            )
            .where(*where)
            .order_by(OpenalexWork.year.desc().nulls_last(), func.lower(OpenalexWork.title))
            .limit(GAP_ITEM_CAP)
        )
    ).all()
    publishers = await journal_publisher_map(session, [r.venue_issn_l for r in rows])
    roster = await ut_roster_by_aids(
        session,
        institution,
        {
            aid.lower()
            for r in rows
            for entry in r.authorships or []
            if (aid := str((entry or {}).get("a") or ""))
        },
    )
    items = [
        {
            "title": r.title,
            "year": r.year,
            "doi": r.doi_normalized,
            "oa_status": r.oa_status,
            "work_type": r.work_type,
            "venue": r.venue_name,
            "openalex_id": r.w_id,
            "openalex_url": f"{OPENALEX_URL}/{r.w_id}",
            "authors": work_authors_of(r.authorships),
            "ut_authors": ut_authors_for_authorships(r.authorships, roster),
            "journal_issn_l": r.venue_issn_l,
            "journal_title": r.venue_name,
            "publisher_name": publishers.get(r.venue_issn_l),
        }
        for r in rows
    ]
    return {"total": int(total or 0), "items": items, "available": True}


async def venue_openalex_only(
    session: AsyncSession,
    institution: Institution,
    *,
    issn_l: str | None = None,
    issns: list[str] | None = None,
    year_range: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Store works in the venue(s) the Pure population does not hold.

    One issn for the journal view, the publisher group's issn set for the
    publisher view. Attribution key is venue_issn_l — the same key the
    OpenAlex-side institution metrics use.

    Restricted to the institution-filter corpus (source != author-sweep):
    those rows were harvested under OpenAlex's institutions.id filter, so
    OpenAlex itself attributes them to this institution. Author-sweep rows
    carry an author's full profile — works OpenAlex attributes elsewhere
    or to no institution — and counting those here would report the
    venue's global output as a CRIS gap."""
    venue_issns = [issn_l] if issn_l is not None else sorted(set(issns or []))
    if not venue_issns:
        return {"total": 0, "items": [], "available": True}
    return await _store_gap_payload(
        session,
        institution,
        [
            OpenalexWork.venue_issn_l.in_(venue_issns),
            OpenalexWork.source != AUTHOR_SWEEP_PREFIX,
            *store_gates(institution, year_range),
            not_in_pure(),
        ],
    )


async def author_ids_openalex_only(
    session: AsyncSession,
    institution: Institution,
    aids: list[str],
    year_range: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Store works attributed to any of the given OpenAlex author ids the
    Pure population does not hold (org-unit gap card).

    Attribution unnests the authorships array and compares bare A-ids
    case-insensitively: authors.openalex_ids stores lowercase ids while
    the store's authorships carry OpenAlex's canonical uppercase form, so
    a work counts once however many of the unit's authors it names."""
    flat = sorted(
        {aid.lower() for row in aids for aid in (row if isinstance(row, list) else [row]) if aid}
    )
    if not flat:
        return {"total": 0, "items": [], "available": await local_store_ready(session, institution)}
    return await _store_gap_payload(
        session,
        institution,
        [attributed_to_any(flat), *store_gates(institution, year_range), not_in_pure()],
    )


async def venue_authorship(
    session: AsyncSession,
    institution: Institution,
    *,
    issn_l: str | None = None,
    issns: list[str] | None = None,
    year_range: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Who at this institution authors the venue's canonical works.

    Distinct works per faculty and per research group plus the top
    authors, all over one population: the works-table rows the search
    card counts, restricted to rows with at least one UT author edge.
    Rows whose faculty/research_group attribute is missing stay in
    n_ut_works but form no bucket. An explicit publication-year range
    replaces the data-window bounds (the works-derived numbers scope;
    None keeps the window, byte-identical)."""
    venue_issns = [issn_l] if issn_l is not None else sorted(set(issns or []))
    empty: dict[str, Any] = {
        "n_ut_works": 0,
        "faculties": [],
        "research_groups": [],
        "top_authors": [],
    }
    if not venue_issns:
        return empty
    population = [
        Work.institution_id == institution.id,
        Work.journal_issn_l.in_(venue_issns),
        Work.retired_at.is_(None),
        *work_year_window(institution, year_range),
        work_type_not_excluded(Work.work_type),
    ]
    pairs = (
        select(
            Work.pure_uuid.label("work_uuid"),
            Author.faculty.label("faculty"),
            Author.research_group.label("research_group"),
            Author.pure_uuid.label("author_uuid"),
            Author.name.label("name"),
        )
        .join(
            WorkPureAuthor,
            (WorkPureAuthor.institution_id == Work.institution_id)
            & (WorkPureAuthor.work_pure_uuid == Work.pure_uuid),
        )
        .join(
            Author,
            (Author.institution_id == WorkPureAuthor.institution_id)
            & (Author.pure_uuid == WorkPureAuthor.person_uuid),
        )
        .where(*population)
        .subquery()
    )
    n_ut_works = await session.scalar(select(func.count(func.distinct(pairs.c.work_uuid))))

    async def _buckets(column: Any) -> list[dict[str, Any]]:
        rows = (
            await session.execute(
                select(column, func.count(func.distinct(pairs.c.work_uuid)).label("works"))
                .select_from(pairs)
                .where(column.is_not(None), column != "")
                .group_by(column)
                .order_by(func.count(func.distinct(pairs.c.work_uuid)).desc(), column)
            )
        ).all()
        return [{"name": name, "works": int(n)} for name, n in rows]

    faculties = await _buckets(pairs.c.faculty)
    research_groups = await _buckets(pairs.c.research_group)
    author_rows = (
        await session.execute(
            select(
                pairs.c.author_uuid,
                pairs.c.name,
                pairs.c.faculty,
                pairs.c.research_group,
                func.count(func.distinct(pairs.c.work_uuid)).label("works"),
            )
            .select_from(pairs)
            .group_by(pairs.c.author_uuid, pairs.c.name, pairs.c.faculty, pairs.c.research_group)
            .order_by(func.count(func.distinct(pairs.c.work_uuid)).desc(), func.lower(pairs.c.name))
            .limit(TOP_AUTHORS)
        )
    ).all()
    return {
        "n_ut_works": int(n_ut_works or 0),
        "faculties": faculties,
        "research_groups": research_groups,
        "top_authors": [
            {
                "pure_uuid": r.author_uuid,
                "name": r.name,
                "faculty": r.faculty,
                "research_group": r.research_group,
                "works": int(r.works),
            }
            for r in author_rows
        ],
    }
