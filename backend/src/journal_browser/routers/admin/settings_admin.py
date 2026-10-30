import os
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import (
    get_settings,
    load_settings_yaml,
    reset_settings_cache,
    settings_yaml_path,
)
from ...harvest.common import normalize_issn
from ...models import Institution
from ...schemas import AdminInstitutionOut
from ...settings_schema import SETTINGS_REGISTRY, value_for_response
from .auth import AdminDep, SessionDep

router = APIRouter(prefix="/admin", tags=["admin"])

MASK = "********"


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


class InstitutionUpdate(BaseModel):
    """PATCH-shaped PUT body: absent fields are untouched, explicit null
    clears nullable columns, and the four non-nullable fields reject null."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    short_name: str | None = None
    ror: str | None = None
    openalex_id: str | None = None
    pure_oai_base_url: str | None = None
    openaire_org_id: str | None = None
    data_window_start: int | None = None
    data_window_end: int | None = None
    library_url: str | None = None
    oa_guide_url: str | None = None
    support_email: str | None = None
    admin_contact: str | None = None
    research_portal_url: str | None = None
    active: StrictBool | None = None
    require_confirmed_affiliation: StrictBool | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_cleared_nonnullable(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for key in ("name", "data_window_start", "data_window_end", "active"):
                if key in data and data[key] is None:
                    raise ValueError(f"{key} must not be null")
        return data


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


@router.get("/institutions/{code}", response_model=AdminInstitutionOut)
async def get_institution(
    code: str, session: SessionDep, _: AdminDep
) -> dict[str, Any]:
    return _institution_payload(await _get_institution_or_404(session, code))


@router.put("/institutions/{code}", response_model=AdminInstitutionOut)
async def update_institution(
    code: str, body: InstitutionUpdate, session: SessionDep, _: AdminDep
) -> dict[str, Any]:
    inst = await _get_institution_or_404(session, code)
    for key in body.model_fields_set:
        setattr(inst, key, getattr(body, key))
    await session.commit()
    return _institution_payload(inst)
