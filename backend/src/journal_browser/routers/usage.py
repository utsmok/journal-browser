"""Anonymous usage tracking: POST /api/v1/usage/events from the frontend
tracker. One batch INSERT; the `enable_usage_tracking` flag gates all
writes. No response body, no user accounts, no cookies — the client mints
its own session id.
"""

import ipaddress
import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..models import UsageEvent

router = APIRouter(prefix="/usage", tags=["usage"])

MAX_FILTERS_BYTES = 4096
MAX_EVENTS = 100
UA_MAX = 512

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class ClientInfo(BaseModel):
    tz: str | None = Field(default=None, max_length=64)
    locale: str | None = Field(default=None, max_length=32)


class PageViewIn(BaseModel):
    type: Literal["page_view"]
    session_id: str = Field(max_length=64)
    path: str = Field(max_length=512)
    duration_ms: int | None = None
    referrer: str | None = Field(default=None, max_length=512)
    ref_type: Literal["journal", "funder", "author", "orgunit", "publisher"] | None = None
    ref_id: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def _refs_go_together(self) -> "PageViewIn":
        if (self.ref_type is None) != (self.ref_id is None):
            raise ValueError("ref_type and ref_id must be given together")
        return self


class SearchIn(BaseModel):
    type: Literal["search"]
    session_id: str = Field(max_length=64)
    path: str = Field(max_length=512)
    query: str | None = Field(default=None, max_length=512)
    results_count: int | None = None
    search_scope: Literal["journals", "funders", "authors", "publishers", "orgunits"] | None = None
    filters: dict[str, Any] | None = None


class ErrorIn(BaseModel):
    type: Literal["error"]
    session_id: str = Field(max_length=64)
    path: str = Field(max_length=512)
    source: Literal["js_error", "unhandled_rejection", "api_status"]
    message: str | None = Field(default=None, max_length=1024)
    detail: str | None = Field(default=None, max_length=1024)
    status: int | None = None


class UsageBatchIn(BaseModel):
    client: ClientInfo | None = None
    events: list[Annotated[PageViewIn | SearchIn | ErrorIn, Field(discriminator="type")]] = Field(
        max_length=MAX_EVENTS
    )


def _client_ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    raw = xff.split(",")[0].strip() if xff else (request.client.host if request.client else None)
    if not raw:
        return None
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


@router.post("/events", status_code=204)
async def create_events(body: UsageBatchIn, request: Request, session: SessionDep) -> Response:
    if not get_settings().enable_usage_tracking:
        return Response(status_code=204)

    ip = _client_ip(request)
    ua = (request.headers.get("user-agent") or "")[:UA_MAX] or None
    tz = body.client.tz if body.client else None
    locale = body.client.locale if body.client else None

    rows: list[UsageEvent] = []
    for ev in body.events:
        data = ev.model_dump()
        if data.get("filters") is not None and len(json.dumps(data["filters"])) > (
            MAX_FILTERS_BYTES
        ):
            raise HTTPException(413, "filters too large")
        data["event_type"] = data.pop("type")
        rows.append(UsageEvent(ip=ip, tz=tz, locale=locale, user_agent=ua, **data))
    session.add_all(rows)
    await session.commit()
    return Response(status_code=204)
