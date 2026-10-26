"""/api/v1/admin: password-protected harvest inspection and configuration.

POST /admin/login exchanges the admin password for a stateless HMAC
bearer token (12 h; the MAC secret derives from the current settings, so a
password change invalidates old tokens immediately). GET endpoints show
recent harvest runs and deals flagged for curation. GET/PUT /settings read
and write the settings.yaml overlay (reloaded live, no restart) and
GET/PUT /institutions/{code} the per-university configuration rows.
/deals is the curation CRUD: edits are recorded as manual_overrides and
survive every re-harvest; removed deal journals are flagged, not deleted.
"""

import asyncio
import hashlib
import hmac
import os
import time
from datetime import date
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import delete, desc, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..config import (
    get_settings,
    load_settings_yaml,
    reset_settings_cache,
    settings_yaml_path,
)
from ..db import get_session
from ..harvest.common import (
    get_active_institutions,
    get_institution_by_code,
    normalize_issn,
)
from ..harvest.denorm import refresh_deal_flags
from ..models import (
    Deal,
    DealInstitution,
    DealJournal,
    HarvestRun,
    Institution,
    IssnMap,
    Journal,
    ManualOverride,
    Publisher,
)
from ..settings_schema import SETTINGS_REGISTRY, value_for_response

router = APIRouter(prefix="/admin", tags=["admin"])

TOKEN_TTL = 12 * 3600
MASK = "********"


class LoginIn(BaseModel):
    password: str


def _secret() -> bytes:
    return hashlib.sha256(f"jb-admin:{get_settings().admin_password}".encode()).digest()


