"""ROR records for partner_institutions: gap-fill and monthly refresh.

Usage: uv run python jobs/harvest_ror.py [--refresh] [--ttl-days N] [--limit N]

Default: fetch a record for every partner the table only knows from a work
payload (payload IS NULL), plus every record older than --ttl-days (30),
in ROR id order. The refresh brings status changes, relocations and type
edits in: ROR publishes a new data dump every month. --refresh re-fetches
every row instead; --limit N stops after N rows, for a first run in
several slices. ROR (https://ror.org, data CC0) serves each record at
https://api.ror.org/v2/organizations/{id}. The request names the
configured contact (settings.contact_email) in its User-Agent, which puts
it in ROR's polite pool. ROR allows 2000 requests per 5 minutes per
address; the pace below stays well under it.

A 404 marks the row not_found and leaves the payload empty; the id is
asked again once that mark is as old as the ttl (ROR registers new ids).
Idempotent; commits per chunk, so an interrupted run resumes as a rerun.
"""

import logging
from datetime import timedelta
from typing import Any, cast

import httpx
from bibliofabric.exceptions import NotFoundError
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import PartnerInstitution
from .common import paced_single_gets
from .funders import normalize_ror

logger = logging.getLogger(__name__)

ROR_API = "https://api.ror.org/v2/organizations/"
#: requests started per second (5 * 60 = 300 per 5 minutes)
ROR_MIN_INTERVAL_S = 0.2
ROR_CONCURRENCY = 5
#: rows per fetch-and-commit chunk
CHUNK = 500
#: mark for a ROR id the registry does not know (yet)
NOT_FOUND = "not_found"
#: a record older than this many days is fetched again
TTL_DAYS = 30

#: names[] types in order of preference for the display name.
_NAME_PRIORITY = ("ror_display", "label", "acronym", "alias")
#: types in order of preference for the one type a partner is grouped
#: under. ROR lists an organisation's roles in no particular order, and
#: what it is comes first: a teaching hospital that also hands out grants
#: is healthcare.
_TYPE_PRIORITY = (
    "education",
    "healthcare",
    "facility",
    "government",
    "company",
    "nonprofit",
    "archive",
    "funder",
    "other",
)
_COLUMNS = (
    "name",
    "org_type",
    "country_code",
    "city",
    "lat",
    "lng",
    "parent_ror",
    "parent_name",
    "status",
    "payload",
)


def display_name(names: list[dict[str, Any]]) -> str | None:
    """First non-empty value of the most preferred name type."""
    for kind in _NAME_PRIORITY:
        for entry in names:
            if kind in (entry.get("types") or []) and (value := (entry.get("value") or "").strip()):
                return value
    return None


def display_type(types: list[str]) -> str | None:
    """The most preferred type of a ROR record; a type outside the priority
    list ranks last, in registry order."""
    rank = {kind: i for i, kind in enumerate(_TYPE_PRIORITY)}
    ordered = sorted(types, key=lambda kind: rank.get(kind, len(rank)))
    return ordered[0] if ordered else None


def ror_row(record: dict[str, Any], ror: str) -> dict[str, Any]:
    """partner_institutions columns from one ROR v2 organization record.

    Coordinates come from the first location whose GeoNames details carry
    both; the city is the GeoNames city, or the place name for records
    without one."""
    geonames = [loc.get("geonames_details") or {} for loc in record.get("locations") or []]
    geo = next((g for g in geonames if g.get("lat") is not None and g.get("lng") is not None), {})
    parent = next(
        (r for r in record.get("relationships") or [] if (r.get("type") or "").lower() == "parent"),
        {},
    )
    types = record.get("types") or []
    return {
        "ror": ror,
        "name": display_name(record.get("names") or []),
        "org_type": display_type(types),
        "country_code": geo.get("country_code"),
        "city": geo.get("city") or geo.get("name"),
        "lat": geo.get("lat"),
        "lng": geo.get("lng"),
        "parent_ror": normalize_ror(parent.get("id")),
        "parent_name": parent.get("label"),
        "status": record.get("status"),
        "payload": record,
    }


def _get(client: httpx.AsyncClient):
    """Single-record GET for paced_single_gets; a 404 maps to None there."""

    async def fetch(ror: str) -> dict[str, Any]:
        resp = await client.get(f"{ROR_API}{ror}")
        if resp.status_code == 404:
            raise NotFoundError(f"ROR has no record {ror}")
        resp.raise_for_status()
        return resp.json()

    return fetch


async def harvest_ror(
    session: AsyncSession,
    *,
    refresh: bool = False,
    limit: int | None = None,
    ttl_days: int = TTL_DAYS,
) -> dict[str, int]:
    """Fetch ROR records for the rows without one and for the records older
    than `ttl_days`, and upsert them. A not_found mark is trusted until it
    is that old, then the id is asked for again."""
    stats = {"selected": 0, "fetched": 0, "not_found": 0, "failed": 0}
    stmt = select(PartnerInstitution.ror).order_by(PartnerInstitution.ror)
    if not refresh:
        stale = PartnerInstitution.updated_at < func.now() - timedelta(days=ttl_days)
        stmt = stmt.where(
            or_(
                and_(
                    PartnerInstitution.payload.is_(None),
                    PartnerInstitution.status.is_distinct_from(NOT_FOUND),
                ),
                stale,
            )
        )
    if limit is not None:
        stmt = stmt.limit(limit)
    todo = [ror for (ror,) in (await session.execute(stmt)).all()]
    stats["selected"] = len(todo)
    if not todo:
        return stats
    contact = get_settings().contact_email
    # ROR reads the mailto out of the User-Agent for its polite pool.
    user_agent = f"journal-browser ({contact})" if contact else "journal-browser"
    table = cast("Any", PartnerInstitution.__table__)
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": user_agent}) as client:
        for start in range(0, len(todo), CHUNK):
            chunk = todo[start : start + CHUNK]
            payloads, failed = await paced_single_gets(
                _get(client),
                chunk,
                concurrency=ROR_CONCURRENCY,
                min_interval_s=ROR_MIN_INTERVAL_S,
            )
            stats["failed"] += len(failed)
            if failed:
                logger.warning(
                    "harvest_ror: %d lookups failed, e.g. %s", len(failed), sorted(failed)[:5]
                )
            missing = [
                ror for ror, payload in payloads.items() if payload is None and ror not in failed
            ]
            fetched = [
                ror_row(payload, ror)
                for ror, payload in payloads.items()
                if payload is not None and ror not in failed
            ]
            if fetched:
                stmt = pg_insert(table).values(fetched)
                await session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["ror"],
                        set_={
                            # A ROR record without a value keeps what the
                            # work payload gave; openalex_id is never touched.
                            **{
                                col: func.coalesce(stmt.excluded[col], table.c[col])
                                for col in _COLUMNS
                                if col != "payload"
                            },
                            "payload": stmt.excluded.payload,
                            "updated_at": text("now()"),
                        },
                    )
                )
            if missing:
                await session.execute(
                    update(table)
                    .where(table.c.ror.in_(missing))
                    .values(status=NOT_FOUND, updated_at=text("now()"))
                )
            await session.commit()
            stats["fetched"] += len(fetched)
            stats["not_found"] += len(missing)
            logger.info(
                "harvest_ror: %d/%d ids done (fetched %d, not found %d)",
                min(start + CHUNK, len(todo)),
                len(todo),
                stats["fetched"],
                stats["not_found"],
            )
    logger.info("harvest_ror: %s", stats)
    return stats
