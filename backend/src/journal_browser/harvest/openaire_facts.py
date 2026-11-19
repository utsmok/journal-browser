"""OpenAIRE work facts derive: source_records payloads -> openaire_work_facts.

The openaire harvest lands research products verbatim in source_records and
matches them to Pure works as confirmed work_identity rows. This job folds
the latest payload per confirmed identity into the derived per-work store
(usage counts, diamond flag, OA color, license, fulltext url, embargo,
FOS subjects, projects). Full idempotent refresh: every confirmed identity
is re-derived and rows whose identity is no longer confirmed are pruned, so
a rerun converges without a wipe.
"""

import logging
from datetime import date
from typing import Any, cast

from sqlalchemy import delete, select, text, tuple_
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..ingest import IngestSession
from ..models import Institution, OpenaireWorkFacts, SourceRecord, WorkIdentity

logger = logging.getLogger(__name__)

SOURCE = "openaire"
#: identities per payload-fetch chunk (memory bound)
CHUNK = 2_000

#: ON CONFLICT target shared by the model PK, the migration, and this upsert.
FACTS_UQ_COLS = ["institution_id", "pure_uuid"]

#: columns the upsert refreshes (updated_at is stamped separately)
UPSERT_COLS = (
    "source_pk",
    "views",
    "downloads",
    "diamond",
    "oa_color",
    "license",
    "oa_url",
    "embargo_end",
    "fos",
    "projects",
)


def _embargo_end(payload: dict[str, Any]) -> date | None:
    """Max embargo end across instances ('YYYY-MM-DD...' first-10 parse)."""
    ends: list[date] = []
    for inst in payload.get("instances") or []:
        raw = inst.get("embargoEndDate") if isinstance(inst, dict) else None
        if not raw:
            continue
        try:
            ends.append(date.fromisoformat(str(raw)[:10]))
        except ValueError:
            continue
    return max(ends) if ends else None


def _projects(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """[{id, funder, code, acronym}] from payload['projects'], which the
    API may serve as null, a scalar, or a list; non-dict entries dropped."""
    raw = payload.get("projects")
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [
        {k: p.get(k) for k in ("id", "funder", "code", "acronym")}
        for p in raw
        if isinstance(p, dict)
    ]


def facts_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """openaire_work_facts columns from one stored research product payload.

    Pure function of the payload so tests run without a database. Field
    paths match the stored aireloom dumps (license/open_access_url are
    aireloom computed properties, serialized top-level by model_dump).
    """
    usage = (payload.get("indicators") or {}).get("usageCounts") or {}
    fos = sorted(
        {
            value
            for s in payload.get("subjects") or []
            if isinstance(s, dict)
            and (s.get("subject") or {}).get("scheme", "").lower() == "fos"
            and (value := s["subject"].get("value"))
        }
    )
    return {
        "views": usage.get("views"),
        "downloads": usage.get("downloads"),
        "diamond": payload.get("isInDiamondJournal") is True,
        "oa_color": payload.get("openAccessColor"),
        "license": payload.get("license"),
        "oa_url": payload.get("open_access_url"),
        "embargo_end": _embargo_end(payload),
        "fos": fos,
        "projects": _projects(payload),
    }


async def derive_openaire_facts(
    session: AsyncSession,
    institution: Institution,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Rebuild openaire_work_facts for one institution from the latest
    stored payload per confirmed openaire identity. Idempotent full
    refresh; prunes rows whose identity is no longer confirmed."""
    ingest = IngestSession(session)
    await ingest.start_run(
        SOURCE,
        "facts",
        f"institution={institution.id}",
        {"chunk": CHUNK},
        institution_id=institution.id,
    )
    stats: dict[str, Any] = {
        "identities": 0,
        "upserted": 0,
        "pruned": 0,
        "with_usage": 0,
        "with_fulltext": 0,
        "diamond": 0,
    }

    identities = (
        await session.execute(
            select(WorkIdentity.source_pk, WorkIdentity.work_id).where(
                WorkIdentity.institution_id == institution.id,
                WorkIdentity.source == SOURCE,
                WorkIdentity.status == "confirmed",
            )
        )
    ).all()
    if limit is not None:
        identities = identities[:limit]
    stats["identities"] = len(identities)

    # Latest payload per source_pk, chunked to bound memory; a work with
    # several confirmed records (u1 matched twice) keeps the payload of
    # the newest record, and identities without a stored record yet keep
    # any existing row untouched.
    for at in range(0, len(identities), CHUNK):
        chunk = identities[at : at + CHUNK]
        pks = [pk for pk, _uuid in chunk]
        pk_payloads = {
            row.source_pk: (row.payload, row.harvested_at)
            for row in (
                await session.execute(
                    select(
                        SourceRecord.source_pk.label("source_pk"),
                        SourceRecord.payload.label("payload"),
                        SourceRecord.harvested_at.label("harvested_at"),
                    )
                    .ext(distinct_on(SourceRecord.source_pk))
                    .where(
                        SourceRecord.source == SOURCE,
                        SourceRecord.entity_type == "work",
                        SourceRecord.source_pk.in_(pks),
                    )
                    .order_by(SourceRecord.source_pk, SourceRecord.harvested_at.desc())
                )
            ).all()
        }
        candidates = []
        for source_pk, pure_uuid in chunk:
            hit = pk_payloads.get(source_pk)
            if hit is None:
                continue
            payload, harvested_at = hit
            candidates.append((harvested_at, pure_uuid, source_pk, payload))
        # newest record first; one facts row per work
        candidates.sort(key=lambda c: (c[0], c[2]), reverse=True)
        rows = []
        seen: set[str] = set()
        for _harvested_at, pure_uuid, source_pk, payload in candidates:
            if pure_uuid in seen:
                continue
            seen.add(pure_uuid)
            facts = facts_from_payload(payload)
            stats["with_usage"] += facts["views"] is not None or facts["downloads"] is not None
            stats["with_fulltext"] += facts["oa_url"] is not None
            stats["diamond"] += facts["diamond"]
            rows.append(
                {
                    "institution_id": institution.id,
                    "pure_uuid": pure_uuid,
                    "source_pk": source_pk,
                    **facts,
                }
            )
        if rows:
            await _upsert(session, rows)
            stats["upserted"] += len(rows)
        await ingest.commit()

    stats["pruned"] = await _prune(session, institution.id)
    logger.info("derive_openaire_facts: %s", stats)
    final = await ingest.finish_run("completed", stats)
    await session.commit()
    return final


async def _upsert(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    """INSERT ... ON CONFLICT (institution_id, pure_uuid) DO UPDATE; the
    update set re-stamps updated_at on every rerun."""
    stmt = pg_insert(cast("Any", OpenaireWorkFacts.__table__)).values(rows)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=FACTS_UQ_COLS,
            set_={
                **{c: getattr(stmt.excluded, c) for c in UPSERT_COLS},
                "updated_at": text("now()"),
            },
        )
    )


async def _prune(session: AsyncSession, institution_id: int) -> int:
    """Drop facts rows with no confirmed identity left (full-refresh
    semantics); work-row deletes cascade through the FK."""
    result = await session.execute(
        delete(OpenaireWorkFacts).where(
            OpenaireWorkFacts.institution_id == institution_id,
            tuple_(OpenaireWorkFacts.institution_id, OpenaireWorkFacts.pure_uuid).not_in(
                select(WorkIdentity.institution_id, WorkIdentity.work_id).where(
                    WorkIdentity.institution_id == institution_id,
                    WorkIdentity.source == SOURCE,
                    WorkIdentity.status == "confirmed",
                )
            ),
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)
