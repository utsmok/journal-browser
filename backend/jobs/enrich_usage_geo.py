"""Backfill usage_events.country from ip-api.com (free batch endpoint).

Usage: uv run python jobs/enrich_usage_geo.py [--limit N]

Batches of 100 unresolved IPs -> POST https://ip-api.com/batch; private,
loopback, and reserved addresses are skipped. The free tier allows 15
requests/minute, so batches are spaced 4.5 s apart.
"""

import argparse
import asyncio
import ipaddress
import json
from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.models import UsageEvent

BATCH_SIZE = 100
BATCH_URL = "https://ip-api.com/batch"
BATCH_FIELDS = "status,countryCode,query"
BATCH_SPACING_S = 4.5  # free tier: 15 req/min

# batch of IPs -> {ip: countryCode or None}; None marks a failed lookup.
Fetcher = Callable[[list[str]], Awaitable[dict[str, str | None]]]


def is_trackable(ip: str) -> bool:
    """False for private/loopback/reserved/link-local addresses (and junk)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_reserved
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
    )


def plan_batches(ips: list[str]) -> list[list[str]]:
    return [ips[i : i + BATCH_SIZE] for i in range(0, len(ips), BATCH_SIZE)]


async def fetch_countries(client: httpx.AsyncClient, batch: list[str]) -> dict[str, str | None]:
    """One POST /batch -> {ip: countryCode or None}; None marks a failed lookup."""
    resp = await client.post(BATCH_URL, params={"fields": BATCH_FIELDS}, json=batch)
    resp.raise_for_status()
    return {
        row["query"]: row.get("countryCode") if row.get("status") == "success" else None
        for row in resp.json()
    }


async def enrich(
    session,
    *,
    limit: int | None = None,
    sleep: float = BATCH_SPACING_S,
    fetch: Fetcher,
) -> dict[str, int]:
    stats = {"resolved": 0, "batches": 0, "skipped_private": 0, "failed": 0}
    ips = [
        str(ip)
        for (ip,) in (
            await session.execute(
                select(UsageEvent.ip)
                .where(UsageEvent.country.is_(None), UsageEvent.ip.is_not(None))
                .distinct()
            )
        ).all()
        if ip is not None
    ]
    trackable = [ip for ip in ips if is_trackable(ip)]
    stats["skipped_private"] = len(ips) - len(trackable)

    batches = plan_batches(trackable)
    if limit is not None:
        batches = batches[:limit]
    for i, batch in enumerate(batches):
        if i:
            await asyncio.sleep(sleep)
        stats["batches"] += 1
        for ip, country in (await fetch(batch)).items():
            if country is None:
                stats["failed"] += 1
                continue
            await session.execute(
                update(UsageEvent)
                .where(UsageEvent.ip == ip, UsageEvent.country.is_(None))
                .values(country=country)
            )
            stats["resolved"] += 1
        await session.commit()
    return stats


async def main(limit: int | None = None) -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session, httpx.AsyncClient() as client:
        stats = await enrich(session, limit=limit, fetch=lambda b: fetch_countries(client, b))
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="max batches to process")
    asyncio.run(main(parser.parse_args().limit))
