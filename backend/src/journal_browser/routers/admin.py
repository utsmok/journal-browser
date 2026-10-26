"""/api/v1/admin: password-protected harvest inspection and configuration.

POST /admin/login exchanges the admin password for a stateless HMAC
bearer token (12 h; the MAC secret derives from the current settings, so a
password change invalidates old tokens immediately). GET endpoints show
recent harvest runs and deals flagged for curation. GET/PUT /settings read
and write the settings.yaml overlay (reloaded live, no restart) and
GET/PUT /institutions/{code} the per-university configuration rows.
"""

import hashlib
import hmac
import os
import tempfile
import time
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import (
    get_settings,
    load_settings_yaml,
    reset_settings_cache,
    settings_yaml_path,
)
from ..db import get_session
from ..models import Deal, DealJournal, HarvestRun, Institution, Publisher
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
    """Atomic YAML write (tmp + rename) so readers never see a half file."""
    path = settings_yaml_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(doc, fh, sort_keys=True)
        os.replace(tmp_name, path)
    finally:
        Path(tmp_name).unlink(missing_ok=True)  # no-op after a successful replace


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
    "external_works_dsn": "secret",
    "data_window_start": "int",
    "data_window_end": "int",
    "library_url": "string",
    "oa_guide_url": "string",
    "support_email": "string",
    "admin_contact": "string",
    "research_portal_url": "string",
    "active": "bool",
    "is_default": "bool",
}
# String fields the DB allows to be NULL; explicit null clears the value.
INSTITUTION_NULLABLE = set(INSTITUTION_EDITABLE) - {
    "name",
    "data_window_start",
    "data_window_end",
    "active",
    "is_default",
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
        "external_works_dsn": MASK if inst.external_works_dsn else None,
        "data_window_start": inst.data_window_start,
        "data_window_end": inst.data_window_end,
        "library_url": inst.library_url,
        "oa_guide_url": inst.oa_guide_url,
        "support_email": inst.support_email,
        "admin_contact": inst.admin_contact,
        "research_portal_url": inst.research_portal_url,
        "active": inst.active,
        "is_default": inst.is_default,
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
    # Empty or masked DSN = keep the existing one.
    if updates.get("external_works_dsn") in ("", MASK):
        updates.pop("external_works_dsn")
    for key, value in updates.items():
        setattr(inst, key, value)
    await session.commit()
    return _institution_payload(inst)
