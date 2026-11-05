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

from sqlalchemy import bindparam, or_, select, text, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..harvest.common import oa_openness_desc
from ..harvest.org_closure import load_org_tree
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


async def ut_affiliated_dois(
    session: AsyncSession, institution: Institution, issn_l: str
) -> set[str]:
    """DOIs of the venue's works with at least one UT-affiliated author: a
    pure author edge whose affiliations close on the institution root
    (work-level arm), or a confirmed roster author on the work (profile
    arm). Pure is the affiliation ground truth — OpenAlex attribution and
    author-profile sweeps leak foreign works into the venue tab."""
    tree = await load_org_tree(session, institution)
    stmt = text(
        """
        WITH venue_dois AS (
            SELECT DISTINCT o.doi_normalized AS doi
            FROM openalex_works o
            WHERE o.institution_id = :iid
              AND o.venue_issn_l = :issn
              AND o.doi_normalized IS NOT NULL
        )
        SELECT DISTINCT w.doi_normalized
        FROM works w
        JOIN venue_dois v ON v.doi = w.doi_normalized
        WHERE w.institution_id = :iid
          AND (
              EXISTS (
                  SELECT 1
                  FROM work_pure_authors wpa
                  JOIN authors a ON a.institution_id = wpa.institution_id
                       AND a.pure_uuid = wpa.person_uuid AND a.confirmed
                  WHERE wpa.institution_id = w.institution_id
                    AND wpa.work_pure_uuid = w.pure_uuid
              )
              OR EXISTS (
                  SELECT 1
                  FROM work_pure_authors wpa,
                       jsonb_array_elements_text(wpa.affiliations) aff
                  WHERE wpa.institution_id = w.institution_id
                    AND wpa.work_pure_uuid = w.pure_uuid
                    AND aff IN :connected
              )
          )
        """
    ).bindparams(bindparam("connected", expanding=True))
    result = await session.execute(
        stmt,
        {"iid": institution.id, "issn": issn_l, "connected": sorted(tree.connected) or [""]},
    )
    return {row[0] for row in result}


async def works_for_journal(
    session: AsyncSession, institution: Institution, issn_l: str
) -> list[dict[str, Any]] | None:
    """Canonical works for the journal; None = serve works_stats-only.

    Local store rows win (deduped by DOI, most open record kept —
    owner decision 2026-11-05, ties keep the lowest W-id; merged
    profiles can carry one publication under two W-ids); the DSN path
    takes over only when the store has nothing for this institution or
    the setting opts back into it. Rows serve only when a pure-side
    author shows UT affiliation (owner decision 2026-11-05: OpenAlex
    attribution and author-profile sweeps leak foreign works, and
    author-less records such as edited volumes are not works of ours)."""
    if await _use_local(session, institution):
        ut_dois = await ut_affiliated_dois(session, institution, issn_l)
        rows = (
            await session.execute(
                select(OpenalexWork)
                .where(
                    OpenalexWork.institution_id == institution.id,
                    OpenalexWork.venue_issn_l == issn_l,
                )
                .order_by(oa_openness_desc(OpenalexWork.oa_status), OpenalexWork.w_id)
            )
        ).scalars()
        by_doi: dict[str, dict[str, Any]] = {}
        out: list[dict[str, Any]] = []
        for row in rows:
            item = _journal_row(row)
            if not item["doi"] or item["doi"] not in ut_dois:
                continue
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
