"""work_partners derive: stored OpenAlex and OpenAIRE work payloads ->
work_partners, plus stub rows in partner_institutions.

For every hosted institution the job rebuilds work_partners in two passes
over the newest stored payload of each confirmed work identity (the PID
match, see work_identity):

1. OpenAlex authorships. Every authorship institution with a ROR id
   becomes a partner, except the home institution and its children (an
   institution whose OpenAlex lineage contains the home OpenAlex id).
2. OpenAIRE organisations, only for works the first pass gave no partner:
   organisations that carry a ROR pid, minus the home ROR ids.

OpenAlex wins because its authorships carry the corresponding-author flag
and the institution lineage. OpenAIRE adds the works OpenAlex did not
link. Both passes also upsert stub rows into partner_institutions (name,
type and country as the payload gives them), so the serving layer can
label a partner before harvest.ror fills in the ROR record.

Idempotent: a rerun replaces the institution's rows with the same ones.
Commits per institution, so an interrupted run resumes as a rerun.
"""

import logging
from typing import Any, cast

from sqlalchemy import TEXT, and_, any_, bindparam, delete, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Institution,
    PartnerInstitution,
    SourceRecord,
    Work,
    WorkIdentity,
    WorkPartner,
)
from .common import get_active_institutions
from .funders import normalize_ror

logger = logging.getLogger(__name__)

OPENALEX = "openalex"
OPENAIRE = "openaire"
#: Only a confirmed identity makes a stored payload the work's record.
CONFIRMED = "confirmed"

#: rows per INSERT (7 columns each; asyncpg caps statements at 32,767 binds)
INSERT_CHUNK = 1000
#: payloads per streaming partition; partner rows flush after each one
STREAM_PARTITION = 200


def _bare(openalex_id: Any) -> str | None:
    """'https://openalex.org/I123' -> 'I123'; None without a usable id."""
    if not isinstance(openalex_id, str) or not openalex_id.strip():
        return None
    return openalex_id.rstrip("/").rsplit("/", 1)[-1]


def _stub(
    *, name: Any, org_type: Any, country_code: Any, openalex_id: Any, corresponding: bool
) -> dict[str, Any]:
    """Partner value that both the row writer and the stub upsert read:
    the stub columns, the number of authorships and the corresponding
    flag."""
    return {
        "name": name,
        "org_type": org_type,
        "country_code": country_code,
        "openalex_id": openalex_id,
        "authorships": 1,
        "corresponding": corresponding,
    }


def openalex_partners(
    payload: dict[str, Any], home_id: str | None
) -> tuple[dict[str, dict[str, Any]], set[str], int, int]:
    """Partners of one OpenAlex work payload, keyed on the bare ROR id.

    Returns (partners, home ROR ids seen, non-home entries without a ROR
    id, home entries). A partner value carries name, org_type,
    country_code and openalex_id for its stub row, the number of
    authorships, and whether one of them is a corresponding authorship.
    An authorship institution is home when its lineage holds home_id; the
    lineage includes the institution's own id.
    """
    partners: dict[str, dict[str, Any]] = {}
    home_rors: set[str] = set()
    without_ror = 0
    home_entries = 0
    for authorship in payload.get("authorships") or []:
        corresponding = bool(authorship.get("is_corresponding"))
        for inst in authorship.get("institutions") or []:
            ror = normalize_ror(inst.get("ror"))
            lineage = {_bare(i) for i in inst.get("lineage") or []}
            if home_id is not None and (home_id == _bare(inst.get("id")) or home_id in lineage):
                home_entries += 1
                if ror:
                    home_rors.add(ror)
                continue
            if not ror:
                without_ror += 1
                continue
            partner = partners.get(ror)
            if partner is None:
                partners[ror] = _stub(
                    name=inst.get("display_name"),
                    org_type=inst.get("type"),
                    country_code=inst.get("country_code"),
                    openalex_id=_bare(inst.get("id")),
                    corresponding=corresponding,
                )
                continue
            partner["authorships"] += 1
            partner["corresponding"] = partner["corresponding"] or corresponding
    return partners, home_rors, without_ror, home_entries


