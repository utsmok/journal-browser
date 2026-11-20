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
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import work_type_excluded
from ..models import (
    HarvestRun,
    HarvestState,
    Institution,
    Journal,
    OpenalexWork,
    OpenalexWorkAuthor,
    SourceRecord,
    Work,
)
from .common import canonical_oa_status, normalize_doi, oa_openness_desc, oa_openness_rank

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


def _parent_works(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Compact parent works: [{id: bare W-id, name: display name, rel:
    relationship}] — OpenAlex work parts (Graph v12, 2026-11-15); payloads
    harvested before it carry none. Ids may be full URLs; all parents are
    kept, capped at 10."""
    out: list[dict[str, Any]] = []
    for pw in (payload.get("parent_works") or [])[:10]:
        if not isinstance(pw, dict):
            continue
        out.append(
            {
                "id": _w_id(pw.get("id")),
                "name": (pw.get("display_name") or "").strip() or None,
                "rel": pw.get("relationship"),
            }
        )
    return out


def raw_export_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """CSV-export cells carried by openalex_works columns: publication
    date, OA urls and distinct institution RORs from the raw works_stats
    payload; None/empty without the values (mirrors the payload shape the
    CSV export used to read per row)."""
    best = payload.get("best_oa_location") or {}
    primary = payload.get("primary_location") or {}
    rors = sorted(
        {
            ror
            for entry in payload.get("authorships") or []
            for inst in entry.get("institutions") or []
            if (ror := inst.get("ror"))
        }
    )
    return {
        "publication_date": payload.get("publication_date"),
        "pdf_url": best.get("pdf_url") or primary.get("pdf_url"),
        "landing_page_url": primary.get("landing_page_url") or best.get("landing_page_url"),
        "institution_rors": ";".join(rors),
    }


def work_row(payload: dict[str, Any], issn_by_source: dict[str, str]) -> dict[str, Any] | None:
    """One openalex_works row from a stored works payload; None when the
    record has no usable W-id or is of an excluded type (never app
    output)."""
    w_id = _w_id(payload.get("id"))
    if w_id is None or work_type_excluded(payload.get("type")):
        return None
    source = (payload.get("primary_location") or {}).get("source") or {}
    venue_issn_l = issn_by_source.get(_w_id(source.get("id")) or "")
    oa_status = canonical_oa_status((payload.get("open_access") or {}).get("oa_status"))
    fwci = payload.get("fwci")
    authorships = _authorships(payload)
    parents = _parent_works(payload)
    return {
        "w_id": w_id,
        "doi_normalized": normalize_doi(payload.get("doi")),
        "title": (payload.get("display_name") or "").strip() or None,
        "year": payload.get("publication_year"),
        "work_type": payload.get("type"),
        "oa_status": oa_status if oa_status else None,
        "venue_issn_l": venue_issn_l,
        "language": payload.get("language"),
        "venue_name": source.get("display_name") or None,
        "source_type": source.get("type") or None,
        "authorships": authorships,
        "parent_works": parents,
        "is_part": bool(parents),
        "cited_by_count": payload.get("cited_by_count") or 0,
        "fwci": float(fwci) if isinstance(fwci, (int, float)) else None,
        "is_retracted": bool(payload.get("is_retracted")),
        "source": "works_stats",
        **raw_export_fields(payload),
    }


async def _issn_map(session: AsyncSession) -> dict[str, str]:
    """OpenAlex source id -> issn_l (journals.openalex_id, per-source key)."""
    from ..models import Journal

    rows = await session.execute(select(Journal.openalex_id, Journal.issn_l))
    return {_w_id(s): issn_l for s, issn_l in rows.all() if s and issn_l}


async def rebuild_openalex_works(session: AsyncSession, institution: Institution) -> dict[str, Any]:
    """Full-replace the institution's openalex_works from the latest stored
    works_stats payload per W-id (scoped to the institution's runs).
    Part-of facts survive: payload-carried parents mark the row checked,
    silent payloads inherit prior backfill facts."""
    # filter_set rides HarvestState (keyed by last_run_id), not the run row.
    # DISTINCT ON keeps only each W-id's newest payload server-side and the
    # result streams in partitions: materialising every payload at once
    # (hundreds of MB of decoded JSON) pushed the live author-ids step past
    # the host's memory during the rebuild phase.
    stmt = (
        select(
            SourceRecord.source_pk,
            SourceRecord.payload,
            func.coalesce(HarvestState.filter_set, ""),
            func.row_number()
            .over(
                partition_by=SourceRecord.source_pk,
                order_by=[SourceRecord.harvested_at.desc(), SourceRecord.id.desc()],
            )
            .label("rn"),
        )
        .join(HarvestRun, HarvestRun.id == SourceRecord.harvest_run_id)
        .outerjoin(HarvestState, HarvestState.last_run_id == HarvestRun.id)
        .where(
            SourceRecord.source == SOURCE,
            SourceRecord.entity_type == ENTITY_TYPE,
            HarvestRun.institution_id == institution.id,
        )
    )
    issn_by_source = await _issn_map(session)
    rows: dict[str, dict[str, Any]] = {}
    parse_failures = 0
    excluded_types = 0
    result = await session.stream(stmt.execution_options(stream_results=True, max_row_buffer=200))
    async for partition in result.partitions(200):
        for _source_pk, payload, filter_set, rn in partition:
            if rn != 1:
                continue
            filter_set = filter_set or ""
            row = work_row(payload, issn_by_source)
            if row is None:
                # An excluded type (preprint/book, dataset, peer review, ...)
                # is by design, not a parse failure; only the rest are
                # anomalies.
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
    # Part-of facts survive the full replace: payloads harvested before
    # OpenAlex's 2026-11 part-of release carry no parent_works, so a plain
    # rebuild would flip is_part back to false and re-queue every row for
    # the per-DOI backfill (jobs/backfill_parts.py). A payload that DOES
    # name parents wins (newer knowledge from OpenAlex itself) and counts
    # as checked; a silent payload inherits the stored facts.
    prior_parts = {
        w_id: (parents, is_part, checked)
        for w_id, parents, is_part, checked in (
            await session.execute(
                select(
                    OpenalexWork.w_id,
                    OpenalexWork.parent_works,
                    OpenalexWork.is_part,
                    OpenalexWork.parts_checked_at,
                ).where(OpenalexWork.institution_id == institution.id)
            )
        ).all()
    }
    checked_now = datetime.now(UTC)
    for row in rows.values():
        if row["parent_works"]:
            row["parts_checked_at"] = checked_now
        elif prior := prior_parts.get(row["w_id"]):
            row["parent_works"], row["is_part"], row["parts_checked_at"] = prior
        else:
            # New row, silent payload: unchecked. The key must exist on
            # every row — chunked executemany compiles the INSERT from
            # the first dict, so heterogeneous keys crash mid-chunk.
            row["parts_checked_at"] = None
    await session.execute(delete(OpenalexWork).where(OpenalexWork.institution_id == institution.id))
    await session.execute(
        delete(OpenalexWorkAuthor).where(OpenalexWorkAuthor.institution_id == institution.id)
    )
    values = list(rows.values())
    for start in range(0, len(values), INSERT_CHUNK):
        await session.execute(
            OpenalexWork.__table__.insert(),
            [
                {**row, "institution_id": institution.id}
                for row in values[start : start + INSERT_CHUNK]
            ],
        )
    # Attribution edges: one (work, lower-cased author id) pair per
    # authorship — the indexed side of every attribution probe. OpenAlex
    # authorships can repeat an author within one work; the PK forbids
    # duplicate edges, so dedupe per row.
    pairs = [
        {"institution_id": institution.id, "author_id": aid, "w_id": row["w_id"]}
        for row in values
        for aid in sorted({a["a"].lower() for a in row["authorships"] if a["a"]})
    ]
    for start in range(0, len(pairs), INSERT_CHUNK):
        await session.execute(
            OpenalexWorkAuthor.__table__.insert(), pairs[start : start + INSERT_CHUNK]
        )
    # Modal work language per journal, over every institution's stored works
    # (language is a journal attribute, so any rebuild refreshes the same
    # global stamp; ties break alphabetically for determinism). Journals
    # whose works vanished keep the last stamp.
    modal = (
        select(
            OpenalexWork.venue_issn_l.label("issn_l"),
            OpenalexWork.language.label("lang"),
            func.row_number()
            .over(
                partition_by=OpenalexWork.venue_issn_l,
                order_by=[func.count().desc(), OpenalexWork.language.asc()],
            )
            .label("rn"),
        )
        .where(OpenalexWork.venue_issn_l.is_not(None), OpenalexWork.language.is_not(None))
        .group_by(OpenalexWork.venue_issn_l, OpenalexWork.language)
        .subquery()
    )
    stamped = await session.execute(
        update(Journal)
        .where(Journal.issn_l == modal.c.issn_l, modal.c.rn == 1)
        .values(language=modal.c.lang)
    )
    # Fold the fresh OA picture back into the canonical works rows: their
    # oa_status comes from OpenAlex (harvest/enrich.py) but freezes once a
    # work's journal resolves, so later green/gold upgrades never land.
    # The store is the only pass that sees current oa data. DOIs carried
    # under two W-ids with conflicting colors canonicalize to the most
    # open record (owner decision 2026-11-05).
    #
    # Precedence vs OpenAIRE (owner decision 2026-11-20): when
    # openaire_work_facts.oa_color disagrees with the store colour, the
    # OpenAlex colour wins and the OpenAIRE claim is ignored. Ground-truth
    # checks (scripts/analyze_oa_conflicts.py) rated both sources at
    # statistically indistinguishable accuracy, and the owner's tie-break
    # is OpenAlex. So works.oa_status only ever carries the OpenAlex
    # colour (Pure rights fill in where OpenAlex has no row); the OpenAIRE
    # colour stays display-only on the journal card. Pinned by
    # test_foldback_* outcome tests in tests/test_harvest_sources.py.
    canon = (
        select(
            OpenalexWork.doi_normalized.label("doi"),
            OpenalexWork.oa_status.label("oa"),
            # rank/w_id must sit in the select list: Postgres requires
            # DISTINCT ON trailing ORDER BY expressions to be selected.
            oa_openness_rank(OpenalexWork.oa_status).label("rank"),
            OpenalexWork.w_id.label("w_id"),
        )
        .where(
            OpenalexWork.institution_id == institution.id,
            OpenalexWork.oa_status.is_not(None),
        )
        .distinct(OpenalexWork.doi_normalized)
        .order_by(
            OpenalexWork.doi_normalized,
            oa_openness_desc(OpenalexWork.oa_status),
            OpenalexWork.w_id,
        )
        .subquery()
    )
    synced = await session.execute(
        update(Work)
        .where(
            Work.institution_id == institution.id,
            Work.doi_normalized == canon.c.doi,
            Work.oa_status.is_distinct_from(canon.c.oa),
        )
        .values(oa_status=canon.c.oa)
    )
    stats = {
        "works": len(values),
        "parse_failures": parse_failures,
        "excluded_types": excluded_types,
        "author_sweep_rows": sum(1 for r in values if r["source"] == AUTHOR_SWEEP_PREFIX),
        "attributions": len(pairs),
        "journals_language_stamped": stamped.rowcount,
        "works_oa_synced": synced.rowcount,
    }
    logger.info("openalex_works[%s]: %s", institution.code, stats)
    return stats
