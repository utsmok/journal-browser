"""Detail enrichment: raw OpenAlex source/works rows + OpenAIRE match counts.

All work rows live in source_records (source='openalex',
entity_type='works_stats'), keyed per journal via
payload->'primary_location'->'source'->>'issn_l'. Re-harvests can leave
multiple versions of one W-id; every query reads only the latest
harvested_at per source_pk.
"""

from typing import Any

from sqlalchemy import Float, Integer, case, cast, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import HarvestRun, SourceRecord, Work, WorkIdentity
from . import ut_metadata

OPENALEX_URL = "https://openalex.org"


def _journal_works(issn_l: str, institution_id: int):
    """Subquery: latest version of each of the institution's OpenAlex work
    rows for the journal (works_stats runs are institution-scoped; an
    OpenAlex work id can appear in several institutions' harvests)."""
    return (
        select(SourceRecord.payload)
        .ext(distinct_on(SourceRecord.source_pk))
        .where(
            SourceRecord.source == "openalex",
            SourceRecord.entity_type == "works_stats",
            SourceRecord.harvest_run_id.in_(
                select(HarvestRun.id).where(HarvestRun.institution_id == institution_id)
            ),
            # Explicit -> operators (not payload[...][...] subscripts): the
            # subscript form plans as a seq scan and cannot use
            # ix_source_records_works_issn_l.
            SourceRecord.payload.op("->")("primary_location").op("->")("source").op("->>")("issn_l")
            == issn_l,
        )
        .order_by(SourceRecord.source_pk, SourceRecord.harvested_at.desc())
        .subquery()
    )


def _work_item(payload: dict[str, Any]) -> dict[str, Any]:
    # Explicit key list: authorships must never reach the API. Payload ids
    # can be bare W-ids or full URLs; normalize to the bare id.
    work_id = payload.get("id")
    if isinstance(work_id, str) and "/" in work_id:
        work_id = work_id.rsplit("/", 1)[-1]
    return {
        "id": work_id,
        "url": f"{OPENALEX_URL}/{work_id}" if work_id else None,
        "doi": payload.get("doi"),
        "title": payload.get("display_name"),
        "year": payload.get("publication_year"),
        "oa_status": (payload.get("open_access") or {}).get("oa_status"),
        "fwci": payload.get("fwci"),
        "cited_by_count": payload.get("cited_by_count") or 0,
        "is_retracted": payload.get("is_retracted"),
        "type": payload.get("type"),
    }


async def list_works(
    session: AsyncSession,
    issn_l: str,
    institution_id: int,
    page: int,
    page_size: int,
    ut_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Paginated works: ut-metadata union when available, works_stats only
    otherwise. publication_year desc nulls last, cited_by_count desc, title
    asc; slicing happens in Python (bounded per journal)."""
    rows = _journal_works(issn_l, institution_id)
    payloads = (await session.execute(select(rows.c.payload))).scalars().all()
    items = [_work_item(p) for p in payloads]
    for item in items:
        item["work_type"] = None
        item["in_openalex"] = True
    if ut_rows is not None:
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
    institution_id: int,
    ut_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregates over the journal's stored OpenAlex works (SQL, one pass),
    plus canonical-store totals when the external works store is reachable."""
    rows = _journal_works(issn_l, institution_id)
    fwci = cast(rows.c.payload["fwci"].astext, Float)
    total, fwci_avg, fwci_n, retracted, cited_total = (
        await session.execute(
            select(
                func.count(),
                func.avg(fwci),
                func.count(fwci),
                func.count(case((rows.c.payload["is_retracted"].astext == "true", 1))),
                func.coalesce(func.sum(cast(rows.c.payload["cited_by_count"].astext, Integer)), 0),
            ).select_from(rows)
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
