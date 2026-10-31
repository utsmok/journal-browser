"""OpenAlex works store: the normalized projection over the institution's
harvested OpenAlex works.

The raw payloads already land verbatim in source_records — the bootstrap
`stats` sweep (harvest/institution_stats.py, entity_type works_stats,
institutions.id filter, publication-windowed) stores every work with its
authorships — plus the budget-capped per-author enrichment sweep
(harvest/author_ids.py, filter_set author-sweep). This module projects the
latest payload per W-id into openalex_works: one local table that powers
the remaining DSN features standalone (authorship edges for the identity
cascade, the openalex-only author merge, and the journal-detail works
tab). Full-replace per institution: the projection is deterministic and
re-runs fold in new sweep data automatically.
"""

import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import work_type_excluded
from ..models import HarvestRun, HarvestState, Institution, OpenalexWork, SourceRecord
from .common import canonical_oa_status, normalize_doi

logger = logging.getLogger(__name__)

SOURCE = "openalex"
ENTITY_TYPE = "works_stats"
#: harvest_runs.filter_set prefix of the per-author enrichment sweep
AUTHOR_SWEEP_PREFIX = "author-sweep"

INSERT_CHUNK = 5000


def _w_id(openalex_id: Any) -> str | None:
    """'https://openalex.org/W123' -> 'W123'; None for unusable ids."""
    if not isinstance(openalex_id, str) or not openalex_id:
        return None
    tail = openalex_id.rsplit("/", 1)[-1]
    return tail or None


def _authorships(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Compact authorships: [{a: bare A-id, n: display name, o: bare orcid}].

    Entries without any of the three carry no evidence and drop out; the
    author field is the model-dump dict (or an already-compact entry when
    re-projecting a folded row)."""
    out: list[dict[str, Any]] = []
    for sh in payload.get("authorships") or []:
        a = sh.get("author") if isinstance(sh, dict) else None
        if not isinstance(a, dict):
            continue
        aid = _w_id(a.get("id"))
        name = (a.get("display_name") or "").strip() or None
        orcid = a.get("orcid") or None
        if orcid:
            orcid = str(orcid).rsplit("/", 1)[-1].lower()
        if not aid and not name and not orcid:
            continue
        out.append({"a": aid, "n": name, "o": orcid})
    return out


def work_row(payload: dict[str, Any], issn_by_source: dict[str, str]) -> dict[str, Any] | None:
    """One openalex_works row from a stored works payload; None when the
    record has no usable W-id or is a preprint/book (never journal output)."""
    w_id = _w_id(payload.get("id"))
    if w_id is None or work_type_excluded(payload.get("type")):
        return None
    source_id = _w_id(((payload.get("primary_location") or {}).get("source") or {}).get("id"))
    venue_issn_l = issn_by_source.get(source_id or "")
    oa_status = canonical_oa_status((payload.get("open_access") or {}).get("oa_status"))
    fwci = payload.get("fwci")
    return {
        "w_id": w_id,
        "doi_normalized": normalize_doi(payload.get("doi")),
        "title": (payload.get("display_name") or "").strip() or None,
        "year": payload.get("publication_year"),
        "work_type": payload.get("type"),
        "oa_status": oa_status if oa_status else None,
        "venue_issn_l": venue_issn_l,
        "venue_name": (
            ((payload.get("primary_location") or {}).get("source") or {}).get("display_name")
            or None
        ),
        "authorships": _authorships(payload),
        "cited_by_count": payload.get("cited_by_count") or 0,
        "fwci": float(fwci) if isinstance(fwci, (int, float)) else None,
        "is_retracted": bool(payload.get("is_retracted")),
        "source": "works_stats",
    }


async def _issn_map(session: AsyncSession) -> dict[str, str]:
    """OpenAlex source id -> issn_l (journals.openalex_id, per-source key)."""
    from ..models import Journal

    rows = await session.execute(select(Journal.openalex_id, Journal.issn_l))
    return {_w_id(s): issn_l for s, issn_l in rows.all() if s and issn_l}


async def rebuild_openalex_works(session: AsyncSession, institution: Institution) -> dict[str, Any]:
    """Full-replace the institution's openalex_works from the latest stored
    works_stats payload per W-id (scoped to the institution's runs)."""
    # filter_set rides HarvestState (keyed by last_run_id), not the run row.
    stmt = (
        select(SourceRecord.source_pk, SourceRecord.payload, HarvestState.filter_set)
        .join(HarvestRun, HarvestRun.id == SourceRecord.harvest_run_id)
        .outerjoin(HarvestState, HarvestState.last_run_id == HarvestRun.id)
        .where(
            SourceRecord.source == SOURCE,
            SourceRecord.entity_type == ENTITY_TYPE,
            HarvestRun.institution_id == institution.id,
        )
        .order_by(
            SourceRecord.source_pk,
            SourceRecord.harvested_at.desc(),
            SourceRecord.id.desc(),
        )
    )
    latest: dict[str, tuple[dict[str, Any], str]] = {}
    for pk, payload, filter_set in (await session.execute(stmt)).all():
        latest.setdefault(pk, (payload, filter_set or ""))
    issn_by_source = await _issn_map(session)
    rows: dict[str, dict[str, Any]] = {}
    parse_failures = 0
    excluded_types = 0
    for _source_pk, (payload, filter_set) in latest.items():
        row = work_row(payload, issn_by_source)
        if row is None:
            # An excluded type (preprint/book, never journal output) is by
            # design, not a parse failure; only the rest are anomalies.
            if work_type_excluded(payload.get("type")):
                excluded_types += 1
            else:
                parse_failures += 1
            continue
        if filter_set.startswith(AUTHOR_SWEEP_PREFIX):
            row["source"] = AUTHOR_SWEEP_PREFIX
        # One publication under two W-ids (merged profiles): first wins,
        # which is the most-mentioned-at-first-sweep id — deterministic.
        rows.setdefault(row["w_id"], row)
    await session.execute(delete(OpenalexWork).where(OpenalexWork.institution_id == institution.id))
    values = list(rows.values())
    for start in range(0, len(values), INSERT_CHUNK):
        await session.execute(
            OpenalexWork.__table__.insert(),
            [
                {**row, "institution_id": institution.id}
                for row in values[start : start + INSERT_CHUNK]
            ],
        )
    stats = {
        "works": len(values),
        "parse_failures": parse_failures,
        "excluded_types": excluded_types,
        "author_sweep_rows": sum(1 for r in values if r["source"] == AUTHOR_SWEEP_PREFIX),
    }
    logger.info("openalex_works[%s]: %s", institution.code, stats)
    return stats
