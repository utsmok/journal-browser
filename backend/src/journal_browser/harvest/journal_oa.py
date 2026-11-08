"""Observe a journal's real OA color from locally held works.

OpenAlex marks many venues `is_oa` without saying which OA color applies
(DOAJ membership and APC prices cover only part of the corpus). Instead
of sampling works per venue over the API, aggregate the stored oa_status
of works already linked to each journal and store the modal non-green
status in journals.oa_status_observed. Green is ignored because it
reflects repository copies, not the venue's model (owner decision
2026-10-27). Fills NULLs only, so reruns pick up new journals only and
cost zero API calls.
"""

import logging
from collections import Counter
from typing import Any

from sqlalchemy import bindparam, func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Journal, Work
from .common import run_harvest

logger = logging.getLogger(__name__)

SOURCE = "openalex"
ENTITY_TYPE = "works"
FILTER_SET = "oa-color-local"
#: Deterministic tie-break order for the modal color.
_COLOR_ORDER = ("gold", "diamond", "hybrid", "bronze", "closed", "green")
#: Statuses that say something about the venue itself; green reflects
#: repository copies, not the venue's model.
_AT_VENUE = ("gold", "diamond", "hybrid", "bronze", "closed")


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


async def derive_oa_colors_local(session: AsyncSession) -> dict[str, Any]:
    """Fill journals.oa_status_observed from stored works; no API calls.

    Aggregates oa_status over every stored work linked via
    works.journal_issn_l and applies the same modal-non-green rule the
    per-venue API sampler used. Fills NULLs only.
    """

    async def body(ingest: Any) -> dict[str, int]:
        rows = (
            await session.execute(
                select(Journal.issn_l, func.array_agg(Work.oa_status))
                .select_from(Work)
                .join(Journal, Journal.issn_l == Work.journal_issn_l)
                .where(
                    Work.oa_status.is_not(None),
                    Work.journal_issn_l.is_not(None),
                    Journal.oa_status_observed.is_(None),
                )
                .group_by(Journal.issn_l)
            )
        ).all()
        updates = [
            {"b_issn_l": issn_l, "b_color": color}
            for issn_l, statuses in rows
            if (color := observed_color(list(statuses))) is not None
        ]
        if updates:
            journals_t = Journal.__table__
            await session.execute(
                sa_update(journals_t)
                .values(oa_status_observed=bindparam("b_color"))
                .where(
                    journals_t.c.issn_l == bindparam("b_issn_l"),
                    journals_t.c.oa_status_observed.is_(None),
                ),
                updates,
            )
        await session.commit()
        return {"journals_with_works": len(rows), "colored": len(updates)}

    return await run_harvest(SOURCE, ENTITY_TYPE, FILTER_SET, {"via": "local_works"}, body, session)
