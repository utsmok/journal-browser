"""Pure CERIF entity sets: orgunits + persons (the standalone author canon).

Two extra OAI sweeps per institution (`openaire_cris_orgunits`,
`openaire_cris_persons`, both over `oai_cerif_openaire`). Records land
verbatim in source_records (entity_type orgs/persons, same store and
restart bookkeeping as the works sets); the normalized copies
(pure_orgs/pure_org_parents/pure_persons) are rebuilt from the latest
stored version per record afterwards, so a re-harvest with changed XML
flows through on the next run.

Non-year sets: no per-year restart granularity — a badResumptionToken
restarts the whole set (the works-set pattern, MAX_TOKEN_RESTARTS).
"""

import logging
import xml.etree.ElementTree as ET
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...ingest import IngestSession
from ...models import PureOrg, PureOrgParent, PurePerson, SourceRecord
from . import cerif
from .cerif import ref_uuid
from .pipeline import _harvest_set
from .transport import PREFIX_CERIF, SOURCE
from .xmlrecords import pure_uuid_for

logger = logging.getLogger(__name__)

CRIS_PERSONS_SET = "openaire_cris_persons"
CRIS_ORGUNITS_SET = "openaire_cris_orgunits"

#: set_spec -> source_records entity_type
ENTITY_SETS: tuple[tuple[str, str], ...] = (
    (CRIS_ORGUNITS_SET, "orgs"),
    (CRIS_PERSONS_SET, "persons"),
)


def parse_metadata_xml(xml_text: str | None) -> ET.Element | None:
    """First element of a stored inner-metadata XML string.

    The wrapper keeps multi-root re-serializations parseable; namespace
    URIs are irrelevant (parsing matches localnames).
    """
    if not xml_text:
        return None
    try:
        wrapped = ET.fromstring(f"<metadata>{xml_text}</metadata>")
    except ET.ParseError:
        return None
    return next(iter(wrapped), None)


def parse_entity_record(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Parsed CERIF person/orgunit from one stored OAI record payload.

    None when the record carries no parseable Person/OrgUnit root."""
    root = parse_metadata_xml(payload.get("metadata_xml"))
    if root is None:
        return None
    kind = cerif.localname(root)
    if kind == "Person":
        return {"entity_type": "persons", "cerif": cerif.parse_cerif_person(root)}
    if kind == "OrgUnit":
        return {"entity_type": "orgs", "cerif": cerif.parse_cerif_orgunit(root)}
    return None


async def _latest_records(
    session: AsyncSession, entity_type: str
) -> list[tuple[str, dict[str, Any]]]:
    """Latest stored payload per source_pk for one entity type.

    source_records is versioned by content hash; the newest version of a
    record wins (ut-metadata latest_source_records convention)."""
    rows = await session.execute(
        select(SourceRecord.source_pk, SourceRecord.payload)
        .where(SourceRecord.source == SOURCE, SourceRecord.entity_type == entity_type)
        .order_by(
            SourceRecord.source_pk,
            SourceRecord.harvested_at.desc(),
            SourceRecord.id.desc(),
        )
    )
    out: dict[str, dict[str, Any]] = {}
    for pk, payload in rows.all():
        out.setdefault(pk, payload)
    return list(out.items())


async def rebuild_pure_orgs(session: AsyncSession, institution_id: int) -> dict[str, int]:
    """Full-replace the institution's pure_orgs/pure_org_parents from the
    stored orgunit records."""
    org_rows: list[dict[str, Any]] = []
    parent_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    parse_failures = 0
    for pk, payload in await _latest_records(session, "orgs"):
        uuid = pure_uuid_for(pk)
        if uuid in seen:
            continue
        seen.add(uuid)
        parsed = parse_entity_record(payload)
        if parsed is None or parsed["entity_type"] != "orgs":
            parse_failures += 1
            continue
        cer = parsed["cerif"]
        name = cer.get("name")
        if not name:
            parse_failures += 1
            continue
        org_rows.append(
            {
                "institution_id": institution_id,
                "uuid": uuid,
                "name": name,
                "org_type": cer.get("type"),
                "identifiers": cer.get("identifiers") or [],
            }
        )
        parent_uuid = ref_uuid(cer.get("part_of_org_id"))
        if parent_uuid and parent_uuid != uuid:
            parent_rows.append(
                {
                    "institution_id": institution_id,
                    "org_uuid": uuid,
                    "parent_uuid": parent_uuid,
                    "parent_name": cer.get("part_of_name"),
                }
            )
    await session.execute(delete(PureOrg).where(PureOrg.institution_id == institution_id))
    if org_rows:
        await session.execute(pg_insert(PureOrg), org_rows)
    if parent_rows:
        await session.execute(pg_insert(PureOrgParent), parent_rows)
    return {"orgs": len(org_rows), "parents": len(parent_rows), "parse_failures": parse_failures}


async def rebuild_pure_persons(session: AsyncSession, institution_id: int) -> dict[str, int]:
    """Full-replace the institution's pure_persons from the stored person
    records. orcid stores the bare lower-cased form (comparisons key on
    it); the payload keeps the parsed CERIF verbatim-ish."""
    person_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    parse_failures = 0
    for pk, payload in await _latest_records(session, "persons"):
        uuid = pure_uuid_for(pk)
        if uuid in seen:
            continue
        seen.add(uuid)
        parsed = parse_entity_record(payload)
        if parsed is None or parsed["entity_type"] != "persons":
            parse_failures += 1
            continue
        cer = parsed["cerif"]
        raw_orcid = cer.get("orcid") or ""
        orcid = raw_orcid.rsplit("/", 1)[-1].lower() or None
        name = " ".join(
            part for part in (cer.get("first_names"), cer.get("family_names")) if part
        ).strip()
        person_rows.append(
            {
                "institution_id": institution_id,
                "uuid": uuid,
                "orcid": orcid,
                "name": name or None,
                "payload": {"cerif": cer},
            }
        )
    await session.execute(delete(PurePerson).where(PurePerson.institution_id == institution_id))
    if person_rows:
        await session.execute(pg_insert(PurePerson), person_rows)
    return {"persons": len(person_rows), "parse_failures": parse_failures}


async def harvest_pure_entities(
    session: AsyncSession,
    institution,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Sweep the CERIF entity sets, then rebuild the normalized copies.

    Per set: one harvest_run (source=pure, entity_type=orgs/persons),
    per-page commits, whole-set restart on badResumptionToken."""
    base_url = institution.pure_oai_base_url
    if not base_url:
        raise ValueError(f"institution {institution.code!r} has no pure_oai_base_url")
    stats: dict[str, Any] = {"sets": {}}
    for set_spec, entity_type in ENTITY_SETS:
        ingest = IngestSession(session)
        config = {"base_url": base_url, "metadata_prefix": PREFIX_CERIF}
        await ingest.start_run(SOURCE, entity_type, set_spec, config, institution_id=institution.id)
        try:
            set_stats = await _harvest_set(
                ingest,
                set_spec,
                PREFIX_CERIF,
                base_url=base_url,
                institution_id=institution.id,
                limit=limit,
            )
        except Exception as exc:
            await ingest.finish_run("failed", {"error": f"{type(exc).__name__}: {exc}"[:200]})
            raise
        await ingest.finish_run("completed", set_stats)
        await ingest.commit()
        stats["sets"][set_spec] = set_stats
    stats["orgs"] = await rebuild_pure_orgs(session, institution.id)
    stats["persons"] = await rebuild_pure_persons(session, institution.id)
    await session.commit()
    logger.info("pure entities[%s]: %s", institution.code, stats)
    return stats
