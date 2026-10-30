import hashlib
import hmac
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...db import get_session

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
