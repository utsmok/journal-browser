"""CSV exports for the CRIS-gap lists and author works.

Uncapped downloads mirroring the on-screen lists' gates: the journal and
publisher gap cards (venue-attributed OpenAlex store works whose DOI
matches no Pure work, author-sweep rows excluded) and the author page's
missed/canon works split. Store rows carry their payload-derived CSV
fields as openalex_works columns (0068), so the row query touches no
source_records payloads; the roster attribution plus journal/publisher
joins batch over the whole result before streaming.
"""

from collections.abc import AsyncIterator, Iterable
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import column, func, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import AUTHOR_SWEEP_PREFIX
from ..models import (
    Author,
    AuthorWork,
    Institution,
    JiscPublisher,
    Journal,
    OpenalexWork,
    Work,
)
from ..queries import work_type_not_excluded
from .authors import author_gap_works
from .authorship import (
    OPENALEX_URL,
    journal_publisher_map,
    not_in_pure,
    parts_predicate,
    store_gates,
    ut_authors_for_authorships,
    ut_roster_by_aids,
    work_authors_of,
)
from .csv_export import FLUSH_EVERY, csv_response, csv_safe, safe_filename
from .publishers import group_issns
from .work_sources import authorships_by_wid
from .works_query import author_works_join, work_year_window

#: CSV column order; every export uses exactly this header row.
CSV_COLUMNS = (
    "openalex_id",
    "openalex_url",
    "title",
    "publication_year",
    "publication_date",
    "doi",
    "doi_url",
    "pdf_url",
    "landing_page_url",
    "authors",
    "authors_openalex_ids",
    "authors_orcids",
    "institution_rors",
    "ut_authors",
    "ut_authors_orcids",
    "ut_affiliations",
    "journal_title",
    "issn_l",
    "publisher_name",
    "publisher_ror",
    "oa_status",
    "work_type",
    "language",
    "cited_by_count",
    "fwci",
    "is_retracted",
    "in_pure",
    # "rel:Parent Title" per parent work ("volume:Book Title"), "; "-joined
    # when multiple; empty for standalone rows and Pure-side works.
    "part_of",
)


def _t(value: Any) -> str:
    """Cell text: empty string when missing, str() otherwise, formula
    guard applied."""
    return "" if value is None else csv_safe(str(value))


def _part_of(parent_works: Any) -> str:
    """part_of cell: "rel:Parent Title" per parent work
    ("volume:Book Title"), "; "-joined when multiple; empty for
    standalone rows."""
    return "; ".join(
        f"{p['rel']}:{p['name']}"
        for p in parent_works or []
        if isinstance(p, dict) and p.get("rel") and p.get("name")
    )


def _ut_affiliations(ut: list[dict[str, Any]]) -> str:
    """Distinct "faculty / research_group / institute" strings over the
    attributed roster authors, first-seen order, ';'-joined."""
    out: list[str] = []
    for entry in ut:
        combo = " / ".join(
            part for part in (entry["faculty"], entry["research_group"], entry["institute"]) if part
        )
        if combo and combo not in out:
            out.append(combo)
    return ";".join(out)


def _export_stmt(institution: Institution, predicate: list[Any]) -> Any:
    """Store columns over one gap predicate, most recent first. The four
    payload-derived CSV fields ride as openalex_works columns (0068), so
    the export never reads source_records payloads per row."""
    return (
        select(
            OpenalexWork.w_id,
            OpenalexWork.title,
            OpenalexWork.year,
            OpenalexWork.doi_normalized,
            OpenalexWork.oa_status,
            OpenalexWork.work_type,
            OpenalexWork.venue_issn_l,
            OpenalexWork.venue_name,
            OpenalexWork.language,
            OpenalexWork.authorships,
            OpenalexWork.cited_by_count,
            OpenalexWork.fwci,
            OpenalexWork.is_retracted,
            OpenalexWork.parent_works,
            OpenalexWork.publication_date,
            OpenalexWork.pdf_url,
            OpenalexWork.landing_page_url,
            OpenalexWork.institution_rors,
        )
        .where(OpenalexWork.institution_id == institution.id, *predicate)
        .order_by(OpenalexWork.year.desc().nulls_last(), func.lower(OpenalexWork.title))
    )


