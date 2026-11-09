"""Detail enrichment: raw OpenAlex source/works rows + OpenAIRE match counts.

The journal works list, institution metrics, and the venue source card
read plain indexed columns / one small payload row. The works list serves
the same population the stats count — the works table (Pure canonical,
windowed, journal output types only) — so the search card, the detail
totals, and the publications tab always describe one number; the
openalex_works store joins in per DOI only as enrichment (citations,
FWCI, retraction, most-open OA record), never as the population.
"""

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import normalize_work_type
from ..harvest.common import oa_openness_desc
from ..models import (
    Author,
    Institution,
    OpenalexWork,
    SourceRecord,
    Work,
    WorkIdentity,
    WorkPureAuthor,
)
from . import ut_metadata
from .works_query import work_type_not_excluded, work_year_window

OPENALEX_URL = "https://openalex.org"

#: One works-table row plus the store enrichment columns for its DOI.
_WORK_COLUMNS = (
    Work.pure_uuid,
    Work.doi_normalized,
    Work.title,
    Work.year,
    Work.work_type,
    Work.oa_status,
)


async def _venue_work_rows(
    session: AsyncSession,
    issn_l: str,
    institution: Institution,
    year_range: tuple[int, int] | None = None,
) -> list[Any]:
    """The stats population: this institution's Pure canonical works for
    the journal inside the publication-year window (or the explicit clamped
    range the search card filters by), retired dropped,
    never-journal-output types excluded — the exact write_pure_canon_stats
    row set (and therefore journal_flags.works_count, the search card)."""
    return list(
        (
            await session.execute(
                select(*_WORK_COLUMNS)
                .where(
                    Work.institution_id == institution.id,
                    Work.journal_issn_l == issn_l,
                    Work.retired_at.is_(None),
                    *work_year_window(institution, year_range),
                    work_type_not_excluded(Work.work_type),
                )
                .order_by(Work.pure_uuid)
            )
        ).all()
    )


async def _store_by_doi(
    session: AsyncSession, institution_id: int, dois: list[str]
) -> dict[str, OpenalexWork]:
    """Most-open store row per DOI (ties keep the lowest W-id) — the
    merged-profile dedupe works_for_journal used to apply, applied to the
    enrichment join so one Pure work still yields one list item."""
    if not dois:
        return {}
    rows = (
        await session.execute(
            select(OpenalexWork)
            .where(
                OpenalexWork.institution_id == institution_id,
                OpenalexWork.doi_normalized.in_(dois),
            )
            .order_by(oa_openness_desc(OpenalexWork.oa_status), OpenalexWork.w_id)
        )
    ).scalars()
    out: dict[str, OpenalexWork] = {}
    for row in rows:
        if row.doi_normalized is not None:
            out.setdefault(row.doi_normalized, row)
    return out


def _work_item(row: Any, store: OpenalexWork | None) -> dict[str, Any]:
    """Tab item from a works-table row; store columns enrich when the DOI
    matched (id/url/type/oa_status stay OpenAlex's, as before). doi keeps
    the payload path's URL form."""
    doi = row.doi_normalized
    return {
        "id": store.w_id if store else None,
        "url": f"{OPENALEX_URL}/{store.w_id}" if store and store.w_id else None,
        "doi": f"https://doi.org/{doi}" if doi else None,
        "title": row.title,
        "year": row.year,
        "oa_status": (store.oa_status if store and store.oa_status else None) or row.oa_status,
        "fwci": store.fwci if store else None,
        "cited_by_count": (store.cited_by_count if store else 0) or 0,
        "is_retracted": store.is_retracted if store else None,
        "type": store.work_type if store else None,
        "work_type": normalize_work_type(row.work_type) or None,
        "in_openalex": store is not None,
    }


async def _page_authors(
    session: AsyncSession, institution_id: int, pure_uuids: list[str]
) -> dict[str, dict[str, list[dict[str, str]]]]:
    """Pure authors (roster order) per work for one page of works, with
    each author's research group where the roster knows one."""
    if not pure_uuids:
        return {}
    rows = (
        await session.execute(
            select(
                WorkPureAuthor.work_pure_uuid,
                Author.pure_uuid,
                Author.name,
                Author.research_group,
            )
            .join(
                Author,
                (Author.institution_id == WorkPureAuthor.institution_id)
                & (Author.pure_uuid == WorkPureAuthor.person_uuid),
            )
            .where(
                WorkPureAuthor.institution_id == institution_id,
                WorkPureAuthor.work_pure_uuid.in_(pure_uuids),
            )
            .order_by(WorkPureAuthor.work_pure_uuid, WorkPureAuthor.position, Author.name)
        )
    ).all()
    out: dict[str, dict[str, list[dict[str, str]]]] = {}
    for work_uuid, author_uuid, name, group in rows:
        entry = out.setdefault(work_uuid, {"ut_authors": [], "ut_groups": []})
        if author_uuid not in {a["id"] for a in entry["ut_authors"]}:
            entry["ut_authors"].append({"id": author_uuid, "name": name})
        if group and group not in {g["name"] for g in entry["ut_groups"]}:
            entry["ut_groups"].append({"name": group})
    return out


