"""Backfill deal_journals.issn_l from the harvested issn_map.

Runs after the OpenAlex sources sweep (which indexes every variant ISSN
to its linking ISSN). Deal rows that still cannot resolve are flagged
needs_curation instead of being dropped (limitation: issn-mapping).
"""

import logging

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Deal, DealJournal
from .common import lookup_issn_l

logger = logging.getLogger(__name__)


async def backfill_deal_issn_l(session: AsyncSession) -> dict[str, int]:
    rows = (
        (await session.execute(select(DealJournal).where(DealJournal.issn_l.is_(None))))
        .scalars()
        .all()
    )
    resolved = 0
    unresolved = 0
    for row in rows:
        issn_l = await lookup_issn_l(session, row.issn)
        if issn_l:
            row.issn_l = issn_l
            row.needs_curation = False
            resolved += 1
        else:
            row.needs_curation = True
            unresolved += 1
    # Deals with no journal rows at all need curation (JCT lists are never
    # empty; scraper-only deals without a resolvable list are the gap).
    no_journals = ~exists(select(DealJournal.deal_id).where(DealJournal.deal_id == Deal.id))
    result = await session.execute(
        update(Deal)
        .where(no_journals, Deal.needs_curation.is_(False))
        .values(needs_curation=True, needs_curation_reason="no journal list resolved")
    )
    await session.commit()
    stats = {
        "resolved": resolved,
        "unresolved": unresolved,
        "empty_deals": result.rowcount or 0,
    }
    logger.info("issn backfill: %s", stats)
    return stats
