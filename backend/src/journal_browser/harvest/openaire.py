"""Harvest OpenAIRE research products for UT via aireloom (phase 9).

Full sweep of the Graph's research products linked to the home institution
(relOrganizationId filter), stored verbatim in source_records; DOI matches
against ut_works become confirmed work_identity rows.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..ingest import IngestSession
from ..models import UtWork, WorkIdentity

logger = logging.getLogger(__name__)

SOURCE = "openaire"
PAGE_SIZE = 100  # OpenAIRE Graph v3 pageSize maximum

try:
    from aireloom import AireloomClient
    from aireloom.endpoints import ResearchProductsFilters
    from aireloom.models import ResearchProduct
except ImportError:  # pragma: no cover
    AireloomClient = None


def _org_id() -> str | None:
    """OpenAIRE organization id for the institution harvest.

    The OpenAIRE id is NOT derivable from the ROR — it is a lookup, not a
    transformation. Unset means the harvest is off (find yours at
    api.openaire.eu/graph/v1/organizations?legalName=<name>).
    """
    return _settings().openaire_org_id or None


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
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Sweep OpenAIRE research products for the institution; store verbatim.

    DOI matches become confirmed work_identity rows (source='openaire').
    """
    if AireloomClient is None:  # pragma: no cover
        raise RuntimeError("aireloom is not installed")
    org_id = _org_id()
    if org_id is None:
        return {"skipped": "JB_OPENAIRE_ORG_ID is not set"}
    filter_set = f"relOrganizationId={org_id}"
    ingest = IngestSession(session)
    config = {"filter_set": filter_set, "page_size": PAGE_SIZE}
    await ingest.start_run(SOURCE, "work", filter_set, config)

    doi_to_work = {
        doi: uuid
        for doi, uuid in (
            await session.execute(
                select(UtWork.doi_normalized, UtWork.pure_uuid).where(
                    UtWork.doi_normalized.is_not(None),
                    UtWork.retired_at.is_(None),
                )
            )
        ).all()
    }

    stats: dict[str, Any] = {"matched_doi": 0, "no_doi": 0}
    async with AireloomClient() as client:
        async for item in client.research_products.iterate(
            filters=ResearchProductsFilters(relOrganizationId=org_id),
            page_size=PAGE_SIZE,
        ):
            if not isinstance(item, ResearchProduct):
                pk = item.get("id") if isinstance(item, dict) else None
                await ingest.record_parse_failure(
                    {"source_pk": pk, "reason": "ResearchProduct model parse failure"}
                )
                continue
            payload = _strip_nuls(item.model_dump(mode="json"))
            kind, _ = await ingest.ingest_record(item.id, payload)
            doi = _extract_doi(item)
            if doi and (uuid := doi_to_work.get(doi)):
                await _confirm(session, source_pk=item.id, ut_work_id=uuid)
                stats["matched_doi"] += 1
            elif not doi:
                stats["no_doi"] += 1
            if limit is not None and ingest.records_seen >= limit:
                break
    final = await ingest.finish_run("completed", stats)
    await ingest.commit()
    return final


async def _confirm(session: AsyncSession, *, source_pk: str, ut_work_id: str) -> None:
    stmt = (
        pg_insert(WorkIdentity)
        .values(
            source=SOURCE,
            source_pk=source_pk,
            ut_work_id=ut_work_id,
            matched_by="doi",
            confidence=1.0,
            status="confirmed",
        )
        .on_conflict_do_nothing(constraint="uq_work_identity_source")
    )
    await session.execute(stmt)


TRGM_THRESHOLD = 0.82

_MATCH_SQL = """
WITH openaire AS (
    SELECT DISTINCT ON (sr.source_pk)
        sr.source_pk, sr.payload->>'mainTitle' AS title
    FROM source_records sr
    WHERE sr.source = 'openaire' AND sr.entity_type = 'work'
      AND sr.payload->>'mainTitle' IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM work_identity wi
          WHERE wi.source = 'openaire' AND wi.source_pk = sr.source_pk
      )
    LIMIT :limit
)
SELECT o.source_pk, o.title, w.pure_uuid,
       similarity(lower(regexp_replace(o.title, '[^0-9a-zA-Z]+', ' ', 'g')),
                  w.norm_title) AS sim
FROM openaire o
JOIN ut_works w
  ON w.norm_title % (lower(regexp_replace(o.title, '[^0-9a-zA-Z]+', ' ', 'g')))
ORDER BY o.source_pk, sim DESC
"""


async def match_openaire_titles(session: AsyncSession, limit: int | None = None) -> dict[str, Any]:
    """Trigram title matching: OpenAIRE works -> ut_works candidates.

    The Graph API serves no DOIs on list endpoints, so OpenAIRE records
    match by normalized title only. Only the best-scoring work per record
    lands, always as status='candidate' (never auto-confirmed) for the
    curation report. The join uses the pg_trgm ``%`` operator so the GIN
    trigram index on ut_works.norm_title applies; similarity(...) >= const
    would plan as a 470M-row nested loop.
    """
    from sqlalchemy import text

    # % reads the threshold from the GUC; parameters are not allowed in SET.
    # Transaction-local (true): a session-scoped 0.82 would leak to every
    # later trigram query on this pooled connection.
    await session.execute(
        text("SELECT set_config('pg_trgm.similarity_threshold', :thr, true)"),
        {"thr": str(TRGM_THRESHOLD)},
    )
    rows = (await session.execute(text(_MATCH_SQL), {"limit": limit or 100000})).all()
    seen: set[str] = set()
    for r in rows:
        if r.source_pk in seen:
            continue
        seen.add(r.source_pk)
        stmt = (
            pg_insert(WorkIdentity)
            .values(
                source=SOURCE,
                source_pk=r.source_pk,
                ut_work_id=r.pure_uuid,
                matched_by=f"trgm:{TRGM_THRESHOLD}",
                confidence=float(r.sim),
                status="candidate",
                note=f"openaire title: {r.title[:160]}",
            )
            .on_conflict_do_nothing(constraint="uq_work_identity_source")
        )
        await session.execute(stmt)
    await session.commit()
    return {"openaire_records_scanned": len(rows), "candidates": len(seen)}