def openaire_partners(payload: dict[str, Any], home_rors: set[str]) -> dict[str, dict[str, Any]]:
    """Partners of one OpenAIRE work payload, keyed on the bare ROR id.

    Only organisations with a ROR pid count, because an unresolved
    organisation has none; the home ROR ids are skipped. OpenAIRE gives
    neither authorships nor a corresponding flag, so every partner carries
    one authorship and corresponding False."""
    partners: dict[str, dict[str, Any]] = {}
    for org in payload.get("organizations") or []:
        ror = next(
            (
                normalize_ror(pid.get("value"))
                for pid in org.get("pids") or []
                if (pid.get("scheme") or "").upper() == "ROR"
            ),
            None,
        )
        if not ror or ror in home_rors:
            continue
        countries = org.get("countries") or []
        partners[ror] = _stub(
            name=org.get("legalName") or org.get("acronym"),
            org_type=None,
            country_code=countries[0].get("code") if countries else None,
            openalex_id=None,
            corresponding=False,
        )
    return partners


def _newest_payload(source: str):
    """Newest stored payload for one identity's source_pk."""
    return (
        select(SourceRecord.payload)
        .where(
            SourceRecord.source == source,
            SourceRecord.entity_type == "work",
            SourceRecord.source_pk == WorkIdentity.source_pk,
        )
        .order_by(SourceRecord.harvested_at.desc(), SourceRecord.id.desc())
        .limit(1)
        .correlate(WorkIdentity)
        .scalar_subquery()
    )


async def _identities(session, institution: Institution, source: str, skip: set[str]):
    """Stream (pure_uuid, newest payload) in partitions for the
    institution's confirmed identities of one source whose work exists,
    skipping the pure_uuids in `skip`."""
    stmt = (
        select(WorkIdentity.work_id, _newest_payload(source).label("payload"))
        .join(
            Work,
            and_(
                Work.institution_id == WorkIdentity.institution_id,
                Work.pure_uuid == WorkIdentity.work_id,
            ),
        )
        .where(
            WorkIdentity.institution_id == institution.id,
            WorkIdentity.source == source,
            WorkIdentity.status == CONFIRMED,
        )
    )
    if skip:
        # One array bind, not one bind per id: a large institution skips
        # far more ids than Postgres accepts parameters in a statement.
        stmt = stmt.where(~(WorkIdentity.work_id == any_(bindparam("skip", type_=ARRAY(TEXT)))))
        stmt = stmt.params(skip=sorted(skip))
    result = await session.stream(
        stmt.execution_options(stream_results=True, max_row_buffer=STREAM_PARTITION)
    )
    async for partition in result.partitions(STREAM_PARTITION):
        yield partition


async def _insert_partners(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    """Insert partner rows; a repeated (work, partner) keeps its first row,
    which can only arise from a work with two identities at one source."""
    for at in range(0, len(rows), INSERT_CHUNK):
        chunk = rows[at : at + INSERT_CHUNK]
        stmt = pg_insert(WorkPartner).values(chunk)
        await session.execute(stmt.on_conflict_do_nothing())


async def _upsert_stubs(session: AsyncSession, stubs: dict[str, dict[str, Any]]) -> None:
    """Stub rows for every partner the payloads named. A column that
    already holds a value (from ROR or an earlier run) keeps it."""
    table = cast("Any", PartnerInstitution.__table__)
    rows = [
        {"ror": ror, **{key: partner.get(key) for key in _STUB_COLS}}
        for ror, partner in sorted(stubs.items())
    ]
    for at in range(0, len(rows), INSERT_CHUNK):
        chunk = rows[at : at + INSERT_CHUNK]
        stmt = pg_insert(table).values(chunk)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["ror"],
                set_={
                    **{col: func.coalesce(table.c[col], stmt.excluded[col]) for col in _STUB_COLS},
                    "updated_at": text("now()"),
                },
            )
        )


