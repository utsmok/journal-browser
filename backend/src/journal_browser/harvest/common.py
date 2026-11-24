"""Shared harvest helpers: HTTP fetching, ISSN normalization, run wrapper."""

import asyncio
import csv
import io
import logging
import os
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from bibliofabric.exceptions import NotFoundError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..ingest import IngestSession, store_raw_file
from ..models import Institution, IssnMap

logger = logging.getLogger(__name__)


ISSN_RE = re.compile(r"^\d{4}-?\d{3}[\dXx]$")

# Transient HTTP failures worth one retry; everything else fails loudly.
RETRY_STATUS = {429, 500, 502, 503, 504}

HTTP_RETRY_SLEEP = 5.0
HTTP_RETRY_MAX_SLEEP = 60.0


def retry_delay(attempt: int, retry_after: str) -> float:
    """Retry-After seconds when numeric, else capped exponential backoff."""
    if retry_after.isdigit():
        return float(retry_after)
    return min(HTTP_RETRY_SLEEP * 2 ** (attempt - 1), HTTP_RETRY_MAX_SLEEP)


def normalize_issn(raw: str | None) -> str | None:
    """Normalize to XXXX-XXXX form; None when not ISSN-shaped."""
    if not raw:
        return None
    issn = raw.strip().upper()
    if not ISSN_RE.match(issn):
        return None
    if "-" not in issn:
        issn = f"{issn[:4]}-{issn[4:]}"
    return issn


def issn_checksum_ok(issn: str | None) -> bool:
    """Mod-11 ISSN check digit ('X' = 10). Shape-only normalize_issn callers
    that write normalized columns gate on this."""
    if not issn:
        return False
    core = issn.replace("-", "")
    if not re.fullmatch(r"\d{7}[\dX]", core):
        return False
    total = sum(int(d) * (8 - i) for i, d in enumerate(core[:7]))
    check = (11 - total % 11) % 11
    return core[7] == ("X" if check == 10 else str(check))


# Closed OA-status vocabulary for works.oa_status: OpenAlex's set, per the
# limitations registry row "openalex-oa-status". Every writer maps onto this.
OA_STATUSES = frozenset({"gold", "hybrid", "green", "bronze", "diamond", "closed"})


def canonical_oa_status(raw: str | None) -> str | None:
    """OpenAlex oa_status literal -> OA_STATUSES; empty/None stays None,
    anything outside the vocabulary maps to "closed"."""
    if not raw:
        return None
    return raw if raw in OA_STATUSES else "closed"


async def fetch_bytes(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    retries: int = 3,
    timeout: float = 120.0,
) -> bytes:
    """Fetch a URL with retry/backoff; raises on final failure."""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                response = await client.request(method, url, content=data)
                if response.status_code in RETRY_STATUS:
                    raise httpx.HTTPStatusError(
                        f"transient status {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response.content
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                transient = isinstance(exc, httpx.TransportError) or (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code in RETRY_STATUS
                )
                if not transient or attempt == retries - 1:
                    raise
                delay = 2**attempt
                if isinstance(exc, httpx.HTTPStatusError):
                    retry_after = exc.response.headers.get("retry-after", "")
                    if retry_after.isdigit():
                        delay = max(delay, min(int(retry_after), 30))
                await asyncio.sleep(delay)
        assert last_error is not None  # loop always runs at least one attempt
        raise last_error  # pragma: no cover


async def download_to_landing(
    session: AsyncSession,
    ingest: IngestSession,
    source: str,
    entity_type: str,
    url: str,
    suffix: str,
    source_pk: str = "",
    headers: dict[str, str] | None = None,
    retries: int = 3,
) -> tuple[bytes, bool]:
    """Fetch a URL, store the raw bytes in the landing dir, record the file.

    Returns (data, is_new_version). Call BEFORE any normalization so a
    crash never loses a fetched copy.
    """
    data = await fetch_bytes(url, headers=headers, retries=retries)
    _, _, is_new = await store_raw_file(
        session,
        source,
        entity_type,
        url,
        data,
        suffix,
        source_pk=source_pk,
        harvest_run_id=ingest.run_id,
    )
    return data, is_new


def parse_csv_rows(data: bytes, delimiter: str = ",") -> list[dict[str, str]]:
    """Decode + parse a CSV into dicts; strips BOM and stray whitespace."""
    text = data.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))


class HarvestDataError(RuntimeError):
    """Upstream payload shape broke; the harvest must fail, not produce empties."""


def require_headers(rows: list[dict[str, str]], required: set[str], source: str) -> None:
    """Fail the run when upstream renamed/dropped a column we read, or sent
    an empty payload — silent empty output would pass unnoticed otherwise."""
    if not rows:
        raise HarvestDataError(f"{source}: payload has no rows")
    missing = required - rows[0].keys()
    if missing:
        raise HarvestDataError(f"{source}: missing columns {sorted(missing)}")