def _issue_token() -> str:
    expires = int(time.time()) + TOKEN_TTL
    mac = hmac.new(_secret(), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{mac}"


def _valid_token(token: str) -> bool:
    expires, _, mac = token.partition(".")
    if not expires.isdigit() or not mac:
        return False
    if int(expires) < time.time():
        return False
    expected = hmac.new(_secret(), expires.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, mac)


async def _require_admin(request: Request) -> None:
    if not get_settings().admin_password:
        raise HTTPException(403, "admin disabled: set JB_ADMIN_PASSWORD")
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not _valid_token(token):
        raise HTTPException(401, "invalid or expired token")


AdminDep = Annotated[None, Depends(_require_admin)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("/login")
async def login(body: LoginIn) -> dict[str, Any]:
    password = get_settings().admin_password
    if not password or not hmac.compare_digest(body.password, password):
        raise HTTPException(403, "wrong password or admin disabled")
    return {"token": _issue_token(), "expires_in": TOKEN_TTL}


@router.get("/runs")
async def list_runs(
    session: SessionDep,
    _: AdminDep,
    institution: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    query = (
        select(HarvestRun, Institution.code)
        .outerjoin(Institution, Institution.id == HarvestRun.institution_id)
        .order_by(desc(HarvestRun.id))
        .limit(limit)
    )
    if institution is not None:
        from ..harvest.common import get_institution_by_code

        inst = await get_institution_by_code(session, institution)
        if inst is None:
            raise HTTPException(status_code=400, detail=f"unknown institution: {institution}")
        query = query.where(HarvestRun.institution_id == inst.id)
    rows = (await session.execute(query)).all()
    return [
        {
            "id": r.id,
            "source": r.source,
            "entity_type": r.entity_type,
            "institution_id": r.institution_id,
            "institution_code": code,
            "status": r.status,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "stats": r.stats,
        }
        for r, code in rows
    ]


@router.get("/flagged")
async def flagged_deals(session: SessionDep, _: AdminDep) -> list[dict[str, Any]]:
    journal_count = (
        select(func.count())
        .select_from(DealJournal)
        .where(DealJournal.deal_id == Deal.id)
        .correlate(Deal)
        .scalar_subquery()
    )
    rows = (
        await session.execute(
            select(Deal, Publisher.name, journal_count)
            .join(Publisher, Publisher.id == Deal.publisher_id)
            .where(Deal.needs_curation.is_(True))
            .order_by(Deal.status.desc(), Publisher.name)
        )
    ).all()
    return [
        {
            "id": deal.id,
            "publisher": name,
            "esac_id": deal.esac_id,
            "status": deal.status,
            "duration": deal.duration_text,
            "journals": count,
            "reason": deal.needs_curation_reason,
        }
        for deal, name, count in rows
    ]


def _settings_payload() -> dict[str, Any]:
    s = get_settings()
    values = {
        f.key: value_for_response(f.type, getattr(s, f.key))
        for f in SETTINGS_REGISTRY
        if f.section == "global"
    }
    return {"schema": [f.model_dump() for f in SETTINGS_REGISTRY], "values": values}


def _value_ok(ftype: str, value: Any) -> bool:
    match ftype:
        case "string" | "secret":
            return isinstance(value, str)
        case "bool":
            return isinstance(value, bool)
        case "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        case "list":
            return isinstance(value, list) and all(isinstance(v, str) for v in value)
    return False


def _write_settings_yaml(doc: dict[str, Any]) -> None:
    """Write YAML in place with fsync. tmp+rename would be atomic, but the
    compose bind mount makes rename(2) fail with EBUSY (you cannot replace a
    mount point), so truncate-and-write is the only portable option; the
    reader side tolerates a partial file by ignoring YAML errors until the
    next mtime change."""
    path = settings_yaml_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(doc, fh, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())


@router.get("/settings")
async def effective_settings(_: AdminDep) -> dict[str, Any]:
    return _settings_payload()


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


@router.put("/settings")
async def update_settings(body: SettingsUpdate, _: AdminDep) -> dict[str, Any]:
    fields = {f.key: f for f in SETTINGS_REGISTRY}
    doc = load_settings_yaml()
    for key, value in body.values.items():
        f = fields.get(key)
        if f is None:
            raise HTTPException(400, f"unknown setting: {key}")
        if f.section == "institution":
            raise HTTPException(
                400, f"{key} is per-institution; use PUT /admin/institutions/{{code}}"
            )
        if not _value_ok(f.type, value):
            raise HTTPException(400, f"{key}: expected {f.type}")
        if f.type == "secret" and value in ("", MASK):
            continue  # keep the existing value
        if key == "ignored_issns":
            # Journal filters compare against journals.issn_l (XXXX-XXXX);
            # normalize on write so "12345678" or lowercase still matches.
            normalized = sorted({n for n in (normalize_issn(v) for v in value) if n})
            if len(normalized) != len(value):
                raise HTTPException(
                    400, "ignored_issns: entries must be valid ISSNs"
                )
            value = normalized
        doc[key] = value
    _write_settings_yaml(doc)
    reset_settings_cache()
    return _settings_payload()


# Editable institutions-table fields (never code/id) with their value kinds.
INSTITUTION_EDITABLE: dict[str, str] = {
    "name": "string",
    "short_name": "string",
    "ror": "string",
    "openalex_id": "string",
    "pure_oai_base_url": "string",
    "openaire_org_id": "string",
    "data_window_start": "int",
    "data_window_end": "int",
    "library_url": "string",
    "oa_guide_url": "string",
    "support_email": "string",
    "admin_contact": "string",
    "research_portal_url": "string",
    "active": "bool",
    "require_confirmed_affiliation": "bool",
}
# String fields the DB allows to be NULL; explicit null clears the value.
INSTITUTION_NULLABLE = set(INSTITUTION_EDITABLE) - {
    "name",
    "data_window_start",
    "data_window_end",
    "active",
}


def _institution_payload(inst: Institution) -> dict[str, Any]:
    return {
        "code": inst.code,
        "name": inst.name,
        "short_name": inst.short_name,
        "ror": inst.ror,
        "openalex_id": inst.openalex_id,
        "pure_oai_base_url": inst.pure_oai_base_url,
        "openaire_org_id": inst.openaire_org_id,
        "data_window_start": inst.data_window_start,
        "data_window_end": inst.data_window_end,
        "library_url": inst.library_url,
        "oa_guide_url": inst.oa_guide_url,
        "support_email": inst.support_email,
        "admin_contact": inst.admin_contact,
        "research_portal_url": inst.research_portal_url,
        "active": inst.active,
        "require_confirmed_affiliation": inst.require_confirmed_affiliation,
    }


async def _get_institution_or_404(session: AsyncSession, code: str) -> Institution:
    inst = (
        await session.execute(select(Institution).where(Institution.code == code))
    ).scalar_one_or_none()
    if inst is None:
        raise HTTPException(404, f"unknown institution: {code}")
    return inst


@router.get("/institutions/{code}")
async def get_institution(
    code: str, session: SessionDep, _: AdminDep
) -> dict[str, Any]:
    return _institution_payload(await _get_institution_or_404(session, code))


@router.put("/institutions/{code}")
async def update_institution(
    code: str, body: dict[str, Any], session: SessionDep, _: AdminDep
) -> dict[str, Any]:
    inst = await _get_institution_or_404(session, code)
    for key, value in body.items():
        kind = INSTITUTION_EDITABLE.get(key)
        if kind is None:
            raise HTTPException(400, f"unknown or immutable institution field: {key}")
        if kind == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                raise HTTPException(400, f"{key}: expected int")
        elif kind == "bool":
            if not isinstance(value, bool):
                raise HTTPException(400, f"{key}: expected bool")
        elif kind == "secret":
            if not isinstance(value, str):
                raise HTTPException(400, f"{key}: expected string")
        elif (value is None and key not in INSTITUTION_NULLABLE) or (
            value is not None and not isinstance(value, str)
        ):
            raise HTTPException(400, f"{key}: expected string")
    updates = dict(body)
    for key, value in updates.items():
        setattr(inst, key, value)
    await session.commit()
    return _institution_payload(inst)


# ── Deals: curation CRUD ────────────────────────────────────────────────────
# Every accepted edit writes a manual_overrides row (table_name="deals",
# row_key=str(deal id)), which apply_overrides re-applies after each
# harvester upsert — that is what makes edits stick. Removing a deal
# journal sets excluded=true and keeps the row so the JCT upsert cannot
# resurrect it.

# Fields PUT /admin/deals/{id} accepts.
DEAL_EDITABLE = {
    "status",
    "start_year",
    "end_year",
    "corresponding_authors_only",
    "cap_numbers",
    "cap_text",
    "summary",
    "esac_id",
    "publisher_id",
}


def _validate_deal_field(key: str, value: Any) -> None:
    if key == "status":
        if value not in ("current", "archive"):
            raise HTTPException(400, "status must be 'current' or 'archive'")
    elif key in ("start_year", "end_year", "publisher_id"):
        if not isinstance(value, int) or isinstance(value, bool):
            raise HTTPException(400, f"{key}: expected int")
    elif key == "corresponding_authors_only":
        if not isinstance(value, bool):
            raise HTTPException(400, "corresponding_authors_only: expected bool")
    elif key in ("cap_text", "summary", "esac_id"):
        # Nullable columns: the editor sends null to clear the field.
        if value is not None and not isinstance(value, str):
            raise HTTPException(400, f"{key}: expected string or null")
    elif key == "cap_numbers" and value is not None and (
        not isinstance(value, dict)
        or not all(
            isinstance(k, str)
            and len(k) == 4
            and k.isdigit()
            and isinstance(v, int)
            and not isinstance(v, bool)
            for k, v in value.items()
        )
    ):
        raise HTTPException(400, "cap_numbers: expected {\"yyyy\": count} or null")


def _deal_payload(
    deal: Deal, publisher: str | None, journal_count: int, participations: list[str]
) -> dict[str, Any]:
    return {
        "id": deal.id,
        "publisher_id": deal.publisher_id,
        "publisher": publisher,
        "esac_id": deal.esac_id,
        "status": deal.status,
        "start_year": deal.start_year,
        "end_year": deal.end_year,
        "corresponding_authors_only": deal.corresponding_authors_only,
        "capped": bool(deal.cap_numbers),
        "cap_numbers": deal.cap_numbers,
        "cap_text": deal.cap_text,
        "summary": deal.summary,
        "journal_count": journal_count,
        "participations": participations,
        "needs_curation": deal.needs_curation,
        "needs_curation_reason": deal.needs_curation_reason,
    }


async def _deal_detail(session: AsyncSession, deal_id: int) -> dict[str, Any]:
    row = (
        await session.execute(
            select(Deal, Publisher.name)
            .outerjoin(Publisher, Publisher.id == Deal.publisher_id)
            .where(Deal.id == deal_id)
        )
    ).first()
    if row is None:
        raise HTTPException(404, f"unknown deal: {deal_id}")
    deal, publisher = row
    journal_count = await session.scalar(
        select(func.count()).where(
            DealJournal.deal_id == deal_id, DealJournal.excluded.is_(False)
        )
    )
    codes = (
        (
            await session.execute(
                select(Institution.code)
                .join(DealInstitution, DealInstitution.institution_id == Institution.id)
                .where(
                    DealInstitution.deal_id == deal_id,
                    Institution.code.is_not(None),
                )
                .order_by(Institution.code)
            )
        )
        .scalars()
        .all()
    )
    journals = (
        (
            await session.execute(
                select(DealJournal)
                .where(DealJournal.deal_id == deal_id)
                .order_by(DealJournal.issn, DealJournal.institution_id)
            )
        )
        .scalars()
        .all()
    )
    return {
        **_deal_payload(deal, publisher, int(journal_count or 0), list(codes)),
        "journals": [
            {
                "issn": dj.issn,
                "issn_l": dj.issn_l,
                "journal_name": dj.journal_name,
                "source": dj.source,
                "excluded": dj.excluded,
            }
            for dj in journals
        ],
    }


async def _refresh_deal_flags_soon() -> None:
    """Recompute hosted institutions' coverage on a fresh connection."""
    engine = create_async_engine(get_settings().database_url)
    try:
        maker = async_sessionmaker(engine)
        async with maker() as session:
            hosted = await get_active_institutions(session)
            for inst in hosted:
                await refresh_deal_flags(session, inst.id)
            await session.commit()
    finally:
        await engine.dispose()


_flags_task: asyncio.Task | None = None
_flags_rerun = False


def _schedule_flags_refresh() -> None:
    """Deal writes change per-institution coverage, but the full recompute
    takes tens of seconds on live data — run it in the background so admin
    edits return instantly. Coverage lags the write by about that long."""
    global _flags_task, _flags_rerun
    if _flags_task is not None and not _flags_task.done():
        # A pass is running; it may miss this commit, so run once more after.
        _flags_rerun = True
        return
    _flags_task = asyncio.create_task(_flags_refresh_loop())


async def _flags_refresh_loop() -> None:
    global _flags_rerun
    while True:
        _flags_rerun = False
        try:
            await _refresh_deal_flags_soon()
        except Exception:  # noqa: BLE001 - background job; log and stop
            import logging

            logging.getLogger("journal_browser.admin").exception(
                "background deal-flags refresh failed"
            )
            return
        if not _flags_rerun:
            return


async def _get_deal_or_404(session: AsyncSession, deal_id: int) -> Deal:
    deal = await session.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, f"unknown deal: {deal_id}")
    return deal


@router.get("/deals")
async def list_deals(session: SessionDep, _: AdminDep) -> list[dict[str, Any]]:
    counts = (
        select(DealJournal.deal_id, func.count().label("n"))
        .where(DealJournal.excluded.is_(False))
        .group_by(DealJournal.deal_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(Deal, Publisher.name, func.coalesce(counts.c.n, 0))
            .outerjoin(Publisher, Publisher.id == Deal.publisher_id)
            .outerjoin(counts, counts.c.deal_id == Deal.id)
            .order_by(Publisher.name, Deal.id)
        )
    ).all()
    participations: dict[int, list[str]] = {}
    for deal_id, code in (
        await session.execute(
            select(DealInstitution.deal_id, Institution.code)
            .join(Institution, Institution.id == DealInstitution.institution_id)
            # Registry institutions (no code) participate in JCT deals but
            # are not hosted here; a null code breaks the string[] contract.
            .where(Institution.code.is_not(None))
            .order_by(Institution.code)
        )
    ).all():
        participations.setdefault(deal_id, []).append(code)
    return [
        _deal_payload(deal, name, int(count), participations.get(deal.id, []))
        for deal, name, count in rows
    ]


@router.get("/deals/{deal_id}")
async def get_deal(deal_id: int, session: SessionDep, _: AdminDep) -> dict[str, Any]:
    await _get_deal_or_404(session, deal_id)
    return await _deal_detail(session, deal_id)


class DealCreate(BaseModel):
    publisher_id: int | None = None
    publisher_name: str | None = None
    esac_id: str | None = None
    status: str = "current"
    start_year: int | None = None
    end_year: int | None = None
    corresponding_authors_only: bool | None = None


@router.post("/deals", status_code=201)
async def create_deal(body: DealCreate, session: SessionDep, _: AdminDep) -> dict[str, Any]:
    _validate_deal_field("status", body.status)
    if body.publisher_id is None and not body.publisher_name:
        raise HTTPException(422, "publisher_id or publisher_name is required")
    if body.esac_id is not None:
        clash = await session.scalar(select(Deal.id).where(Deal.esac_id == body.esac_id))
        if clash is not None:
            raise HTTPException(409, f"esac_id already in use by deal {clash}")
    publisher_id = body.publisher_id
    if publisher_id is None:
        pub = Publisher(name=body.publisher_name)
        session.add(pub)
        await session.flush()
        publisher_id = pub.id
    elif await session.get(Publisher, publisher_id) is None:
        raise HTTPException(404, f"unknown publisher: {publisher_id}")
    deal = Deal(
        publisher_id=publisher_id,
        esac_id=body.esac_id,
        status=body.status,
        start_year=body.start_year,
        end_year=body.end_year,
        corresponding_authors_only=body.corresponding_authors_only,
    )
    session.add(deal)
    await session.commit()
    _schedule_flags_refresh()
    return await _deal_detail(session, deal.id)


@router.put("/deals/{deal_id}")
async def update_deal(
    deal_id: int, body: dict[str, Any], session: SessionDep, _: AdminDep
) -> dict[str, Any]:
    deal = await _get_deal_or_404(session, deal_id)
    for key, value in body.items():
        if key not in DEAL_EDITABLE:
            raise HTTPException(400, f"unknown or immutable deal field: {key}")
        _validate_deal_field(key, value)
    if body.get("esac_id") not in (None, deal.esac_id):
        clash = await session.scalar(
            select(Deal.id).where(Deal.esac_id == body["esac_id"], Deal.id != deal_id)
        )
        if clash is not None:
            raise HTTPException(409, f"esac_id already in use by deal {clash}")
    if (
        "publisher_id" in body
        and body["publisher_id"] != deal.publisher_id
        and await session.get(Publisher, body["publisher_id"]) is None
    ):
        raise HTTPException(404, f"unknown publisher: {body['publisher_id']}")
    changed = {k: v for k, v in body.items() if getattr(deal, k) != v}
    if not changed:
        return await _deal_detail(session, deal_id)
    for key, value in changed.items():
        setattr(deal, key, value)
    # A human reviewed the deal: clear the curation flag and pin the date.
    # (needs_curation sticks because the openaccess.nl harvester re-applies
    # overrides for it; last_reviewed stays JCT-owned by design.)
    if deal.needs_curation:
        changed["needs_curation"] = False
        changed["needs_curation_reason"] = None
        deal.needs_curation = False
        deal.needs_curation_reason = None
    deal.last_reviewed = date.today()
    for field, value in changed.items():
        await session.execute(
            pg_insert(ManualOverride)
            .values(table_name="deals", row_key=str(deal_id), field=field, value=value)
            .on_conflict_do_update(
                index_elements=["table_name", "row_key", "field"],
                set_={"value": value, "set_at": func.now()},
            )
        )
    await session.commit()
    _schedule_flags_refresh()
    return await _deal_detail(session, deal_id)


class DealJournalAdd(BaseModel):
    issn: str
    journal_name: str | None = None


class DealJournalsBody(BaseModel):
    add: list[DealJournalAdd] = []
    remove: list[str] = []


class DealParticipationsBody(BaseModel):
    add: list[str] = []
    remove: list[str] = []


def _norm_issn_or_400(raw: str) -> str:
    issn = normalize_issn(raw)
    if issn is None:
        raise HTTPException(400, f"invalid ISSN: {raw!r}")
    return issn


async def _resolve_issn_l(session: AsyncSession, issn: str) -> str | None:
    issn_l = await session.scalar(select(Journal.issn_l).where(Journal.issn_l == issn))
    if issn_l is None:
        issn_l = await session.scalar(select(IssnMap.issn_l).where(IssnMap.issn == issn))
    return issn_l


@router.put("/deals/{deal_id}/journals")
async def update_deal_journals(
    deal_id: int, body: DealJournalsBody, session: SessionDep, _: AdminDep
) -> dict[str, Any]:
    await _get_deal_or_404(session, deal_id)
    for add in body.add:
        issn = _norm_issn_or_400(add.issn)
        issn_l = await _resolve_issn_l(session, issn)
        updates: dict[str, Any] = {"excluded": False, "issn_l": issn_l}
        if add.journal_name:
            updates["journal_name"] = add.journal_name
        await session.execute(
            pg_insert(DealJournal)
            .values(
                deal_id=deal_id,
                issn=issn,
                issn_l=issn_l,
                journal_name=add.journal_name,
                source="manual",
                excluded=False,
            )
            .on_conflict_do_update(
                index_elements=["deal_id", "issn"],
                index_where=text("institution_id IS NULL"),
                set_=updates,
            )
        )
    if body.remove:
        # Flag, never delete: a deleted row would be re-inserted by the
        # next JCT harvest.
        await session.execute(
            update(DealJournal)
            .where(
                DealJournal.deal_id == deal_id,
                DealJournal.issn.in_([_norm_issn_or_400(raw) for raw in body.remove]),
            )
            .values(excluded=True)
        )
    await session.commit()
    _schedule_flags_refresh()
    return await _deal_detail(session, deal_id)


@router.put("/deals/{deal_id}/participations")
async def update_deal_participations(
    deal_id: int, body: DealParticipationsBody, session: SessionDep, _: AdminDep
) -> dict[str, Any]:
    await _get_deal_or_404(session, deal_id)
    for code in body.remove:
        inst = await get_institution_by_code(session, code)
        if inst is None:
            raise HTTPException(404, f"unknown institution: {code}")
        await session.execute(
            delete(DealInstitution).where(
                DealInstitution.deal_id == deal_id, DealInstitution.institution_id == inst.id
            )
        )
        # Tombstone: the JCT harvester re-inserts sheet participations on every
        # run, so a removal is recorded as an override it must respect.
        await session.execute(
            pg_insert(ManualOverride)
            .values(
                table_name="deal_institutions",
                row_key=f"{deal_id}:{inst.id}",
                field="removed",
                value=True,
            )
            .on_conflict_do_update(
                index_elements=["table_name", "row_key", "field"], set_={"value": True}
            )
        )
    for code in body.add:
        inst = await get_institution_by_code(session, code)
        if inst is None:
            raise HTTPException(404, f"unknown institution: {code}")
        await session.execute(
            pg_insert(DealInstitution)
            .values(deal_id=deal_id, institution_id=inst.id)
            .on_conflict_do_nothing(index_elements=["deal_id", "institution_id"])
        )
        # Re-adding clears any removal tombstone so JCT can manage it again.
        await session.execute(
            delete(ManualOverride).where(
                ManualOverride.table_name == "deal_institutions",
                ManualOverride.row_key == f"{deal_id}:{inst.id}",
            )
        )
    await session.commit()
    _schedule_flags_refresh()
    return await _deal_detail(session, deal_id)
