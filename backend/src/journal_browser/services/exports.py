"""CSV exports for the CRIS-gap lists and author works.

Uncapped downloads mirroring the on-screen lists' gates: the journal and
publisher gap cards (venue-attributed OpenAlex store works whose DOI
matches no Pure work, author-sweep rows excluded) and the author page's
missed/canon works split. Store rows enrich once through a lateral pick
of the latest works_stats source_record per W-id — publication date, OA
urls and institution RORs ride along without per-row queries — and the
roster attribution plus journal/publisher joins batch over the whole
result before streaming.
"""

import csv
import io
import re
from collections.abc import AsyncIterator, Iterable
from typing import Any

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..harvest.openalex_works import AUTHOR_SWEEP_PREFIX
from ..models import (
    Author,
    AuthorWork,
    Institution,
    JiscPublisher,
    Journal,
    OpenalexWork,
    SourceRecord,
    Work,
)
from .authorship import (
    OPENALEX_URL,
    attributed_to_any,
    journal_publisher_map,
    not_in_pure,
    store_gates,
    ut_authors_for_authorships,
    ut_roster_by_aids,
    work_authors_of,
)
from .publishers import group_issns
from .works_query import author_works_join, work_window

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
)

#: Rows buffered per streaming chunk.
FLUSH_EVERY = 500


def _t(value: Any) -> str:
    """Cell text: empty string when missing, str() otherwise."""
    return "" if value is None else str(value)


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "export"


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


def _raw_fields(payload: dict[str, Any] | None) -> dict[str, Any]:
    """publication_date, OA urls and distinct institution RORs from the
    raw works_stats payload; empty without a stored raw row."""
    if not isinstance(payload, dict):
        return {}
    best = payload.get("best_oa_location") or {}
    primary = payload.get("primary_location") or {}
    rors = sorted(
        {
            ror
            for entry in payload.get("authorships") or []
            for inst in entry.get("institutions") or []
            if (ror := inst.get("ror"))
        }
    )
    return {
        "publication_date": payload.get("publication_date"),
        "pdf_url": best.get("pdf_url") or primary.get("pdf_url"),
        "landing_page_url": primary.get("landing_page_url") or best.get("landing_page_url"),
        "institution_rors": ";".join(rors),
    }


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


def _raw_payload_lateral() -> Any:
    """Latest works_stats source_record per W-id, picked inside the one
    export query (lateral ORDER BY harvested_at DESC LIMIT 1; the lookup
    index ix_source_records_lookup makes each probe a single index scan)."""
    return (
        select(SourceRecord.payload.label("payload"))
        .where(
            SourceRecord.source == "openalex",
            SourceRecord.entity_type == "works_stats",
            SourceRecord.source_pk == OpenalexWork.w_id,
        )
        .order_by(SourceRecord.harvested_at.desc(), SourceRecord.id.desc())
        .limit(1)
        .lateral("raw_payload")
    )


def _export_stmt(institution: Institution, predicate: list[Any]) -> Any:
    """Store columns + the lateral raw payload over one gap predicate,
    most recent first."""
    raw = _raw_payload_lateral()
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
            raw.c.payload,
        )
        .outerjoin(raw, literal(True))
        .where(OpenalexWork.institution_id == institution.id, *predicate)
        .order_by(OpenalexWork.year.desc().nulls_last(), func.lower(OpenalexWork.title))
    )


def _store_csv_row(
    r: Any,
    raw: dict[str, Any],
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
        _t(raw.get("publication_date")),
        _t(doi),
        _t(f"https://doi.org/{doi}" if doi else None),
        _t(raw.get("pdf_url")),
        _t(raw.get("landing_page_url")),
        ";".join(a["name"] for a in authors if a["name"]),
        ";".join(a["openalex_id"] for a in authors),
        ";".join(a["orcid"] for a in authors if a["orcid"]),
        _t(raw.get("institution_rors")),
        ";".join(a["name"] for a in ut),
        ";".join(a["orcid"] for a in ut if a["orcid"]),
        _ut_affiliations(ut),
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
        author.name,
        _t(author.orcid),
        _ut_affiliations(ut),
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
    ]