#: partner_institutions columns a work payload can fill.
_STUB_COLS = ("name", "org_type", "country_code", "openalex_id")

_STATS_KEYS = (
    "openalex_works_with_partner",
    "openaire_works_with_partner",
    "partner_rows",
    "partners",
    "entries_without_ror",
    "home_entries",
)


async def _derive_institution(session: AsyncSession, institution: Institution) -> dict[str, int]:
    """Rebuild one institution's partner rows (the caller deleted the old
    ones and commits)."""
    stats: dict[str, int] = dict.fromkeys(_STATS_KEYS, 0)
    stats["works"] = (
        await session.scalar(
            select(func.count()).select_from(Work).where(Work.institution_id == institution.id)
        )
        or 0
    )
    home_id = _bare(institution.openalex_id)
    home_rors: set[str] = set()
    if ror := normalize_ror(institution.ror):
        home_rors.add(ror)
    stubs: dict[str, dict[str, Any]] = {}

    # Pass 1: OpenAlex authorships.
    covered: set[str] = set()
    rows: list[dict[str, Any]] = []

    async def flush() -> None:
        await _insert_partners(session, rows)
        stats["partner_rows"] += len(rows)
        rows.clear()

    async for partition in _identities(session, institution, OPENALEX, set()):
        for pure_uuid, payload in partition:
            if not payload:
                continue
            partners, seen_home, without_ror, home_entries = openalex_partners(payload, home_id)
            home_rors |= seen_home
            stats["entries_without_ror"] += without_ror
            stats["home_entries"] += home_entries
            if not partners:
                continue
            covered.add(pure_uuid)
            for ror, partner in partners.items():
                stubs.setdefault(ror, partner)
                rows.append(_row(institution.id, pure_uuid, ror, OPENALEX, partner))
        await flush()
    await flush()
    stats["openalex_works_with_partner"] = len(covered)

    # Pass 2: OpenAIRE organisations for the works pass 1 left without a
    # partner. It runs after pass 1 so home_rors is complete. A work with
    # two OpenAIRE identities passes by twice and counts once.
    rescued: set[str] = set()
    async for partition in _identities(session, institution, OPENAIRE, covered):
        for pure_uuid, payload in partition:
            if not payload or pure_uuid in rescued:
                continue
            partners = openaire_partners(payload, home_rors)
            if not partners:
                continue
            rescued.add(pure_uuid)
            for ror, partner in partners.items():
                stubs.setdefault(ror, partner)
                rows.append(_row(institution.id, pure_uuid, ror, OPENAIRE, partner))
        await flush()
    await flush()
    stats["openaire_works_with_partner"] = len(rescued)

    await _upsert_stubs(session, stubs)
    stats["partners"] = len(stubs)
    stats["works_without_partner"] = (
        stats["works"] - stats["openalex_works_with_partner"] - stats["openaire_works_with_partner"]
    )
    return stats


def _row(
    institution_id: int, pure_uuid: str, ror: str, source: str, partner: dict[str, Any]
) -> dict[str, Any]:
    return {
        "institution_id": institution_id,
        "work_pure_uuid": pure_uuid,
        "partner_ror": ror,
        "source": source,
        "partner_openalex_id": partner.get("openalex_id"),
        "corresponding": partner["corresponding"],
        "authorships": partner["authorships"],
    }


async def derive_work_partners(session: AsyncSession) -> dict[str, int]:
    """Rebuild work_partners for every hosted institution."""
    total: dict[str, int] = {}
    for institution in await get_active_institutions(session):
        await session.execute(
            delete(WorkPartner).where(WorkPartner.institution_id == institution.id)
        )
        try:
            stats = await _derive_institution(session, institution)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("derive_work_partners[%s]: failed", institution.code)
            raise
        logger.info("derive_work_partners[%s]: %s", institution.code, stats)
        for key, value in stats.items():
            total[key] = total.get(key, 0) + value
    logger.info("derive_work_partners: %s", total)
    return total