async def resolve_issn_l(session: AsyncSession, issn: str | None) -> str | None:
    """ISSN → ISSN-L via the harvested issn_map; normalized input passthrough
    when no mapping exists (the input may already be the linking ISSN)."""
    issn = normalize_issn(issn)
    if issn is None:
        return None
    row = await session.get(IssnMap, issn)
    return row.issn_l if row else issn


async def lookup_issn_l(session: AsyncSession, issn: str | None) -> str | None:
    """Strict ISSN → ISSN-L via issn_map only; None when unmapped.

    Use for third-party data (scimagojr, OpenAPC fallback) where the input
    ISSN is not known to be a linking ISSN.
    """
    issn = normalize_issn(issn)
    if issn is None:
        return None
    row = await session.get(IssnMap, issn)
    return row.issn_l if row else None


async def upsert_issn_map(
    session: AsyncSession, issns: list[str] | None, issn_l: str | None, source: str
) -> None:
    """Index every variant ISSN of a journal to its linking ISSN."""
    if not issn_l:
        return
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    for issn in {normalize_issn(i) for i in (issns or []) if normalize_issn(i)} | {issn_l}:
        await session.execute(
            pg_insert(IssnMap)
            .values(issn=issn, issn_l=issn_l, source=source)  # type: ignore[arg-type]
            .on_conflict_do_update(
                index_elements=["issn"], set_={"issn_l": issn_l, "source": source}
            )
        )


async def get_home_institution(session: AsyncSession) -> Institution | None:
    """The env-configured home institution, if present."""
    ror = get_settings().institution_ror
    return await session.scalar(select(Institution).where(Institution.ror == ror))


async def ensure_home_institution(session: AsyncSession) -> Institution:
    """The home institution row, seeded from env on first call."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    settings = get_settings()
    existing = await get_home_institution(session)
    if existing is not None:
        return existing
    inst = await session.scalar(
        select(Institution).where(Institution.ror == settings.institution_ror)
    )
    if inst is not None:
        # Env-seed onto an existing participation-only row (e.g. created by
        # a JCT ingest that listed this institution in some deal sheet).
        inst.code = settings.institution_code
        inst.short_name = settings.institution_short
        inst.pure_oai_base_url = settings.pure_oai_base_url
        inst.openaire_org_id = settings.openaire_org_id
        inst.external_works_dsn = settings.ut_metadata_dsn or None
        inst.data_window_start = settings.data_window_start
        inst.data_window_end = settings.data_window_end
        inst.library_url = settings.library_url
        inst.oa_guide_url = settings.oa_guide_url
        inst.support_email = settings.support_email
        inst.admin_contact = settings.admin_contact
        inst.research_portal_url = settings.research_portal_url
        inst.active = True
        await session.flush()
        return inst
    code = settings.institution_code.strip().lower()
    await session.execute(
        pg_insert(Institution)
        .values(
            code=code,
            name=settings.institution_name,
            short_name=settings.institution_short,
            ror=settings.institution_ror,
            pure_oai_base_url=settings.pure_oai_base_url,
            openaire_org_id=settings.openaire_org_id,
            external_works_dsn=settings.ut_metadata_dsn or None,
            data_window_start=settings.data_window_start,
            data_window_end=settings.data_window_end,
            library_url=settings.library_url,
            oa_guide_url=settings.oa_guide_url,
            support_email=settings.support_email,
            admin_contact=settings.admin_contact,
            research_portal_url=settings.research_portal_url,
            active=True,
        )
        .on_conflict_do_nothing(index_elements=["ror"])
    )
    inst = await session.scalar(
        select(Institution).where(Institution.ror == settings.institution_ror)
    )
    assert inst is not None
    await session.flush()
    return inst


async def get_institution_by_code(session: AsyncSession, code: str) -> Institution | None:
    """One hosted institution by its path code."""
    return await session.scalar(
        select(Institution).where(Institution.code == code, Institution.active.is_(True))
    )


async def resolve_institution(session: AsyncSession, code: str | None) -> Institution:
    """Institution for a job's --institution flag: by code, or the env home."""
    if code is None:
        return await ensure_home_institution(session)
    inst = await get_institution_by_code(session, code)
    if inst is None:
        raise SystemExit(f"unknown or inactive institution code: {code!r}")
    return inst


async def run_harvest(
    source: str,
    entity_type: str,
    filter_set: str,
    config: dict[str, Any],
    body: Callable[[IngestSession], Awaitable[dict[str, Any] | None]],
    session: AsyncSession,
    institution_id: int | None = None,
) -> dict[str, Any]:
    """Standard run wrapper: start run, execute body, commit, close run.

    The body receives the IngestSession and is responsible for per-page
    commits; any exception marks the run failed after committing what
    landed (per-page commits make that safe).
    """
    ingest = IngestSession(session)
    await ingest.start_run(source, entity_type, filter_set, config, institution_id)
    try:
        stats = await body(ingest) or {}
        final = await ingest.finish_run("completed", stats)
        await session.commit()
        return final
    except Exception as exc:
        logger.exception("Harvest %s/%s failed", source, entity_type)
        await ingest.finish_run("failed", {"error": f"{type(exc).__name__}: {exc}"[:200]})
        await session.commit()
        raise


