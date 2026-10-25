"""Shared harvest helpers: HTTP fetching, ISSN normalization, run wrapper."""

import asyncio
import csv
import io
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..ingest import IngestSession, store_raw_file
from ..models import Institution, IssnMap

logger = logging.getLogger(__name__)

ISSN_RE = re.compile(r"^\d{4}-?\d{3}[\dXx]$")

# Transient HTTP failures worth one retry; everything else fails loudly.
_RETRY_STATUS = {429, 500, 502, 503, 504}


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


# Closed OA-status vocabulary for ut_works.oa_status: OpenAlex's set, per the
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
                if response.status_code in _RETRY_STATUS:
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
                    and exc.response.status_code in _RETRY_STATUS
                )
                if not transient or attempt == retries - 1:
                    raise
                delay = 2**attempt
                if isinstance(exc, httpx.HTTPStatusError):
                    retry_after = exc.response.headers.get("retry-after", "")
                    if retry_after.isdigit():
                        delay = max(delay, min(int(retry_after), 30))
                await asyncio.sleep(delay)
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


async def get_home_institution(session: AsyncSession) -> Institution:
    """The configured home institution row (created on first call)."""
    settings = get_settings()
    inst = await session.scalar(
        select(Institution).where(Institution.ror == settings.institution_ror)
    )
    if inst is None:
        inst = Institution(
            name=settings.institution_name,
            ror=settings.institution_ror,
            is_home=True,
        )
        session.add(inst)
        await session.flush()
    return inst


async def run_harvest(
    source: str,
    entity_type: str,
    filter_set: str,
    config: dict[str, Any],
    body: Callable[[IngestSession], Awaitable[dict[str, Any] | None]],
    session: AsyncSession,
) -> dict[str, Any]:
    """Standard run wrapper: start run, execute body, commit, close run.

    The body receives the IngestSession and is responsible for per-page
    commits; any exception marks the run failed after committing what
    landed (per-page commits make that safe).
    """
    ingest = IngestSession(session)
    await ingest.start_run(source, entity_type, filter_set, config)
    try:
        stats = await body(ingest) or {}
        final = await ingest.finish_run("completed", stats)
        await session.commit()
        return final
    except Exception:
        logger.exception("Harvest %s/%s failed", source, entity_type)
        await ingest.finish_run("failed", {"error": "see logs"})
        await session.commit()
        raise
