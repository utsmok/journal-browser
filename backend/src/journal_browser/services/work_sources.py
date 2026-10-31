"""Work-source adapter: the local openalex_works store first, the
ut-metadata DSN as the opt-in accelerator.

Selection follows the author-source setting (`author_source`, default
local): local serves the journal works tab and the author page's
openalex-only merge from journal-browser's own harvests; `utmd` restores
the legacy DSN-backed behavior where a DSN is configured. An unbuilt
local store (no rows for the institution at all) degrades to the DSN
path so a fresh deployment never flips to empty before its first
openalex-works projection.
"""

import logging
from typing import Any

from sqlalchemy import or_, select, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Author, Institution, OpenalexWork
from . import ut_metadata

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


def _journal_row(row: OpenalexWork) -> dict[str, Any]:
    """merge_work_lists-shaped canonical row from a store row."""
    return {
        "id": row.w_id,
        "doi": row.doi_normalized,
        "title": row.title,
        "year": row.year,
        "work_type": row.work_type,
        "oa_status": row.oa_status,
        "cited_by_count": row.cited_by_count or 0,
        "is_retracted": row.is_retracted,
    }


async def works_for_journal(
    session: AsyncSession, institution: Institution, issn_l: str
) -> list[dict[str, Any]] | None:
    """Canonical works for the journal; None = serve works_stats-only.

    Local store rows win (deduped by DOI, lowest W-id kept — merged
    profiles can carry one publication under two W-ids); the DSN path
    takes over only when the store has nothing for this institution or
    the setting opts back into it."""
    if await _use_local(session, institution):
        rows = (
            await session.execute(
                select(OpenalexWork)
                .where(
                    OpenalexWork.institution_id == institution.id,
                    OpenalexWork.venue_issn_l == issn_l,
                )
                .order_by(OpenalexWork.w_id)
            )
        ).scalars()
        by_doi: dict[str, dict[str, Any]] = {}
        out: list[dict[str, Any]] = []
        for row in rows:
            item = _journal_row(row)
            if item["doi"]:
                if item["doi"] in by_doi:
                    continue
                by_doi[item["doi"]] = item
            out.append(item)
        return out
    # Foreign institutions must not read another deployment's works.
    return await ut_metadata.ut_works_for_journal(issn_l) if _owns_utmd(institution) else None


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
        # Same ownership rule as works_for_journal.
        return (
            await ut_metadata.ut_openalex_only_works_for_author(aids)
            if _owns_utmd(institution)
            else None
        )
    if not aids:
        return []
    conditions = [
        OpenalexWork.authorships.op("@>")(type_coerce([{"a": aid}], JSONB)) for aid in aids
    ]
    rows = (
        await session.execute(
            select(OpenalexWork).where(
                OpenalexWork.institution_id == institution.id,
                or_(*conditions),
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
