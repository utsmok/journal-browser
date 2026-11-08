"""Work-source adapter for author pages: the local openalex_works store
first, the ut-metadata DSN as the opt-in accelerator.

Selection follows the author-source setting (`author_source`, default
local): local serves the author page's openalex-only merge from
journal-browser's own harvests; `utmd` restores the legacy DSN-backed
behavior where a DSN is configured. An unbuilt local store (no rows for
the institution at all) degrades to the DSN path so a fresh deployment
never flips to empty before its first openalex-works projection. (The
journal works tab no longer goes through here: it serves the works-table
population directly — services.detail_enrichment.)
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Author, Institution, OpenalexWork
from . import ut_metadata
from .authorship import attributed_to_any

logger = logging.getLogger(__name__)


def _owns_utmd(institution: Institution) -> bool:
    """True when this institution may read the ut-metadata DSN.

    The DSN is one deployment's local database (the configured default
    institution's). Any other institution serves works_stats-only instead
    of another site's works."""
    return institution.code == (get_settings().institution_code or "").strip().lower()


async def _use_local(session: AsyncSession, institution: Institution) -> bool:
    """True when the local store serves this institution: the author-source
    setting is local (default) AND the openalex_works projection has run
    for it at least once."""
    mode = (get_settings().author_source or "local").lower()
    if mode == "utmd":
        return False
    return (
        await session.scalar(
            select(1).where(OpenalexWork.institution_id == institution.id).limit(1)
        )
    ) is not None


async def openalex_only_works_for_author(
    session: AsyncSession, institution: Institution, author: Author
) -> list[dict[str, Any]] | None:
    """OpenAlex works attributed to the author that the Pure population
    does not hold; None = not available (caller serves Pure-only).

    Local store: authorships matched against the author's resolved A-ids
    (jsonb containment per id). Raw rows — the caller applies the
    institution's window/type/DOI quality gates."""
    aids = [a.lower() for a in (author.openalex_ids or []) if a]
    if not await _use_local(session, institution):
        # Same ownership rule as the journal works tab had.
        return (
            await ut_metadata.ut_openalex_only_works_for_author(aids)
            if _owns_utmd(institution)
            else None
        )
    if not aids:
        return []
    rows = (
        await session.execute(
            select(OpenalexWork).where(
                OpenalexWork.institution_id == institution.id,
                attributed_to_any(aids),
            )
        )
    ).scalars()
    return [
        {
            "title": row.title,
            "year": row.year,
            "doi": row.doi_normalized,
            "oa_status": row.oa_status,
            "work_type": row.work_type,
            "venue_name": row.venue_name,
            "issn_l": row.venue_issn_l,
        }
        for row in rows
    ]
