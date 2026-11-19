"""Backfill usage_events.country from the DB-IP Country Lite database.

Country lookups are local: the monthly CC BY 4.0 country mmdb
(https://download.db-ip.com/free/dbip-country-lite-YYYY-MM.mmdb.gz) is
downloaded once into landing/dbip/ through the landing store, and every
unresolved usage-event IP is read from the local file. Nothing about
the visitors ever leaves the host; there is no request budget, so no
batch pacing is needed. Country data by DB-IP (db-ip.com), DB-IP
Country Lite (CC BY 4.0).
"""

import argparse
import asyncio
import gzip
import ipaddress
import json
from datetime import UTC, datetime
from pathlib import Path

import maxminddb
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import download_to_landing
from journal_browser.ingest import IngestSession
from journal_browser.logging_setup import configure_logging
from journal_browser.models import UsageEvent

SOURCE = "dbip"
#: DB-IP publishes the lite database as one file per month; the job
#: fetches the current month's file and re-downloads when the month
#: rolls over.
URL_TEMPLATE = "https://download.dbip.com/free/dbip-country-lite-{key}.mmdb.gz"


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


def mmdb_path(landing_dir: Path, key: str) -> tuple[Path, Path, str]:
    """(archive path, decompressed path, download url) for one month."""
    base = landing_dir / SOURCE
    url = URL_TEMPLATE.format(key=key)
    return base / f"dbip-country-lite-{key}.mmdb.gz", base / f"dbip-country-lite-{key}.mmdb", url


async def ensure_mmdb(session) -> Path:
    """Current month's decompressed mmdb in the landing dir, downloading
    and decompressing it when missing. The .gz stays as the verbatim
    landing copy; the decompressed file is what the reader opens."""
    key = datetime.now(UTC).strftime("%Y-%m")
    gz_path, db_path, url = mmdb_path(Path(get_settings().landing_dir), key)
    if db_path.is_file():
        return db_path
    gz_path.parent.mkdir(parents=True, exist_ok=True)
    ingest = IngestSession(session)
    data, _ = await download_to_landing(session, ingest, SOURCE, "country-lite", url, ".mmdb.gz")
    db_path.write_bytes(gzip.decompress(data))
    await session.commit()
    return db_path


def lookup_country(reader: maxminddb.Reader, ip: str) -> str | None:
    """ISO country code for one IP, or None when the database has none."""
    record = reader.get(ip)
    if not isinstance(record, dict):
        return None
    country = record.get("country")
    if isinstance(country, dict):
        code = country.get("iso_code")
        return code if isinstance(code, str) else None
    return None


async def enrich(session, reader: maxminddb.Reader, *, limit: int | None = None) -> dict[str, int]:
    stats = {"resolved": 0, "skipped_private": 0, "failed": 0}
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
    if limit is not None:
        trackable = trackable[:limit]
    for ip in trackable:
        country = lookup_country(reader, ip)
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
    configure_logging()
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        db_path = await ensure_mmdb(session)
        with maxminddb.open_database(str(db_path)) as reader:
            stats = await enrich(session, reader, limit=limit)
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="max IPs to process")
    asyncio.run(main(parser.parse_args().limit))
