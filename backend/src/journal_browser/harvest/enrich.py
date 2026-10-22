"""Enrich canonical UT works and resolve them to journals (phase 9).

Ladder per docs/plan-pure-openaire-crossref.md, per work:

1. OpenAlex (aletheca, batch_get_by_doi 50/call): confirms the DOI identity,
   fills oa_status, and supplies the journal via the work's primary source.
2. Crossref (stavrophora, env-paced, polite pool): gap fill for DOIs OpenAlex
   does not know; supplies the journal ISSN list.
3. Pure CERIF issn (already on the row from the OAI harvest).

ISSN -> journal resolution always goes through issn_map (any ISSN variant to
ISSN-L) and then journals.issn_l.
"""

import asyncio
import logging
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..harvest.common import normalize_issn, resolve_issn_l
from ..ingest import IngestSession
from ..models import Journal, UtWork, WorkIdentity

logger = logging.getLogger(__name__)

BATCH_SIZE = 50  # OpenAlex max identifiers per pipe-separated filter
# OpenAlex rate-limits bursty batch runs; failures then get wrongly recorded
# as "missing" identities, so keep a polite gap between chunks.
CHUNK_PAUSE_S = 0.3


def _chunk(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def _resolve_journal(session: AsyncSession, issns: list[Any]) -> str | None:
    """Any ISSN variant -> issn_map -> journals.issn_l; first hit wins."""
    for raw in issns:
        issn = normalize_issn(str(raw))
        if not issn:
            continue
        issn_l = await resolve_issn_l(session, issn)
        if issn_l and await session.scalar(
            select(Journal.issn_l).where(Journal.issn_l == issn_l)
        ):
            return issn_l
    return None


async def _confirm_identity(
    session: AsyncSession,
    *,
    source: str,
    source_pk: str,
    ut_work_id: str,
    matched_by: str = "doi",
    confidence: float = 1.0,
) -> None:
    """Insert one confirmed work identity (idempotent)."""
    stmt = (
        pg_insert(WorkIdentity)
        .values(
            source=source,
            source_pk=source_pk,
            ut_work_id=ut_work_id,
            matched_by=matched_by,
            confidence=confidence,
            status="confirmed",
        )
        .on_conflict_do_nothing(constraint="uq_work_identity_source")
    )
    await session.execute(stmt)


def _openalex_work_fields(work: Any) -> dict[str, Any]:
    """Extract the fields we keep from one aletheca Work model."""
    fields: dict[str, Any] = {}
    oa = getattr(work, "open_access", None)
    oa_status = getattr(oa, "oa_status", None)
    if oa_status:
        fields["oa_status"] = oa_status
    location = getattr(work, "primary_location", None)
    source = (
        location.get("source")
        if isinstance(location, dict)
        else getattr(location, "source", None)
    )
    issn_l = source.get("issn_l") if isinstance(source, dict) else getattr(source, "issn_l", None)
    if issn_l:
        fields["journal_issn_l"] = issn_l
    return fields


async def _works_needing_journal(
    session: AsyncSession, limit: int | None
) -> list[UtWork]:
    """DOI works still lacking a journal, excluding recorded OpenAlex misses.

    Re-fetches matched works whose journal stayed unresolved; runs are rare
    and the batch is bounded, so the redundant lookups are accepted.
    """
    recorded_miss = exists(
        select(WorkIdentity.id)
        .where(
            WorkIdentity.ut_work_id == UtWork.pure_uuid,
            WorkIdentity.source == "openalex",
            WorkIdentity.source_pk.like("doi:%"),
        )
        .correlate(UtWork)
    )
    query = (
        select(UtWork)
        .where(
            UtWork.doi_normalized.is_not(None),
            UtWork.journal_issn_l.is_(None),
            ~recorded_miss,
        )
        .limit(limit)
    )
    return list((await session.execute(query)).scalars().all())


def _location_issns(work: Any) -> list[str]:
    """ISSNs from any location's source (primary first, deduped in order)."""
    out: list[str] = []
    primary = getattr(work, "primary_location", None)
    for loc in [primary, *(getattr(work, "locations", None) or [])]:
        src = getattr(loc, "source", None) if loc is not None else None
        if src is None:
            continue
        # aletheca parses Location.source as a raw dict (DehydratedSource).
        getter = src.get if isinstance(src, dict) else lambda k, _s=src: getattr(_s, k, None)
        candidates = [getter("issn_l"), *(getter("issn") or [])]
        for value in candidates:
            if value and str(value) not in out:
                out.append(str(value))
    return out


async def enrich_openalex(session: AsyncSession, limit: int | None = None) -> dict[str, int]:
    """Batch DOI lookup; confirm identities + resolve journals from OpenAlex."""
    from aletheca import AlethecaClient

    works = await _works_needing_journal(session, limit)
    stats = {"works": len(works), "matched": 0, "journal_resolved": 0}
    if not works:
        return stats

    client_kwargs: dict[str, Any] = {}
    if get_api_key := getattr(_settings(), "openalex_api_key", ""):
        client_kwargs["api_key"] = get_api_key
    by_doi = {w.doi_normalized: w for w in works}
    ingest = IngestSession(session)
    await ingest.start_run(
        "openalex", "work", "enrichment", {"via": "batch_get_by_doi", "batch": BATCH_SIZE}
    )
    async with AlethecaClient(**client_kwargs) as client:
        for chunk in _chunk(list(by_doi), BATCH_SIZE):
            await asyncio.sleep(CHUNK_PAUSE_S)
            found = await client.works.batch_get_by_doi(chunk)
            found_dois = set()
            for key, work in found.items():
                doi = str(key).lower().removeprefix("https://doi.org/")
                found_dois.add(doi)
                ut = by_doi.get(doi)
                if ut is None:
                    continue
                fields = _openalex_work_fields(work)
                for name, value in fields.items():
                    setattr(ut, name, value)
                await ingest.ingest_record(
                    str(getattr(work, "id", "") or f"doi:{doi}"),
                    work.model_dump(mode="json"),
                )
                await _confirm_identity(
                    session,
                    source="openalex",
                    source_pk=str(getattr(work, "id", "") or ""),
                    ut_work_id=ut.pure_uuid,
                )
                stats["matched"] += 1
                if fields.get("journal_issn_l"):
                    stats["journal_resolved"] += 1
                elif issn_l := await _resolve_journal(session, _location_issns(work)):
                    # Primary location had no journal; any location's source
                    # (e.g. the journal's own landing page) still counts.
                    ut.journal_issn_l = issn_l
                    stats["journal_resolved"] += 1
            # Mark misses so the Crossref pass only sees true gaps.
            for doi in by_doi:
                if doi in chunk and doi not in found_dois:
                    stmt = (
                        pg_insert(WorkIdentity)
                        .values(
                            source="openalex",
                            source_pk=f"doi:{doi}",
                            ut_work_id=by_doi[doi].pure_uuid,
                            matched_by="doi",
                            confidence=0.0,
                            status="missing",
                        )
                        .on_conflict_do_nothing(constraint="uq_work_identity_source")
                    )
                    await session.execute(stmt)
            await ingest.finish_run("completed", dict(stats))
            await ingest.commit()
    return stats


def _settings() -> Any:
    from ..config import get_settings

    return get_settings()


async def _works_for_crossref(
    session: AsyncSession, limit: int | None
) -> list[UtWork]:
    """Works with a DOI, no crossref identity, and no successful OpenAlex match.

    OpenAlex 'missing' rows carry source_pk='doi:<doi>' and are NOT counted
    as matches, so true OpenAlex gaps still reach Crossref.
    """
    no_openalex = ~exists(
        select(WorkIdentity.id)
        .where(
            WorkIdentity.ut_work_id == UtWork.pure_uuid,
            WorkIdentity.source == "openalex",
            WorkIdentity.source_pk.not_like("doi:%"),
        )
        .correlate(UtWork)
    )
    query = (
        select(UtWork)
        .where(
            UtWork.doi_normalized.is_not(None),
            no_openalex,
            ~exists(
                select(WorkIdentity.id)
                .where(
                    WorkIdentity.ut_work_id == UtWork.pure_uuid,
                    WorkIdentity.source == "crossref",
                )
                .correlate(UtWork)
            ),
        )
        .limit(limit)
    )
    return list((await session.execute(query)).scalars().all())


async def enrich_crossref(session: AsyncSession, limit: int | None = None) -> dict[str, int]:
    """Gap fill: DOIs OpenAlex missed -> stavrophora; journal via ISSN list."""
    from stavrophora import StavrophoraClient

    works = await _works_for_crossref(session, limit)
    stats = {"works": len(works), "matched": 0, "journal_resolved": 0}
    if not works:
        return stats

    by_doi = {w.doi_normalized: w for w in works}
    ingest = IngestSession(session)
    await ingest.start_run("crossref", "work", "enrichment", {"via": "batch_get_by_doi"})
    async with StavrophoraClient(mailto=_settings().contact_email) as client:
        for chunk in _chunk(list(by_doi), BATCH_SIZE):
            found = await client.works.batch_get_by_doi(chunk)
            for doi, work in found.items():
                ut = by_doi.get(str(doi).lower())
                if ut is None:
                    continue
                payload = (
                    work.model_dump(mode="json")
                    if hasattr(work, "model_dump")
                    else dict(work)
                )
                await ingest.ingest_record(f"doi:{ut.doi_normalized}", payload)
                await _confirm_identity(
                    session,
                    source="crossref",
                    source_pk=f"doi:{ut.doi_normalized}",
                    ut_work_id=ut.pure_uuid,
                )
                stats["matched"] += 1
                issns = list(getattr(work, "issn", None) or [])
                if issn_l := await _resolve_journal(session, issns):
                    ut.journal_issn_l = issn_l
                    stats["journal_resolved"] += 1
            await ingest.finish_run("completed", dict(stats))
            await ingest.commit()
    return stats


async def resolve_journals_cerif(session: AsyncSession, limit: int | None = None) -> dict[str, int]:
    """Final ladder rung: Pure CERIF issn -> journal, for still-unresolved works."""
    query = (
        select(UtWork)
        .where(UtWork.journal_issn_l.is_(None), UtWork.cerif_issn.is_not(None))
        .limit(limit)
    )
    works = (await session.execute(query)).scalars().all()
    stats = {"works": len(works), "journal_resolved": 0}
    for ut in works:
        if issn_l := await _resolve_journal(session, [ut.cerif_issn]):
            ut.journal_issn_l = issn_l
            stats["journal_resolved"] += 1
    await session.commit()
    return stats


async def enrichment_summary(session: AsyncSession) -> dict[str, Any]:
    """Acceptance metrics: DOI fill + journal resolution rates."""
    total, with_doi, with_journal, doi_works_with_journal = (
        await session.execute(
            select(
                func.count(),
                func.count(UtWork.doi_normalized),
                func.count(UtWork.journal_issn_l),
                select(func.count())
                .select_from(UtWork)
                .where(
                    UtWork.doi_normalized.is_not(None),
                    UtWork.journal_issn_l.is_not(None),
                )
                .scalar_subquery(),
            )
        )
    ).one()
    return {
        "works": total,
        "with_doi": with_doi,
        "doi_fill": round(with_doi / total, 3) if total else None,
        "with_journal": with_journal,
        "doi_works_with_journal": round(
            doi_works_with_journal / with_doi, 3
        )
        if with_doi
        else None,
    }
