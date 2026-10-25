"""/api/v1/admin: password-protected harvest inspection (read-only).

POST /admin/login exchanges the JB_ADMIN_PASSWORD for a stateless HMAC
bearer token (12 h). GET endpoints show recent harvest runs with their
stats, deals flagged for curation, and the effective non-secret settings.
Nothing here edits state: environment changes belong in .env plus a
compose restart, so the panel can never drift from the deployment.
"""

import hashlib
import hmac
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..models import Deal, DealJournal, HarvestRun, Publisher

router = APIRouter(prefix="/admin", tags=["admin"])

TOKEN_TTL = 12 * 3600


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
async def list_runs(session: SessionDep, _: AdminDep, limit: int = 100) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                select(HarvestRun).order_by(desc(HarvestRun.id)).limit(min(limit, 500))
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id,
            "source": r.source,
            "entity_type": r.entity_type,
            "status": r.status,
            "started_at": r.started_at,
            "finished_at": r.finished_at,
            "stats": r.stats,
        }
        for r in rows
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
        (
            await session.execute(
                select(Deal, Publisher.name, journal_count)
                .join(Publisher, Publisher.id == Deal.publisher_id)
                .where(Deal.needs_curation.is_(True))
                .order_by(Deal.status.desc(), Publisher.name)
            )
        )
        .all()
    )
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


@router.get("/settings")
async def effective_settings(_: AdminDep) -> dict[str, Any]:
    s = get_settings()
    return {
        "institution_name": s.institution_name,
        "institution_ror": s.institution_ror,
        "pure_oai_base_url": s.pure_oai_base_url,
        "openaire_org_id": s.openaire_org_id,
        "data_window_start": s.data_window_start,
        "data_window_end": s.data_window_end,
        "bootstrap": s.bootstrap,
        "contact_email": s.contact_email,
        "has_openalex_key": bool(s.openalex_api_key),
        "has_ut_metadata": bool(s.ut_metadata_dsn),
        "landing_dir": s.landing_dir,
        "enable_journal_citations": s.enable_journal_citations,
        "enable_jisc": s.enable_jisc,
    }
