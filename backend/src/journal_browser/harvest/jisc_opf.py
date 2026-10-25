"""Scaffold: Jisc Open Policy Finder harvester (green OA policies).

API: https://api.openpolicyfinder.jisc.ac.uk/retrieve, `x-api-key`
header, limit/offset paging with search_after beyond 10k records.
BLOCKED per docs/decisions.md: no API key yet, scaffold behind
`JB_ENABLE_JISC` (default OFF). This module makes ZERO calls unless the
flag is set AND a key is present.
"""

import logging
from typing import Any

import httpx

from ..config import get_settings
from ..ingest import IngestSession

logger = logging.getLogger(__name__)

SOURCE = "jisc_opf"
ENTITY_TYPE = "policies"
BASE_URL = "https://api.openpolicyfinder.jisc.ac.uk/retrieve"


def assert_enabled() -> tuple[bool, str]:
    settings = get_settings()
    if not settings.enable_jisc:
        return False, "JB_ENABLE_JISC=false; integration starts when the key arrives"
    if not settings.jisc_api_key:
        return False, "JB_JISC_API_KEY is empty"
    return True, ""


async def retrieve_page(
    client: httpx.AsyncClient,
    *,
    item_type: str = "publication",
    limit: int = 100,
    offset: int = 0,
    search_after: str | None = None,
    filters: list[list[str]] | None = None,
) -> dict[str, Any]:
    """One retrieve call; `search_after` replaces offset beyond 10k records."""
    params: dict[str, Any] = {"type": item_type, "limit": limit, "offset": offset}
    if search_after:
        params["search_after"] = search_after
    if filters:
        params["filter"] = str(filters)
    response = await client.get(BASE_URL, params=params)
    response.raise_for_status()
    return response.json()


async def harvest_policies(ingest: IngestSession, limit: int | None = None) -> dict:
    """Paged full harvest; raw JSON lands per record before normalization.
    Caller owns ingest.start_run()/finish_run()."""
    enabled, reason = assert_enabled()
    if not enabled:
        logger.info("Jisc harvester skipped: %s", reason)
        return {"status": "skipped", "reason": reason}

    headers = {"x-api-key": get_settings().jisc_api_key}
    stats: dict[str, Any] = {"records": 0}
    search_after: str | None = None
    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        while True:
            page = await retrieve_page(client, search_after=search_after)
            for record in page.get("results", []):
                pk = str(((record.get("system_metadata") or {}).get("id")) or stats["records"] + 1)
                await ingest.ingest_record(pk, record)
                stats["records"] += 1
                if limit is not None and stats["records"] >= limit:
                    await ingest.commit()
                    return stats
            search_after = page.get("search_after")
            if not search_after or not page.get("results"):
                break
            await ingest.commit()
    return stats
