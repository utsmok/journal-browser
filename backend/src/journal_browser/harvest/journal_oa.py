"""Observe a journal's real OA color from its recent works.

OpenAlex marks many venues `is_oa` without saying which OA color applies
(DOAJ membership and APC prices cover only part of the corpus). For every
journal flagged is_oa without other evidence, sample its most recent works
and store the modal non-green Work oa_status in journals.oa_status_observed.
Recent works of one venue share a color; green is ignored because it
reflects repository copies, not the venue's model (owner decision
2026-10-27). Fills NULLs only, so reruns pick up new journals only.
"""

import asyncio
import logging
from collections import Counter
from typing import Any

from aletheca import AlethecaClient
from sqlalchemy import and_, func, or_, select, type_coerce, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Journal
from .common import run_harvest

logger = logging.getLogger(__name__)

SOURCE = "openalex"
ENTITY_TYPE = "works"
FILTER_SET = "oa-color-sample"
SAMPLE_N = 20
#: Concurrent work-list requests; the keyed OpenAlex pool tolerates this
#: comfortably and ~50k journals need the throughput.
CONCURRENCY = 4
#: Deterministic tie-break order for the modal color.
_COLOR_ORDER = ("gold", "diamond", "hybrid", "bronze", "closed", "green")
#: Statuses that say something about the venue itself; green reflects
#: repository copies, not the venue's model.
_AT_VENUE = ("gold", "diamond", "hybrid", "bronze", "closed")

# Only OpenAlex-OA venues without other evidence need sampling; priced or
# DOAJ journals already classify without it.
_TARGETS = and_(
    Journal.is_oa.is_(True),
    or_(Journal.is_in_doaj.is_(False), Journal.is_in_doaj.is_(None)),
    or_(
        Journal.apc_prices.is_(None),
        func.jsonb_array_length(type_coerce(Journal.apc_prices, JSONB)) == 0,
    ),
    Journal.latest_apc_euro.is_(None),
)


def observed_color(statuses: list[str | None]) -> str | None:
    """Modal non-green oa_status of the sampled works.

    All green / empty samples store 'green' (= venue color unknown); ties
    and unexpected values resolve deterministically via _COLOR_ORDER.
    """
    counted = Counter(s for s in statuses if s)
    if not counted:
        return None
    known = [s for s in counted if s in _COLOR_ORDER]
    if not known:
        return "green"
    return max(known, key=lambda s: (counted[s], -_COLOR_ORDER.index(s)))


def _source_filter(issn_l: str, openalex_id: str | None) -> str | None:
    if openalex_id:
        return f"primary_location.source.id:{openalex_id.rsplit('/', 1)[-1]}"
    return f"primary_location.source.issn:{issn_l}" if issn_l else None


async def _sample(client: Any, row: Any) -> tuple[str, str | None]:
    flt = _source_filter(row.issn_l, row.openalex_id)
    if flt is None:
        return row.issn_l, None
    try:
        resp = await client.request(
            "GET",
            "works",
            params={
                "filter": flt,
                "sort": "publication_date:desc",
                "per-page": SAMPLE_N,
                "select": "open_access",
            },
            raw=True,
        )
        results = ((resp.json() if resp is not None else None) or {}).get("results") or []
    except Exception as exc:  # noqa: BLE001 - one bad journal must not kill the sweep
        logger.warning("oa sample %s failed: %s", row.issn_l, exc)
        return row.issn_l, None
    statuses = [(w.get("open_access") or {}).get("oa_status") for w in results]
    return row.issn_l, observed_color(statuses)


async def harvest_oa_statuses(
    session: AsyncSession, limit: int | None = None
) -> dict[str, Any]:
    """Sample recent works for every OA-flagged journal missing a color."""
    rows = (
        await session.execute(
            select(Journal.issn_l, Journal.openalex_id)
            .where(_TARGETS, Journal.oa_status_observed.is_(None))
            .order_by(Journal.issn_l)
            .limit(limit)
        )
    ).all()

    async def body(ingest: Any) -> dict[str, Any]:
        client_kwargs: dict[str, Any] = {}
        if api_key := get_settings().openalex_api_key:
            client_kwargs["api_key"] = api_key
        sampled = colored = 0
        async with AlethecaClient(**client_kwargs) as client:
            for chunk in (rows[i : i + CONCURRENCY] for i in range(0, len(rows), CONCURRENCY)):
                for issn_l, color in await asyncio.gather(
                    *(_sample(client, row) for row in chunk)
                ):
                    sampled += 1
                    if color:
                        colored += 1
                        await session.execute(
                            update(Journal)
                            .where(Journal.issn_l == issn_l)
                            .values(oa_status_observed=color)
                        )
                if sampled % (CONCURRENCY * 100) < CONCURRENCY:
                    await session.commit()  # bounded redo on failure
        await session.commit()
        return {"sampled": sampled, "colored": colored}

    return await run_harvest(
        SOURCE, ENTITY_TYPE, FILTER_SET, {"sample_n": SAMPLE_N}, body, session
    )
