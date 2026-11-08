"""Enrich canonical works and resolve them to journals (phase 9).

Ladder per docs/plan-pure-openaire-crossref.md, per work:

1. OpenAlex (aletheca, one single-entity GET per DOI): confirms the DOI
   identity, fills oa_status, and supplies the journal via the work's
   primary source. Single-entity calls are free under OpenAlex's 2026-11
   credit pricing, unlike the 50-DOI pipe-OR batch filter this replaced.
2. Crossref (stavrophora, env-paced, polite pool): gap fill for DOIs OpenAlex
   does not know; supplies the journal ISSN list.
3. Pure CERIF issn (already on the row from the OAI harvest).

ISSN -> journal resolution always goes through issn_map (any ISSN variant to
ISSN-L) and then journals.issn_l.
"""

import asyncio
import logging
import os
from collections.abc import Sequence
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..harvest.common import canonical_oa_status, normalize_issn, resolve_issn_l
from ..ingest import IngestSession
from ..models import WORK_IDENTITY_UQ, Journal, Work, WorkIdentity

logger = logging.getLogger(__name__)

# Single-entity GETs are free on OpenAlex; keep starts spaced so a job's
# steady-state rate stays bounded (concurrency alone is latency-bound and
# bursts past the shared 30 req/s free cap: 10 in-flight at ~150 ms
# round-trip is ~60 req/s). 0.08 s spacing ≈ 12 req/s per job; two jobs
# plus listing pages stay under the cap.
GET_CONCURRENCY = 10
#: Seconds between singleton GET starts. Rate-limit tiers differ (keyed
#: free ~10 rps vs premium higher); JB_OPENALEX_MIN_INTERVAL_S=0.13 keeps
#: a solo consumer under the free 10 rps cap, avoiding the 429 retry
#: freeze (bibliofabric sleeps rate_limit_retry_after_default=60s per 429
#: while holding its semaphore slot).
GET_MIN_INTERVAL_S = float(os.environ.get("JB_OPENALEX_MIN_INTERVAL_S", "0.08"))
FETCH_CHUNK = 500
CHUNK_PAUSE_S = 0.3
# DOIs per pipe-separated filter on the Crossref ladder (free API, no
# OpenAlex credit pricing). The OpenAlex rungs use single-entity GETs.
BATCH_SIZE = 50


