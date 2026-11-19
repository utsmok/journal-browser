"""Harvest OpenAIRE research products for UT via aireloom (phase 9).

Full sweep of the Graph's research products linked to the home institution
(affiliations.organization_id filter), stored verbatim in source_records; DOI matches
against works become confirmed work_identity rows.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..ingest import IngestSession
from ..models import WORK_IDENTITY_UQ, Work, WorkIdentity

logger = logging.getLogger(__name__)

SOURCE = "openaire"
PAGE_SIZE = 100  # OpenAIRE Graph v3 pageSize maximum

try:
    from aireloom import AireloomClient
    from aireloom.filters import ResearchProductsFilters
except ImportError:  # pragma: no cover
    AireloomClient = None


def _org_id(institution) -> str | None:
    """OpenAIRE organization id for one institution's harvest.

    The OpenAIRE id is NOT derivable from the ROR — it is a lookup, not a
    transformation. Unset means the harvest is off for this institution
    (find yours at api.openaire.eu/graph/v1/organizations?legalName=<name>).
    """
    return institution.openaire_org_id or None


def _settings() -> Any:
    return get_settings()


def _strip_nuls(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop NUL characters that break Postgres TEXT (ut-metadata rule)."""
    import json

    text = json.dumps(payload, default=str).replace("\\u0000", "")
    return json.loads(text)


def _extract_doi(product: Any) -> str | None:
    """Best-effort DOI from an OpenAIRE product's pids."""
    from ..harvest.pure import extract_doi

    pids = getattr(product, "pids", None)
    if isinstance(pids, list):
        for pid in pids:
            scheme = (getattr(pid, "scheme", None) or "").lower()
            value = getattr(pid, "value", None) or ""
            if scheme == "doi":
                doi = extract_doi(str(value))
                if doi:
                    return doi
    dois = getattr(product, "dois", None)
    if dois:
        for value in dois:
            doi = extract_doi(str(value))
            if doi:
                return doi
    return None


async def harvest_openaire_products(
    session: AsyncSession,
    institution,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Sweep OpenAIRE research products for one institution; store verbatim.

    DOI matches become confirmed work_identity rows (source='openaire').
    """
    if AireloomClient is None:  # pragma: no cover
        raise RuntimeError("aireloom is not installed")
    org_id = _org_id(institution)
    if org_id is None:
        return {"skipped": f"institution {institution.code!r} has no openaire_org_id"}
    filter_set = f"affiliations.organization_id={org_id}"
    ingest = IngestSession(session)
    config = {"filter_set": filter_set, "page_size": PAGE_SIZE}
    await ingest.start_run(SOURCE, "work", filter_set, config, institution_id=institution.id)

    doi_to_work = dict(
        (
            await session.execute(
                select(Work.doi_normalized, Work.pure_uuid).where(
                    Work.institution_id == institution.id,
                    Work.doi_normalized.is_not(None),
                    Work.retired_at.is_(None),
                )
            )
        ).all()
    )

    stats: dict[str, Any] = {"matched_doi": 0, "no_doi": 0}
    async with AireloomClient() as client:
        failures: list[tuple[dict[str, Any], Exception]] = []
        async for item in client.research_products.iterate(
            filters=ResearchProductsFilters(affiliations_organization_id=org_id),
            page_size=PAGE_SIZE,
            on_error="skip",
            failures=failures,
        ):
            payload = _strip_nuls(item.model_dump(mode="json"))
            _kind, _ = await ingest.ingest_record(item.id, payload)
            doi = _extract_doi(item)
            if doi and (uuid := doi_to_work.get(doi)):
                await _confirm(
                    session,
                    institution_id=institution.id,
                    source_pk=item.id,
                    work_id=uuid,
                )
                stats["matched_doi"] += 1
            elif not doi:
                stats["no_doi"] += 1
            if limit is not None and ingest.records_seen >= limit:
                break
        for raw, exc in failures:
            await ingest.record_parse_failure({"source_pk": raw.get("id"), "reason": str(exc)})
    final = await ingest.finish_run("completed", stats)
    await ingest.commit()
    return final


async def _confirm(
    session: AsyncSession, *, institution_id: int, source_pk: str, work_id: str
) -> None:
    stmt = (
        pg_insert(WorkIdentity)
        .values(
            institution_id=institution_id,
            source=SOURCE,
            source_pk=source_pk,
            work_id=work_id,
            matched_by="doi",
            confidence=1.0,
            status="confirmed",
        )
        .on_conflict_do_nothing(constraint=WORK_IDENTITY_UQ)
    )
    await session.execute(stmt)
