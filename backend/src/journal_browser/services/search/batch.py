"""Explicit ISSN-L lookups for a saved journal list (the client shortlist).

Rows come from the browse list's own query, so deal coverage, OA type,
works, quartile and APC display match what the browse table shows for the
same institution and year range. The active/vouched eligibility toggles do
not apply: readers saved these journals and expect to see them again.
Covering deal names come from the live deal register under the same
participation and scope rules as the journal detail endpoint.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Deal, DealInstitution, DealJournal, Journal, Publisher
from ..deal_coverage import dj_scope
from .items import rename_twoyr
from .query import attach_apc_display, base_query


async def _attach_deals(
    session: AsyncSession, institution_id: int, items: list[dict[str, Any]]
) -> None:
    """Name the current deals covering each item for this institution."""
    rows = (
        await session.execute(
            select(
                DealJournal.issn_l,
                Deal.id,
                Publisher.name,
                Deal.duration_text,
            )
            .select_from(DealJournal)
            .join(Deal, Deal.id == DealJournal.deal_id)
            # Relation first: dj_scope reads journal_override from it.
            .join(
                DealInstitution,
                (DealInstitution.deal_id == DealJournal.deal_id)
                & (DealInstitution.institution_id == institution_id),
            )
            .outerjoin(Publisher, Publisher.id == Deal.publisher_id)
            .where(
                DealJournal.issn_l.in_([i["issn_l"] for i in items]),
                dj_scope(institution_id),
                DealJournal.excluded.is_not(True),
                Deal.status == "current",
            )
            .order_by(Publisher.name.nulls_last(), Deal.id)
        )
    ).all()
    by_issn: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, int]] = set()
    for issn_l, deal_id, publisher_name, duration_text in rows:
        if issn_l is None or (issn_l, deal_id) in seen:
            continue  # a NULL issn_l never matches; multi-ISSN deals appear once
        seen.add((issn_l, deal_id))
        deals = by_issn.setdefault(issn_l, [])
        deals.append(
            {
                "id": deal_id,
                "publisher_name": publisher_name,
                "duration_text": duration_text,
            }
        )
    for item in items:
        item["deals"] = by_issn.get(item["issn_l"], [])


async def journals_by_issn(
    session: AsyncSession,
    *,
    institution_id: int,
    issn_ls: list[str],
    year_from: int | None = None,
    year_to: int | None = None,
) -> list[dict[str, Any]]:
    """Rows for ``issn_ls`` in request order. An ISSN-L outside the
    institution's browsable corpus is absent from the result; the caller
    reports it as missing."""
    if not issn_ls:
        return []
    query = base_query(institution_id=institution_id, year_from=year_from, year_to=year_to).where(
        Journal.issn_l.in_(issn_ls)
    )
    found = {row.issn_l: dict(row._mapping) for row in (await session.execute(query)).all()}
    items = [rename_twoyr(found[issn_l]) for issn_l in issn_ls if issn_l in found]
    if not items:
        return []
    await attach_apc_display(session, items)
    await _attach_deals(session, institution_id, items)
    return items