async def list_works(
    session: AsyncSession,
    issn_l: str,
    institution: Institution,
    page: int,
    page_size: int,
    year_range: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Paginated works over the stats population (see _venue_work_rows),
    store-enriched per DOI. Sorting stays in Python (bounded per journal):
    publication_year desc nulls last, cited_by_count desc, title asc.
    Page rows carry their Pure authors and research groups; pure_uuid
    rides along for the author lookup and WorkItem drops it on render."""
    rows = await _venue_work_rows(session, issn_l, institution, year_range)
    store_by_doi = await _store_by_doi(
        session, institution.id, sorted({r.doi_normalized for r in rows if r.doi_normalized})
    )
    items = []
    for row in rows:
        item = _work_item(row, store_by_doi.get(row.doi_normalized))
        item["pure_uuid"] = row.pure_uuid
        items.append(item)
    items = ut_metadata.sort_work_items(items)
    page_items = items[(page - 1) * page_size : page * page_size]
    authors = await _page_authors(session, institution.id, [i["pure_uuid"] for i in page_items])
    for item in page_items:
        entry = authors.get(item["pure_uuid"]) or {"ut_authors": [], "ut_groups": []}
        item["ut_authors"] = entry["ut_authors"]
        item["ut_groups"] = entry["ut_groups"]
    return {
        "items": page_items,
        "total": len(items),
        "page": page,
        "page_size": page_size,
    }


async def institution_metrics(
    session: AsyncSession,
    issn_l: str,
    institution: Institution,
) -> dict[str, Any]:
    """Aggregates over the journal's works (both sides bounded to the
    institution's publication-year window): the OpenAlex-side metrics come
    from the venue store rows (SQL, one pass); the canonical side describes
    the same stats population the works list and the search card serve —
    works-table rows, store-enriched per DOI for retraction/OA status."""
    year_start = institution.data_window_start
    year_end = institution.data_window_end if institution.data_window_end is not None else 9999
    total, fwci_avg, fwci_n, retracted, cited_total = (
        await session.execute(
            select(
                func.count(),
                func.avg(OpenalexWork.fwci),
                func.count(OpenalexWork.fwci),
                func.count(case((OpenalexWork.is_retracted.is_(True), 1))),
                func.coalesce(func.sum(OpenalexWork.cited_by_count), 0),
            ).where(
                OpenalexWork.institution_id == institution.id,
                OpenalexWork.venue_issn_l == issn_l,
                OpenalexWork.year.between(year_start, year_end),
            )
        )
    ).one()
    metrics: dict[str, Any] = {
        "openalex_matched": total,
        "fwci_avg": float(fwci_avg) if fwci_avg is not None else None,
        "fwci_n": fwci_n,
        "retracted": retracted,
        "cited_total": cited_total,
        "canonical_total": None,
        "canonical_retracted": None,
        "canonical_oa": None,
    }
    base = await _venue_work_rows(session, issn_l, institution)
    store_by_doi = await _store_by_doi(
        session, institution.id, sorted({r.doi_normalized for r in base if r.doi_normalized})
    )
    metrics["canonical_total"] = len(base)
    metrics["canonical_retracted"] = sum(
        1 for r in base if (s := store_by_doi.get(r.doi_normalized)) is not None and s.is_retracted
    )
    metrics["canonical_oa"] = ut_metadata.oa_buckets(
        [
            {
                "oa_status": (s.oa_status if (s := store_by_doi.get(r.doi_normalized)) else None)
                or r.oa_status
            }
            for r in base
        ]
    )
    return metrics


async def openalex_info(session: AsyncSession, issn_l: str) -> dict[str, Any] | None:
    """Raw venue source object; None when no source row maps to the ISSN-L."""
    payload = await session.scalar(
        select(SourceRecord.payload)
        .where(
            SourceRecord.source == "openalex",
            SourceRecord.entity_type == "sources",
            SourceRecord.payload["issn_l"].astext == issn_l,
        )
        .order_by(SourceRecord.harvested_at.desc())
        .limit(1)
    )
    if payload is None:
        return None
    years = [entry["year"] for entry in payload.get("counts_by_year") or [] if entry.get("year")]
    topics = sorted(
        payload.get("topics") or [],
        key=lambda t: (t.get("count") is None, -(t.get("count") or 0)),
    )
    source_id = payload.get("id")
    return {
        "id": source_id,
        "url": f"{OPENALEX_URL}/{source_id}" if source_id else None,
        "cited_by_count": payload.get("cited_by_count"),
        "works_count": payload.get("works_count"),
        "host_organization_name": payload.get("host_organization_name"),
        "first_publication_year": min(years) if years else None,
        "last_publication_year": max(years) if years else None,
        "topics": topics,
    }


async def openaire_matched(session: AsyncSession, issn_l: str, institution_id: int) -> int:
    """Distinct works of the institution matched in OpenAIRE for the journal."""
    return (
        await session.scalar(
            select(func.count(func.distinct(WorkIdentity.work_id)))
            .join(
                Work,
                (Work.institution_id == WorkIdentity.institution_id)
                & (Work.pure_uuid == WorkIdentity.work_id),
            )
            .where(
                WorkIdentity.institution_id == institution_id,
                WorkIdentity.source == "openaire",
                Work.journal_issn_l == issn_l,
            )
        )
    ) or 0