def _chunk(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def fetch_works_by_doi(
    client: Any, dois: Sequence[str], stats: dict[str, int] | None = None
) -> tuple[dict[str, Any | None], set[str], Exception | None]:
    """One single-entity GET per DOI (free on OpenAlex), bounded by a
    semaphore.

    Returns ({doi: Work-or-None}, errored_dois, first_error). None marks a
    404 miss; any other failure is counted under stats["fetch_errors"],
    isolated to its DOI, and reported via first_error. A chunk where every
    lookup failed raises loudly: systemic breakage must not masquerade as
    a clean, empty sweep (and work_funders must not prune on it)."""
    sem = asyncio.Semaphore(GET_CONCURRENCY)
    next_slot = 0.0

    async def one(doi: str) -> tuple[str, Any | None, bool, Exception | None]:
        nonlocal next_slot
        async with sem:
            # Claim the next start slot synchronously (read+assign with no
            # await in between), then sleep up to it — assigning after the
            # sleep lets every coroutine read the same stale slot and fire
            # as an unspaced burst.
            loop = asyncio.get_running_loop()
            now = loop.time()
            start = max(now, next_slot)
            next_slot = start + GET_MIN_INTERVAL_S
            if start > now:
                await asyncio.sleep(start - now)
            try:
                return doi, await client.works.get(f"https://doi.org/{doi}"), False, None
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status == 404:
                    return doi, None, False, None
                return doi, None, True, exc

    out: dict[str, Any | None] = {}
    errored: set[str] = set()
    first_error: Exception | None = None
    dois = list(dois)
    for at in range(0, len(dois), FETCH_CHUNK):
        chunk = dois[at : at + FETCH_CHUNK]
        if at:
            await asyncio.sleep(CHUNK_PAUSE_S)
        chunk_failed = 0
        for doi, work, failed, exc in await asyncio.gather(*(one(d) for d in chunk)):
            out[doi] = work
            if failed:
                errored.add(doi)
                chunk_failed += 1
                first_error = first_error or exc
        if chunk_failed == len(chunk):
            raise RuntimeError(
                f"openalex fetch: all {len(chunk)} lookups in chunk failed "
                f"(first error: {first_error!r})"
            ) from first_error
    if stats is not None:
        stats["fetch_errors"] = stats.get("fetch_errors", 0) + len(errored)
    return out, errored, first_error


async def _batch_by_doi_resilient(fetch: Any, chunk: list[str], stats: dict[str, int]) -> dict:
    """fetch(chunk) with API-side rejection isolated to the offending DOI.

    One malformed/unknown-to-the-filter DOI in a 50-DOI batch makes Crossref
    reject the whole request with a 400, which used to fail the entire
    enrichment run. Bisect client-error batches until the bad DOI stands
    alone, then skip + count it. Transient/systemic failures (5xx, 429,
    network) re-raise: retry logic lives upstream. Crossref-only: the
    OpenAlex rungs fetch per entity via fetch_works_by_doi."""
    from bibliofabric.exceptions import APIError, RateLimitError

    try:
        return await fetch(chunk)
    except RateLimitError:
        raise
    except APIError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status is not None and (status < 400 or status >= 500 or status == 429):
            raise
        if len(chunk) == 1:
            logger.warning("enrichment: API rejected doi %s; skipped (%s)", chunk[0], exc)
            stats["dois_rejected"] = stats.get("dois_rejected", 0) + 1
            return {}
        mid = len(chunk) // 2
        found: dict = {}
        for half in (chunk[:mid], chunk[mid:]):
            found.update(await _batch_by_doi_resilient(fetch, half, stats))
        return found


def _norm_doi_key(key: Any) -> str:
    """Client result keys may be bare DOIs or https://doi.org/ URLs."""
    return str(key).lower().removeprefix("https://doi.org/")


async def _journal_exists(session: AsyncSession, issn_l: str) -> bool:
    return await session.scalar(select(Journal.issn_l).where(Journal.issn_l == issn_l)) is not None


async def _resolve_journal(session: AsyncSession, issns: list[Any]) -> str | None:
    """Any ISSN variant -> issn_map -> journals.issn_l; first hit wins."""
    for raw in issns:
        issn = normalize_issn(str(raw))
        if not issn:
            continue
        issn_l = await resolve_issn_l(session, issn)
        if issn_l and await session.scalar(select(Journal.issn_l).where(Journal.issn_l == issn_l)):
            return issn_l
    return None


async def _confirm_identity(
    session: AsyncSession,
    *,
    institution_id: int,
    source: str,
    source_pk: str,
    work_id: str,
    matched_by: str = "doi",
    confidence: float = 1.0,
) -> None:
    """Insert one confirmed work identity (idempotent per institution)."""
    stmt = (
        pg_insert(WorkIdentity)
        .values(
            institution_id=institution_id,
            source=source,
            source_pk=source_pk,
            work_id=work_id,
            matched_by=matched_by,
            confidence=confidence,
            status="confirmed",
        )
        .on_conflict_do_nothing(constraint=WORK_IDENTITY_UQ)
    )
    await session.execute(stmt)


def _openalex_work_fields(work: Any) -> dict[str, Any]:
    """Extract the fields we keep from one aletheca Work model."""
    fields: dict[str, Any] = {}
    oa = getattr(work, "open_access", None)
    oa_status = canonical_oa_status(getattr(oa, "oa_status", None))
    if oa_status:
        fields["oa_status"] = oa_status
    location = getattr(work, "primary_location", None)
    source = (
        location.get("source") if isinstance(location, dict) else getattr(location, "source", None)
    )
    issn_l = source.get("issn_l") if isinstance(source, dict) else getattr(source, "issn_l", None)
    if issn_l:
        fields["journal_issn_l"] = issn_l
    return fields


async def _works_needing_journal(
    session: AsyncSession, institution_id: int, limit: int | None
) -> list[Work]:
    """One institution's DOI works still lacking a journal, excluding
    recorded OpenAlex misses.

    Re-fetches matched works whose journal stayed unresolved; runs are rare
    and the batch is bounded, so the redundant lookups are accepted.
    """
    recorded_miss = exists(
        select(WorkIdentity.id)
        .where(
            WorkIdentity.institution_id == institution_id,
            WorkIdentity.work_id == Work.pure_uuid,
            WorkIdentity.source == "openalex",
            WorkIdentity.source_pk.like("doi:%"),
        )
        .correlate(Work)
    )
    query = (
        select(Work)
        .where(
            Work.institution_id == institution_id,
            Work.doi_normalized.is_not(None),
            Work.journal_issn_l.is_(None),
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


async def _works_for_refresh(
    session: AsyncSession, institution_id: int, limit: int | None
) -> list[Work]:
    """Every DOI work of the institution, matched or not, for full
    refreshes (`--refresh-matched`): upstream dedup merges move canonical
    OpenAlex ids and re-tag stored fields, so already-matched works need
    re-confirmation too."""
    query = (
        select(Work)
        .where(
            Work.institution_id == institution_id,
            Work.doi_normalized.is_not(None),
        )
        .order_by(Work.pure_uuid)
        .limit(limit)
    )
    return list((await session.execute(query)).scalars().all())


async def _mark_openalex_miss(
    session: AsyncSession, institution_id: int, doi: str, work_uuid: str
) -> None:
    """Record a 404 so the Crossref pass only sees true gaps."""
    stmt = (
        pg_insert(WorkIdentity)
        .values(
            institution_id=institution_id,
            source="openalex",
            source_pk=f"doi:{doi}",
            work_id=work_uuid,
            matched_by="doi",
            confidence=None,  # missing = no evidence, not zero confidence
            status="missing",
        )
        .on_conflict_do_nothing(constraint=WORK_IDENTITY_UQ)
    )
    await session.execute(stmt)


async def enrich_openalex(
    session: AsyncSession,
    institution_id: int,
    limit: int | None = None,
    *,
    refresh_matched: bool = False,
) -> dict[str, int]:
    """Single-entity DOI lookups; confirm identities + resolve journals
    from OpenAlex.

    OpenAlex's 2026-11 credit pricing keeps get-single-entity calls free
    while list/filter calls cost credits, so each DOI gets its own GET
    instead of a 50-DOI pipe filter (whose single malformed DOI used to
    poison the whole batch). `refresh_matched` widens the selection from
    journal-less works to every DOI work of the institution."""
    from aletheca import AlethecaClient

    works = (
        await _works_for_refresh(session, institution_id, limit)
        if refresh_matched
        else await _works_needing_journal(session, institution_id, limit)
    )
    stats = {"works": len(works), "matched": 0, "journal_resolved": 0}
    if not works:
        return stats

    client_kwargs: dict[str, Any] = {}
    if get_api_key := getattr(_settings(), "openalex_api_key", ""):
        client_kwargs["api_key"] = get_api_key
    by_doi = {w.doi_normalized: w for w in works}
    ingest = IngestSession(session)
    await ingest.start_run(
        "openalex",
        "work",
        "enrichment",
        {"via": "single_get_by_doi", "refresh": refresh_matched},
        institution_id=institution_id,
    )
    fetch_stats: dict[str, int] = {}
    async with AlethecaClient(**client_kwargs) as client:
        dois = sorted(by_doi)
        for at in range(0, len(dois), FETCH_CHUNK):
            chunk = dois[at : at + FETCH_CHUNK]
            found, errored, first_error = await fetch_works_by_doi(client, chunk, fetch_stats)
            if errored:
                logger.warning(
                    "openalex enrichment: %d/%d lookups failed this chunk (first: %r); "
                    "affected DOIs left untouched",
                    len(errored),
                    len(chunk),
                    first_error,
                )
            for doi in chunk:
                ut = by_doi[doi]
                work = found.get(doi)
                if work is None:
                    if doi not in errored:
                        await _mark_openalex_miss(session, institution_id, doi, ut.pure_uuid)
                    continue
                fields = _openalex_work_fields(work)
                # FK guard: ut_works.journal_issn_l -> journals.issn_l. OpenAlex
                # can cite a journal this DB has not ingested; drop the link
                # (counted) instead of failing the whole chunk at flush.
                if fields.get("journal_issn_l") and not await _journal_exists(
                    session, fields["journal_issn_l"]
                ):
                    logger.warning(
                        "openalex enrichment: journal %s not ingested; link dropped (doi=%s)",
                        fields.pop("journal_issn_l"),
                        doi,
                    )
                    stats["journal_fk_skipped"] = stats.get("journal_fk_skipped", 0) + 1
                for name, value in fields.items():
                    setattr(ut, name, value)
                await ingest.ingest_record(
                    str(getattr(work, "id", "") or f"doi:{doi}"),
                    work.model_dump(mode="json"),
                )
                await _confirm_identity(
                    session,
                    institution_id=institution_id,
                    source="openalex",
                    source_pk=str(getattr(work, "id", "") or ""),
                    work_id=ut.pure_uuid,
                )
                stats["matched"] += 1
                if fields.get("journal_issn_l"):
                    stats["journal_resolved"] += 1
                elif issn_l := await _resolve_journal(session, _location_issns(work)):
                    # Primary location had no journal; any location's source
                    # (e.g. the journal's own landing page) still counts.
                    ut.journal_issn_l = issn_l
                    stats["journal_resolved"] += 1
            await ingest.commit()
    stats.update(fetch_stats)
    # Finalize once, after the last chunk: a mid-run crash must not leave a
    # "completed" run whose later chunks were rolled back.
    await ingest.finish_run("completed", dict(stats))
    await session.commit()
    return stats


def _settings() -> Any:
    from ..config import get_settings

    return get_settings()


async def _works_for_crossref(
    session: AsyncSession, institution_id: int, limit: int | None
) -> list[Work]:
    """Works with a DOI, no crossref identity, and no successful OpenAlex match.

    OpenAlex 'missing' rows carry source_pk='doi:<doi>' and are NOT counted
    as matches, so true OpenAlex gaps still reach Crossref.
    """
    no_openalex = ~exists(
        select(WorkIdentity.id)
        .where(
            WorkIdentity.institution_id == institution_id,
            WorkIdentity.work_id == Work.pure_uuid,
            WorkIdentity.source == "openalex",
            WorkIdentity.source_pk.not_like("doi:%"),
        )
        .correlate(Work)
    )
    query = (
        select(Work)
        .where(
            Work.institution_id == institution_id,
            Work.doi_normalized.is_not(None),
            no_openalex,
            ~exists(
                select(WorkIdentity.id)
                .where(
                    WorkIdentity.institution_id == institution_id,
                    WorkIdentity.work_id == Work.pure_uuid,
                    WorkIdentity.source == "crossref",
                )
                .correlate(Work)
            ),
        )
        .limit(limit)
    )
    return list((await session.execute(query)).scalars().all())


async def enrich_crossref(
    session: AsyncSession, institution_id: int, limit: int | None = None
) -> dict[str, int]:
    """Gap fill: DOIs OpenAlex missed -> stavrophora; journal via ISSN list."""
    from stavrophora import StavrophoraClient

    works = await _works_for_crossref(session, institution_id, limit)
    stats = {"works": len(works), "matched": 0, "journal_resolved": 0}
    if not works:
        return stats

    by_doi = {w.doi_normalized: w for w in works}
    ingest = IngestSession(session)
    await ingest.start_run(
        "crossref",
        "work",
        "enrichment",
        {"via": "batch_get_by_doi"},
        institution_id=institution_id,
    )
    async with StavrophoraClient(mailto=_settings().contact_email) as client:
        for chunk in _chunk(list(by_doi), BATCH_SIZE):
            found = await _batch_by_doi_resilient(client.works.batch_get_by_doi, chunk, stats)
            for key, work in found.items():
                ut = by_doi.get(_norm_doi_key(key))
                if ut is None:
                    continue
                payload = (
                    work.model_dump(mode="json") if hasattr(work, "model_dump") else dict(work)
                )
                await ingest.ingest_record(f"doi:{ut.doi_normalized}", payload)
                await _confirm_identity(
                    session,
                    institution_id=institution_id,
                    source="crossref",
                    source_pk=f"doi:{ut.doi_normalized}",
                    work_id=ut.pure_uuid,
                )
                stats["matched"] += 1
                issns = list(getattr(work, "issn", None) or [])
                if issn_l := await _resolve_journal(session, issns):
                    ut.journal_issn_l = issn_l
                    stats["journal_resolved"] += 1
            await ingest.commit()
    await ingest.finish_run("completed", dict(stats))
    await session.commit()
    return stats


async def resolve_journals_cerif(
    session: AsyncSession, institution_id: int, limit: int | None = None
) -> dict[str, int]:
    """Final ladder rung: Pure CERIF issn -> journal, for still-unresolved works."""
    query = (
        select(Work)
        .where(
            Work.institution_id == institution_id,
            Work.journal_issn_l.is_(None),
            Work.cerif_issn.is_not(None),
        )
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
                func.count(Work.doi_normalized),
                func.count(Work.journal_issn_l),
                select(func.count())
                .select_from(Work)
                .where(
                    Work.doi_normalized.is_not(None),
                    Work.journal_issn_l.is_not(None),
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
        "doi_works_with_journal": round(doi_works_with_journal / with_doi, 3) if with_doi else None,
    }