async def _store_csv_response(
    session: AsyncSession, institution: Institution, rows: list[Any], filename: str
) -> StreamingResponse:
    """Batch enrichment (publisher names/RORs, roster) over the fetched
    result, then the streaming CSV — no per-row queries."""
    publishers = await journal_publisher_map(session, [r.venue_issn_l for r in rows])
    rors = await _publisher_rors(session, publishers.values())
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
    out_rows = [_store_csv_row(r, _raw_fields(r.payload), roster, publishers, rors) for r in rows]
    return _csv_response(filename, out_rows)


def _csv_response(filename: str, rows: Iterable[list[str]]) -> StreamingResponse:
    """CSV attachment; the csv module owns the quoting."""

    async def _stream() -> AsyncIterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        yield buf.getvalue()
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        written = 0
        for row in rows:
            writer.writerow(row)
            written += 1
            if written % FLUSH_EVERY == 0:
                yield buf.getvalue()
                buf = io.StringIO()
                writer = csv.writer(buf, lineterminator="\n")
        if written % FLUSH_EVERY:
            yield buf.getvalue()

    return StreamingResponse(
        _stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def journal_openalex_only_csv(
    session: AsyncSession, institution: Institution, issn_l: str
) -> StreamingResponse:
    """Uncapped CSV of the journal's CRIS-gap list (same gates as the
    on-screen card)."""
    issn = issn_l.upper()
    if (await session.scalar(select(Journal.issn_l).where(Journal.issn_l == issn))) is None:
        raise HTTPException(status_code=404, detail="journal not found")
    predicate = [
        OpenalexWork.venue_issn_l.in_([issn]),
        OpenalexWork.source != AUTHOR_SWEEP_PREFIX,
        *store_gates(institution),
        not_in_pure(),
    ]
    rows = (await session.execute(_export_stmt(institution, predicate))).all()
    return await _store_csv_response(
        session, institution, rows, f"{_safe_filename(issn)}-openalex-only.csv"
    )


async def publisher_openalex_only_csv(
    session: AsyncSession, institution: Institution, name: str
) -> StreamingResponse:
    """Uncapped CSV of the publisher group's CRIS-gap list (same issn
    resolution and gates as the on-screen card)."""
    issns = await group_issns(session, institution.id, name)
    if not issns:
        raise HTTPException(status_code=404, detail="publisher not found")
    predicate = [
        OpenalexWork.venue_issn_l.in_(sorted(set(issns))),
        OpenalexWork.source != AUTHOR_SWEEP_PREFIX,
        *store_gates(institution),
        not_in_pure(),
    ]
    rows = (await session.execute(_export_stmt(institution, predicate))).all()
    return await _store_csv_response(
        session, institution, rows, f"{_safe_filename(name)}-openalex-only.csv"
    )


async def author_works_csv(
    session: AsyncSession, institution: Institution, pure_uuid: str, scope: str
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
        return await _canon_csv(session, institution, author)
    return await _missed_csv(session, institution, author)


async def _missed_csv(
    session: AsyncSession, institution: Institution, author: Author
) -> StreamingResponse:
    aids = sorted({a.lower() for a in (author.openalex_ids or []) if a})
    rows: list[Any] = []
    if aids:
        predicate = [attributed_to_any(aids), *store_gates(institution), not_in_pure()]
        rows = (await session.execute(_export_stmt(institution, predicate))).all()
    return await _store_csv_response(
        session, institution, rows, f"{_safe_filename(author.pure_uuid)}-works-missed.csv"
    )


async def _canon_csv(
    session: AsyncSession, institution: Institution, author: Author
) -> StreamingResponse:
    rows = (
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
            .join(AuthorWork, author_works_join(institution.id, author.pure_uuid))
            .outerjoin(Journal, Journal.issn_l == Work.journal_issn_l)
            .where(
                Work.institution_id == institution.id,
                Work.retired_at.is_(None),
                *work_window(institution),
            )
            .order_by(Work.year.desc(), func.lower(Work.title))
        )
    ).all()
    publishers = await journal_publisher_map(session, [r.journal_issn_l for r in rows])
    rors = await _publisher_rors(session, publishers.values())
    out_rows = [_canon_csv_row(r, author, publishers, rors) for r in rows]
    return _csv_response(f"{_safe_filename(author.pure_uuid)}-works-canon.csv", out_rows)