async def _publisher_rors(session: AsyncSession, names: Iterable[str]) -> dict[str, str]:
    """Publisher display name -> ROR, matched case-insensitively on
    jisc_publishers (the canon publisher_detail reads; lowest id breaks
    ties between case variants)."""
    wanted = sorted({name.lower() for name in names if name})
    if not wanted:
        return {}
    rows = (
        await session.execute(
            select(JiscPublisher.name, JiscPublisher.ror)
            .where(JiscPublisher.ror.is_not(None), func.lower(JiscPublisher.name).in_(wanted))
            .order_by(JiscPublisher.id)
        )
    ).all()
    out: dict[str, str] = {}
    for r in rows:
        out.setdefault(r.name.lower(), r.ror)
    return out


def _store_csv_row(
    r: Any,
    roster: dict[str, dict[str, Any]],
    publishers: dict[str, str],
    rors: dict[str, str],
) -> list[str]:
    """One store (OpenAlex-only) row -> CSV cells in CSV_COLUMNS order."""
    authors = work_authors_of(r.authorships)
    ut = ut_authors_for_authorships(r.authorships, roster)
    doi = r.doi_normalized
    publisher = publishers.get(r.venue_issn_l)
    return [
        r.w_id,
        f"{OPENALEX_URL}/{r.w_id}",
        _t(r.title),
        _t(r.year),
        _t(r.publication_date),
        _t(doi),
        _t(f"https://doi.org/{doi}" if doi else None),
        _t(r.pdf_url),
        _t(r.landing_page_url),
        csv_safe(";".join(a["name"] for a in authors if a["name"])),
        csv_safe(";".join(a["openalex_id"] for a in authors)),
        csv_safe(";".join(a["orcid"] for a in authors if a["orcid"])),
        _t(r.institution_rors),
        csv_safe(";".join(a["name"] for a in ut)),
        csv_safe(";".join(a["orcid"] for a in ut if a["orcid"])),
        csv_safe(_ut_affiliations(ut)),
        _t(r.venue_name),
        _t(r.venue_issn_l),
        _t(publisher),
        _t(rors.get((publisher or "").lower())),
        _t(r.oa_status),
        _t(r.work_type),
        _t(r.language),
        _t(r.cited_by_count),
        _t(r.fwci),
        _t(r.is_retracted),
        "false",
        _part_of(r.parent_works),
    ]


def _canon_csv_row(
    row: Any, author: Author, publishers: dict[str, str], rors: dict[str, str]
) -> list[str]:
    """One Pure (canon) work -> CSV cells; OpenAlex-side columns stay
    empty except the DOI, and the page author is the sole UT author."""
    doi = row.doi_normalized
    publisher = publishers.get(row.journal_issn_l)
    ut = [
        {
            "name": author.name,
            "orcid": author.orcid,
            "faculty": author.faculty,
            "research_group": author.research_group,
            "institute": author.institute,
        }
    ]
    return [
        "",
        "",
        _t(row.title),
        _t(row.year),
        "",
        _t(doi),
        _t(f"https://doi.org/{doi}" if doi else None),
        "",
        "",
        "",
        "",
        "",
        "",
        csv_safe(author.name),
        _t(author.orcid),
        csv_safe(_ut_affiliations(ut)),
        _t(row.journal_title),
        _t(row.journal_issn_l),
        _t(publisher),
        _t(rors.get((publisher or "").lower())),
        _t(row.oa_status),
        _t(row.work_type),
        "",
        "",
        "",
        "",
        "true",
        "",
    ]


