import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Work
from .cerif import ref_uuid
from .doi import extract_doi
from .transport import PureOaiError
from .xmlrecords import (
    _dc_first,
    _norm_title,
    canonical_access,
    pure_uuid_for,
)

logger = logging.getLogger(__name__)


async def upsert_work(
    session: AsyncSession,
    payload: dict[str, Any],
    *,
    institution_id: int,
    year: int,
    run_id: int,
) -> None:
    """Upsert one canonical work of one institution from a harvested oai_dc payload."""
    dc = payload.get("dc", {})
    title = _dc_first(dc.get("title"))
    if not title:
        raise PureOaiError("parse", f"record without dc:title: {payload['oai_identifier']}")
    cerif = payload.get("cerif") or {}
    doi = payload.get("doi_normalized") or extract_doi(cerif.get("doi") or "")
    uuid = pure_uuid_for(payload["oai_identifier"])
    if doi:
        # Pure occasionally carries the same publication under two uuids
        # (e.g. article + chapter views); doi_normalized is UNIQUE, so the
        # twin keeps the DOI and this row stays NULL-doi (fuzzy-matchable).
        owner = await session.scalar(
            select(Work.pure_uuid).where(
                Work.institution_id == institution_id,
                Work.doi_normalized == doi,
                Work.pure_uuid != uuid,
            )
        )
        if owner:
            logger.warning(
                "duplicate DOI %s across pure works %s and %s; storing %s without doi",
                doi,
                owner,
                uuid,
                uuid,
            )
            doi = None
    oa_status = canonical_access(_dc_first(cerif.get("oa_status")) or _dc_first(dc.get("rights")))
    stmt = (
        pg_insert(Work)
        .values(
            institution_id=institution_id,
            pure_uuid=uuid,
            doi_normalized=doi,
            title=title,
            norm_title=_norm_title(title),
            year=year,
            work_type=_dc_first(dc.get("type")),
            publisher=_dc_first(dc.get("publisher")),
            cerif_issn=_dc_first(cerif.get("issn")),
            oa_status=oa_status,
            first_seen_run=run_id,
            last_seen_run=run_id,
        )
        .on_conflict_do_update(
            index_elements=[Work.institution_id, Work.pure_uuid],
            set_={
                "doi_normalized": doi,
                "title": title,
                "norm_title": _norm_title(title),
                "year": year,
                "work_type": _dc_first(dc.get("type")),
                "publisher": _dc_first(dc.get("publisher")),
                "cerif_issn": _dc_first(cerif.get("issn")),
                "oa_status": oa_status,
                "last_seen_run": run_id,
                "retired_at": None,
                "updated_at": datetime.now(UTC),
            },
        )
    )
    await session.execute(stmt)


async def store_pure_work_authors(
    session: AsyncSession,
    work_uuid: str,
    authors: list[dict[str, Any]],
    *,
    institution_id: int,
) -> int:
    """Full-replace one work's pure authorship edges (work_pure_authors).

    Person and affiliation refs are CERIF relative ids
    ('openaire_cris_persons/<uuid>'); both collapse to the bare uuid. The
    flattened primary affiliation_id is the fallback when the affiliations
    list is empty (ut-metadata collab._WORK_ORG_SQL's COALESCE). Rows for
    works the institution does not hold are skipped — the FK onto works
    must never fire (a cerif-only record can precede its works row; the
    backfill job covers those)."""
    from ...models import Work, WorkPureAuthor

    exists = await session.scalar(
        select(Work.pure_uuid).where(
            Work.institution_id == institution_id, Work.pure_uuid == work_uuid
        )
    )
    if exists is None:
        return 0
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, author in enumerate(authors):
        person_uuid = ref_uuid(author.get("person_id"))
        if not person_uuid or person_uuid in seen:
            continue
        seen.add(person_uuid)
        affiliations = [
            ref
            for ref in (
                ref_uuid(aff.get("affiliation_id")) for aff in author.get("affiliations") or []
            )
            if ref
        ]
        if not affiliations and author.get("affiliation_id"):
            affiliations = [ref_uuid(author["affiliation_id"])]
        rows.append(
            {
                "institution_id": institution_id,
                "work_pure_uuid": work_uuid,
                "person_uuid": person_uuid,
                "position": position,
                "first_names": (author.get("first_names") or "").strip() or None,
                "family_names": (author.get("family_names") or "").strip() or None,
                "affiliations": affiliations,
            }
        )
    await session.execute(
        delete(WorkPureAuthor).where(
            WorkPureAuthor.institution_id == institution_id,
            WorkPureAuthor.work_pure_uuid == work_uuid,
        )
    )
    if rows:
        await session.execute(pg_insert(WorkPureAuthor), rows)
    return len(rows)


async def backfill_cerif(
    session: AsyncSession, uuid: str, cerif: dict[str, Any], *, institution_id: int
) -> None:
    """Backfill cerif-derived fields onto an existing work; never nulls.

    doi_normalized is UNIQUE across works and cerif records can repeat a
    DOI another uuid already claimed, so the DOI is only set when free.
    """
    values: dict[str, Any] = {"updated_at": datetime.now(UTC)}
    if issn := _dc_first(cerif.get("issn")):
        values["cerif_issn"] = issn
    if publisher := _dc_first(cerif.get("publisher")):
        values["publisher"] = publisher
    if oa := canonical_access(_dc_first(cerif.get("oa_status"))):
        values["oa_status"] = oa
    if doi := extract_doi(cerif.get("doi") or ""):
        owner = await session.scalar(
            select(Work.pure_uuid).where(
                Work.institution_id == institution_id,
                Work.doi_normalized == doi,
                Work.pure_uuid != uuid,
            )
        )
        if owner is None:
            values["doi_normalized"] = doi
    if len(values) == 1:
        return
    from sqlalchemy import update

    await session.execute(
        update(Work)
        .where(Work.institution_id == institution_id, Work.pure_uuid == uuid)
        .values(**values)
    )


async def retire_absent(session: AsyncSession, run_ids: list[int], institution_id: int) -> int:
    """Mark the institution's works not seen in any of these sweep runs as retired.

    Never deletes. A no-run call is a no-op: `NOT IN ()` would retire
    every row.
    """
    if not run_ids:
        return 0
    from sqlalchemy import update

    result = await session.execute(
        update(Work)
        .where(
            Work.institution_id == institution_id,
            Work.last_seen_run.not_in(run_ids),
            Work.retired_at.is_(None),
        )
        .values(retired_at=datetime.now(UTC))
    )
    return result.rowcount or 0


# ── Job entry points ─────────────────────────────────────────────────────────
