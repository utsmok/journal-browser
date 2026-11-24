import os
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import (
    get_settings,
    load_settings_yaml,
    reset_settings_cache,
    settings_yaml_path,
)
from ...harvest.common import normalize_issn
from ...harvest.denorm import refresh_institution_stats
from ...harvest.institution_stats import write_pure_canon_stats
from ...models import Institution, JournalFlags
from ...schemas import AdminInstitutionOut
from ...settings_schema import SETTINGS_REGISTRY, value_for_response
from .audit_rows import MASKED, audit_row
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
async def update_settings(body: SettingsUpdate, session: SessionDep, _: AdminDep) -> dict[str, Any]:
    fields = {f.key: f for f in SETTINGS_REGISTRY}
    doc = load_settings_yaml()
    changes: list[tuple[str, Any, Any, bool]] = []  # (key, old, new, masked)
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
                raise HTTPException(400, "ignored_issns: entries must be valid ISSNs")
            value = normalized
        old = doc.get(key)
        unchanged = (
            isinstance(value, list) and isinstance(old, list) and sorted(old) == sorted(value)
        ) or old == value
        if not unchanged:
            changes.append((key, old, value, f.type == "secret"))
        doc[key] = value
    _write_settings_yaml(doc)
    for key, old, new, masked in changes:
        # Secret-valued settings are recorded as "(masked)" on both sides:
        # the audit log must never hold a password (or an old one).
        session.add(
            audit_row(
                table_name="settings",
                row_key={"key": key},
                field=key,
                old=MASKED if masked and old is not None else old,
                new=MASKED if masked else new,
            )
        )
    await session.commit()
    reset_settings_cache()
    return _settings_payload()


class InstitutionUpdate(BaseModel):
    """PATCH-shaped PUT body: absent fields are untouched, explicit null
    clears nullable columns, and the three non-nullable fields reject null."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    short_name: str | None = None
    ror: str | None = None
    openalex_id: str | None = None
    pure_oai_base_url: str | None = None
    openaire_org_id: str | None = None
    data_window_start: int | None = None
    data_window_end: int | None = None

    @field_validator("data_window_end", mode="before")
    @classmethod
    def _window_end_zero_means_open(cls, v: object) -> object:
        # The column is nullable and the help text says empty = open; 0 is
        # the same sentinel Settings accepts from JB_DATA_WINDOW_END.
        return None if v in (0, "0", "") else v

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
            for key in ("name", "data_window_start", "active"):
                if key in data and data[key] is None:
                    raise ValueError(f"{key} must not be null")
        return data


def _institution_payload(
    inst: Institution, *, rematerialized_journals: int | None = None
) -> dict[str, Any]:
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
        "rematerialized_journals": rematerialized_journals,
    }


async def get_institution_or_404(session: AsyncSession, code: str) -> Institution:
    inst = (
        await session.execute(select(Institution).where(Institution.code == code))
    ).scalar_one_or_none()
    if inst is None:
        raise HTTPException(404, f"unknown institution: {code}")
    return inst


@router.get("/institutions/{code}", response_model=AdminInstitutionOut)
async def get_institution(code: str, session: SessionDep, _: AdminDep) -> dict[str, Any]:
    return _institution_payload(await get_institution_or_404(session, code))


@router.put("/institutions/{code}", response_model=AdminInstitutionOut)
async def update_institution(
    code: str, body: InstitutionUpdate, session: SessionDep, _: AdminDep
) -> dict[str, Any]:
    inst = await get_institution_or_404(session, code)
    window_changed = bool(body.model_fields_set & {"data_window_start", "data_window_end"})
    was_active = inst.active
    # Merged window check: a one-sided body must also be validated against
    # the stored value, or {"data_window_end": 2010} on a 2020-start row
    # would still store an inverted range.
    start = (
        body.data_window_start
        if "data_window_start" in body.model_fields_set
        else inst.data_window_start
    )
    end = (
        body.data_window_end if "data_window_end" in body.model_fields_set else inst.data_window_end
    )
    if start is not None and end is not None and end < start:
        raise HTTPException(
            400,
            f"data_window_end {end} is before data_window_start {start}; "
            "set both ends consistently",
        )
    olds = {
        key: getattr(inst, key)
        for key in body.model_fields_set
        if getattr(inst, key) != getattr(body, key)
    }
    for key in body.model_fields_set:
        setattr(inst, key, getattr(body, key))
    rematerialized_journals: int | None = None
    if was_active and not inst.active:
        # Inactive institutions are not served, so their per-journal flags
        # rows (denorm search state) go with the flip. Reactivation is NOT
        # lazy anymore: the activate path below re-materializes the rows in
        # the same request, so /{code}/journals never serves empty-with-200
        # until the nightly wave (2026-11-19 sweep finding 2).
        await session.execute(delete(JournalFlags).where(JournalFlags.institution_id == inst.id))
    elif inst.active and (window_changed or not was_active):
        # works_count is window-bounded, so the card goes stale the moment
        # the window moves; a freshly reactivated row has no flags rows at
        # all. Both cases rebuild the canon stats rows and flags in this
        # request's transaction. The OpenAlex OA split keeps its old window
        # until the next stats job — that cross-check dimension is not the
        # card number.
        await write_pure_canon_stats(session, inst)
        await refresh_institution_stats(session, inst)
        rematerialized_journals = int(
            await session.scalar(
                select(func.count())
                .select_from(JournalFlags)
                .where(JournalFlags.institution_id == inst.id)
            )
            or 0
        )
    for key, old in olds.items():
        session.add(
            audit_row(
                table_name="institutions",
                row_key={"code": code},
                field=key,
                old=old,
                new=getattr(inst, key),
            )
        )
    await session.commit()
    return _institution_payload(inst, rematerialized_journals=rematerialized_journals)