async def _store_keys(
    session: AsyncSession, institution: Institution, predicate: list[Any]
) -> tuple[list[str], set[str]]:
    """Enrichment keys over the export predicate: distinct venue ISSNs and
    lowercased author ids. Gathered in SQL so the row query itself can
    stream from a server-side cursor without a full in-memory fetch."""
    where = [OpenalexWork.institution_id == institution.id, *predicate]
    issns = (
        (await session.execute(select(OpenalexWork.venue_issn_l).distinct().where(*where)))
        .scalars()
        .all()
    )
    aid = (
        func.jsonb_array_elements(OpenalexWork.authorships)
        .table_valued(column("value", JSONB), name="aid")
        .lateral()
    )
    aid_rows = await session.execute(
        select(func.lower(aid.c.value.op("->>")("a")))
        .distinct()
        .join_from(OpenalexWork, aid, true())
        .where(*where)
    )
    return [i for i in issns if i], {r[0] for r in aid_rows if r[0]}


async def _store_csv_response(
    session: AsyncSession,
    institution: Institution,
    stmt: Any,
    predicate: list[Any],
    filename: str,
) -> StreamingResponse:
    """Batch enrichment (publisher names/RORs, roster) over SQL-gathered
    keys, then the streaming CSV off a server-side cursor (yield_per) —
    no per-row queries and no whole-result fetch."""
    issns, aids = await _store_keys(session, institution, predicate)
    publishers = await journal_publisher_map(session, issns)
    rors = await _publisher_rors(session, publishers.values())
    roster = await ut_roster_by_aids(session, institution, aids)
    result = await session.stream(stmt.execution_options(yield_per=FLUSH_EVERY))

    async def rows() -> AsyncIterator[list[str]]:
        async for partition in result.partitions(FLUSH_EVERY):
            for r in partition:
                yield _store_csv_row(r, roster, publishers, rors)

    return csv_response(filename, rows(), CSV_COLUMNS)


async def _empty_rows() -> AsyncIterator[list[str]]:
    """Header-only exports iterate nothing."""
    return
    yield  # pragma: no cover


async def journal_openalex_only_csv(
    session: AsyncSession,
    institution: Institution,
    issn_l: str,
    year_range: tuple[int, int] | None = None,
) -> StreamingResponse:
    """Uncapped CSV of the journal's CRIS-gap list (same gates as the
    on-screen card)."""
    issn = issn_l.upper()
    if (await session.scalar(select(Journal.issn_l).where(Journal.issn_l == issn))) is None:
        raise HTTPException(status_code=404, detail="journal not found")
    predicate = [
        OpenalexWork.venue_issn_l.in_([issn]),
        OpenalexWork.source != AUTHOR_SWEEP_PREFIX,
        *store_gates(institution, year_range),
        not_in_pure(),
    ]
    return await _store_csv_response(
        session,
        institution,
        _export_stmt(institution, predicate),
        predicate,
        f"{safe_filename(issn)}-openalex-only.csv",
    )


async def publisher_openalex_only_csv(
    session: AsyncSession,
    institution: Institution,
    name: str,
    year_range: tuple[int, int] | None = None,
    parts: list[str] | None = None,
) -> StreamingResponse:
    """Uncapped CSV of the publisher group's CRIS-gap list (same issn
    resolution and gates as the on-screen card). parts (pipe-joined
    standalone|chapter|part) filters the rows."""
    issns = await group_issns(session, institution.id, name)
    if not issns:
        raise HTTPException(status_code=404, detail="publisher not found")
    predicate = [
        OpenalexWork.venue_issn_l.in_(sorted(set(issns))),
        OpenalexWork.source != AUTHOR_SWEEP_PREFIX,
        *store_gates(institution, year_range),
        not_in_pure(),
    ]
    if (parts_sql := parts_predicate(parts)) is not None:
        predicate.append(parts_sql)
    return await _store_csv_response(
        session,
        institution,
        _export_stmt(institution, predicate),
        predicate,
        f"{safe_filename(name)}-openalex-only.csv",
    )


async def author_works_csv(
    session: AsyncSession,
    institution: Institution,
    pure_uuid: str,
    scope: str,
    year_range: tuple[int, int] | None = None,
) -> StreamingResponse:
    """The author's works as an uncapped CSV: scope=missed serves the
    openalex-only list (same gates as the profile section), scope=canon
    the Pure works."""
    if scope not in ("missed", "canon"):
        raise HTTPException(status_code=400, detail="scope must be 'missed' or 'canon'")
    author = await session.scalar(
        select(Author).where(Author.institution_id == institution.id, Author.pure_uuid == pure_uuid)
    )
    if author is None:
        raise HTTPException(status_code=404, detail="author not found")
    if scope == "canon":
        return await _canon_csv(session, institution, author, year_range)
    return await _missed_csv(session, institution, author, year_range)


