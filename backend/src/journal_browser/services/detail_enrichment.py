"""Detail enrichment: raw OpenAlex source/works rows + OpenAIRE match counts.

The journal works list and institution metrics read the openalex_works
store — plain indexed columns. They used to re-read the underlying
works_stats payloads (~8 KB JSONB per work) on every request, which
detoasting turned into seconds per journal page; the store projection
carries every served field already. The venue source card keeps reading
its sources payload (one small row).
"""

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Institution, OpenalexWork, SourceRecord, Work, WorkIdentity
from . import ut_metadata

OPENALEX_URL = "https://openalex.org"


def _store_work_item(row: OpenalexWork) -> dict[str, Any]:
    """Tab item from store columns; doi keeps the payload path's URL form."""
    return {
        "id": row.w_id,
        "url": f"{OPENALEX_URL}/{row.w_id}" if row.w_id else None,
        "doi": f"https://doi.org/{row.doi_normalized}" if row.doi_normalized else None,
        "title": row.title,
        "year": row.year,
        "oa_status": row.oa_status,
        "fwci": row.fwci,
        "cited_by_count": row.cited_by_count or 0,
        "is_retracted": row.is_retracted,
        "type": row.work_type,
    }


def _venue_works(issn_l: str, institution_id: int, year_start: int, year_end: int):
    """The institution's store rows for the journal, inside the
    publication-year window (NULL years drop out via the BETWEEN)."""
    return (
        select(OpenalexWork)
        .where(
            OpenalexWork.institution_id == institution_id,
            OpenalexWork.venue_issn_l == issn_l,
            OpenalexWork.year.between(year_start, year_end),
        )
        .order_by(OpenalexWork.w_id)
    )


async def list_works(
    session: AsyncSession,
    issn_l: str,
    institution: Institution,
    page: int,
    page_size: int,
    ut_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Paginated works: ut-metadata union when available, works_stats only
    otherwise. publication_year desc nulls last, cited_by_count desc, title
    asc; slicing happens in Python (bounded per journal). Both sides are
    bounded to the institution's publication-year window."""
    year_start = institution.data_window_start
    year_end = institution.data_window_end if institution.data_window_end is not None else 9999
    rows = await session.execute(_venue_works(issn_l, institution.id, year_start, year_end))
    items = [_store_work_item(r) for r in rows.scalars()]
    for item in items:
        item["work_type"] = None
        item["in_openalex"] = True
    if ut_rows is not None:
        # Canonical rows carry their own year: same window applies.
        ut_rows = [
            r for r in ut_rows if r["year"] is not None and year_start <= r["year"] <= year_end
        ]
        # The tab serves UT-affiliated-author works only (owner decision
        # 2026-11-05). Stats-side items carry their payload DOI form, so
        # the set matches both bare and https://doi.org/ forms, caseless —
        # anything without a filtered canonical DOI behind it drops.
        ut_dois = set()
        for row in ut_rows:
            if row["doi"]:
                doi = row["doi"].lower()
                ut_dois.add(doi)
                ut_dois.add(f"https://doi.org/{doi}")
        items = [i for i in items if (i.get("doi") or "").lower() in ut_dois]
        items = ut_metadata.merge_work_lists(ut_rows, items)
    return {
        "items": ut_metadata.sort_work_items(items)[(page - 1) * page_size : page * page_size],
        "total": len(items),
        "page": page,
        "page_size": page_size,
    }


async def institution_metrics(
    session: AsyncSession,
    issn_l: str,
    institution: Institution,
    ut_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregates over the journal's stored OpenAlex works (SQL, one pass),
    plus canonical-store totals when the external works store is reachable.
    Both sides bounded to the institution's publication-year window."""
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
    if ut_rows is not None:
        # Canonical rows carry their own year: same window applies.
        ut_rows = [
            r for r in ut_rows if r["year"] is not None and year_start <= r["year"] <= year_end
        ]
        metrics["canonical_total"] = len(ut_rows)
        metrics["canonical_retracted"] = sum(1 for r in ut_rows if r["is_retracted"])
        metrics["canonical_oa"] = ut_metadata.oa_buckets(ut_rows)
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