def require_openalex_key(step: str) -> str:
    """Return the OpenAlex API key, raising when it is unset.

    Keyless requests serve only the first cursor page (and 10k results),
    so a listing/cursor sweep without a key would harvest one page and
    finish 'completed' with silently partial data. Sweeps call this
    before starting a run and fail with a message naming the step."""
    key = get_settings().openalex_api_key
    if not key:
        raise RuntimeError(
            f"{step}: OPENALEX_API_KEY/JB_OPENALEX_API_KEY is not set; "
            "a keyless listing sweep would harvest only the first page"
        )
    return key


async def openalex_credits_remaining() -> float | None:
    """Remaining daily USD credit budget from OpenAlex's rate-limit
    endpoint; None when the check fails or no key is set (gate stays
    open: a keyless install has no per-key budget to check, so no HTTP)."""
    api_key = get_settings().openalex_api_key
    if not api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.openalex.org/rate-limit",
                params={"api_key": api_key} if api_key else None,
            )
        bucket = (resp.json() or {}).get("rate_limit") or {}
        remaining = bucket.get("daily_remaining_usd")
        return float(remaining) if remaining is not None else None
    except Exception:
        return None


async def openalex_budget_ok(stage: str, stats: dict[str, Any] | None = None) -> bool:
    """True while the daily OpenAlex budget clears the reserve.

    OpenAlex-spending stages call this before each chunk and stop cleanly
    when the remaining budget falls below JB_OPENALEX_RESERVE_USD (default
    0.25): the reserve keeps the /rate-limit endpoint itself answerable and
    leaves headroom instead of draining the day to zero. A failed check
    (openalex_credits_remaining returns None) keeps the gate open, as with
    a keyless install. Singleton GETs bill $0 (measured 2026-11-20); the
    budget is drawn by list pages ($0.0001) and searches ($0.001), so the
    gate mainly protects the priced stages and catches pricing drift.
    Trips log a warning and set stats["openalex_reserve_stop"] = 1."""
    remaining = await openalex_credits_remaining()
    if remaining is None:
        return True
    reserve = get_settings().openalex_reserve_usd
    if remaining >= reserve:
        return True
    logger.warning(
        "openalex budget reserve hit: %s stops cleanly (remaining $%.4f "
        "below the $%.2f reserve; budget resets 00:00 UTC)",
        stage,
        remaining,
        reserve,
    )
    if stats is not None:
        stats["openalex_reserve_stop"] = 1
    return False


async def paced_single_gets(
    get: Callable[[str], Awaitable[Any]],
    ids: list[str],
    *,
    concurrency: int = 10,
    min_interval_s: float | None = None,
) -> tuple[dict[str, Any | None], dict[str, Exception]]:
    """Free single-entity GETs paced to the OpenAlex tier cap.

    Singleton lookups bill $0 (measured 2026-11-20, x-ratelimit-cost-usd:
    0), so they work even with the credit budget at zero and gap-filling
    (journals, funders) never needs a listing sweep; list pages cost
    $0.0001 and searches $0.001 against the $1/day key budget. Claims
    each request's start slot synchronously before sleeping — assigning
    after the sleep lets every coroutine read the same stale slot and
    fire as an unspaced burst (see enrich.fetch_works_by_doi). 404s and
    per-id failures isolate: misses map to None, other exceptions land
    in the failed dict; only every id failing raises, so systemic
    breakage never masquerades as an empty sweep.
    """
    if not ids:
        return {}, {}
    if min_interval_s is None:
        min_interval_s = float(os.environ.get("JB_OPENALEX_MIN_INTERVAL_S", "0.08"))
    sem = asyncio.Semaphore(concurrency)
    next_slot = 0.0
    loop = asyncio.get_running_loop()

    async def one(iid: str) -> tuple[str, Any | None, Exception | None]:
        nonlocal next_slot
        async with sem:
            now = loop.time()
            start = max(now, next_slot)
            next_slot = start + min_interval_s
            if start > now:
                await asyncio.sleep(start - now)
            try:
                return iid, await get(iid), None
            except NotFoundError:
                return iid, None, None
            except Exception as exc:
                return iid, None, exc

    out: dict[str, Any | None] = {}
    failed: dict[str, Exception] = {}
    for iid, payload, exc in await asyncio.gather(*(one(i) for i in ids)):
        out[iid] = payload
        if exc is not None:
            failed[iid] = exc
    if len(failed) == len(ids):
        first = next(iter(failed.values()))
        raise RuntimeError(
            f"paced_single_gets: all {len(ids)} lookups failed (first: {first!r})"
        ) from first
    return out, failed