async def _missed_csv(
    session: AsyncSession,
    institution: Institution,
    author: Author,
    year_range: tuple[int, int] | None = None,
) -> StreamingResponse:
    """The author's likely-missing works as an uncapped CSV: exactly the
    rows behind the profile's likely_missing count. authors.author_gap_works
    is the one gap definition (window + work-type gates + the Pure-record
    refinement), so card headline, sub-count and this download quote the
    same population; the old raw not_in_pure anti-join served a wider set
    that matched neither number."""
    filename = f"{safe_filename(author.pure_uuid)}-works-missed.csv"
    gap = await author_gap_works(session, institution, author, year_range)
    if gap is None or not gap[1]:
        return csv_response(filename, _empty_rows(), CSV_COLUMNS)
    missing = gap[1]
    # The profile fetch keeps authorships scalar; the authors/ut_authors
    # columns need them. One keyed query over the author-bounded set.
    ash = await authorships_by_wid(
        session, institution, sorted({r["openalex_id"] for r in missing if r["openalex_id"]})
    )
    rows = [
        SimpleNamespace(
            w_id=r["openalex_id"],
            doi_normalized=r["doi"],
            title=r["title"],
            year=r["year"],
            publication_date=r.get("publication_date"),
            pdf_url=r.get("pdf_url"),
            landing_page_url=r.get("landing_page_url"),
            authorships=ash.get(r["openalex_id"]) or [],
            institution_rors=r.get("institution_rors"),
            venue_name=r["journal_title"],
            venue_issn_l=r["journal_issn_l"],
            oa_status=r["oa_status"],
            work_type=r["work_type"],
            language=r.get("language"),
            cited_by_count=r.get("cited_by_count"),
            fwci=r.get("fwci"),
            is_retracted=r.get("is_retracted"),
            parent_works=r.get("parent_works"),
        )
        for r in missing
    ]
    publishers = await journal_publisher_map(
        session, sorted({r.venue_issn_l for r in rows if r.venue_issn_l})
    )
    rors = await _publisher_rors(session, publishers.values())
    roster = await ut_roster_by_aids(
        session,
        institution,
        {
            str(a.get("a") or "").lower()
            for r in rows
            for a in r.authorships
            if (a.get("a") or "").strip()
        },
    )

    async def rows_iter() -> AsyncIterator[list[str]]:
        for r in rows:
            yield _store_csv_row(r, roster, publishers, rors)

    return csv_response(filename, rows_iter(), CSV_COLUMNS)


async def _canon_csv(
    session: AsyncSession,
    institution: Institution,
    author: Author,
    year_range: tuple[int, int] | None = None,
) -> StreamingResponse:
    where = [
        Work.institution_id == institution.id,
        Work.retired_at.is_(None),
        *work_year_window(institution, year_range),
        work_type_not_excluded(Work.work_type),
    ]
    issns = (
        (await session.execute(select(Work.journal_issn_l).distinct().where(*where)))
        .scalars()
        .all()
    )
    publishers = await journal_publisher_map(session, issns)
    rors = await _publisher_rors(session, publishers.values())
    stmt = (
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
        .join(AuthorWork, author_works_join(institution.id, author.pure_uuid))
        .outerjoin(Journal, Journal.issn_l == Work.journal_issn_l)
        .where(*where)
        .order_by(Work.year.desc(), func.lower(Work.title))
        .execution_options(yield_per=FLUSH_EVERY)
    )
    result = await session.stream(stmt)

    async def rows() -> AsyncIterator[list[str]]:
        async for partition in result.partitions(FLUSH_EVERY):
            for r in partition:
                yield _canon_csv_row(r, author, publishers, rors)

    return csv_response(f"{safe_filename(author.pure_uuid)}-works-canon.csv", rows(), CSV_COLUMNS)
