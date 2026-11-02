"""Jisc Open Policy Finder harvester: full sweeps into landing.

API: https://api.openpolicyfinder.jisc.ac.uk/retrieve, `x-api-key` header,
`item-type` + `format=Json` required, `search_after` paging past 10k
records (echo back the `next_search_after` value from the response).
Transport verified live 2026-11-02; key read from `JB_JISC_API_KEY`.
Raw JSON lands per record (source jisc_opf, entity_type = item type);
normalization is harvest/jisc_normalize.py.
"""

import asyncio
import json
import logging
from typing import Any, Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from .common import run_harvest

logger = logging.getLogger(__name__)

SOURCE = "jisc_opf"
BASE_URL = "https://api.openpolicyfinder.jisc.ac.uk/retrieve"
SWEEP_TYPES = (
    "publication",
    "publisher",
    "publisher_policy",
    "funder",
    "funder_group",
    "repository",
)


class _SweepIngest(Protocol):
    """What sweep_type needs; IngestSession satisfies it."""

    async def ingest_records(self, records: list[tuple[str, dict[str, Any]]]) -> int: ...
    async def commit(self) -> Any: ...


async def retrieve_page(
    client: httpx.AsyncClient,
    *,
    item_type: str = "publication",
    limit: int = 100,
    offset: int = 0,
    search_after: str | None = None,
    filters: list[list[str]] | None = None,
) -> dict[str, Any]:
    """One retrieve call; `search_after` (e.g. "[6]") replaces offset past 10k."""
    params: dict[str, Any] = {
        "item-type": item_type,
        "format": "Json",
        "limit": limit,
        "offset": offset,
    }
    if search_after:
        params["search_after"] = str(search_after)
    if filters:
        params["filter"] = json.dumps(filters, separators=(",", ":"))
    response = await client.get(BASE_URL, params=params)
    response.raise_for_status()
    return response.json()


async def sweep_type(
    client: httpx.AsyncClient,
    ingest: _SweepIngest,
    item_type: str,
    *,
    page_size: int = 100,
    sleep_s: float = 0.15,
    max_records: int | None = None,
) -> dict[str, Any]:
    """Full /retrieve sweep for one item type into landing; the caller owns
    the run (start_run/finish_run). Stops when `next_search_after` is null,
    `items` is empty/missing, or `max_records` new records are stored.
    Records without a system_metadata id are skipped, not ingested."""
    stats: dict[str, Any] = {"item_type": item_type, "pages": 0, "records": 0, "skipped": 0}
    search_after: str | None = None
    while True:
        if max_records is not None and stats["records"] >= max_records:
            return stats
        page = await retrieve_page(
            client, item_type=item_type, limit=page_size, search_after=search_after
        )
        items = page.get("items") or []
        records = []
        for item in items:
            pk = (item.get("system_metadata") or {}).get("id")
            if pk is None:
                stats["skipped"] += 1
                continue
            records.append((str(pk), item))
        # Page-bulk dedupe; truncation honors a smoke-run cap exactly (the
        # dropped tail re-lands on the next full sweep).
        if max_records is not None:
            records = records[: max_records - stats["records"]]
        if records:
            stats["records"] += await ingest.ingest_records(records)
        stats["pages"] += 1
        await ingest.commit()
        next_after = page.get("next_search_after")
        if not next_after or not items:
            return stats
        search_after = str(next_after)
        await asyncio.sleep(sleep_s)


async def harvest_all(
    session: AsyncSession,
    only: str | None = None,
    limit_records: int | None = None,
    sleep_s: float = 0.15,
) -> dict[str, Any]:
    """Sweep every (or one --only) item type, each in its own HarvestRun so
    per-type HarvestState tracks independently. Idempotent full refresh:
    reruns dedupe on content_hash. `limit_records` caps new records across
    all swept types (smoke runs)."""
    if only is not None and only not in SWEEP_TYPES:
        raise ValueError(f"unknown item type {only!r}; expected one of {SWEEP_TYPES}")
    item_types = (only,) if only else SWEEP_TYPES
    headers = {"x-api-key": get_settings().jisc_api_key}
    results: dict[str, Any] = {}
    swept = 0
    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        for item_type in item_types:
            max_records = None if limit_records is None else max(limit_records - swept, 0)
            stats = await run_harvest(
                SOURCE,
                item_type,
                "all",
                {"mode": "retrieve-sweep"},
                lambda ingest, it=item_type, cap=max_records: sweep_type(
                    client, ingest, it, sleep_s=sleep_s, max_records=cap
                ),
                session,
            )
            results[item_type] = stats
            swept += stats.get("records", 0)
            if limit_records is not None and swept >= limit_records:
                break
    return results
