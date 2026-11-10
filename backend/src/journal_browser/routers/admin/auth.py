import hashlib
import hmac
import math
import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...db import get_session

router = APIRouter(prefix="/admin", tags=["admin"])

TOKEN_TTL = 12 * 3600

# Failed-login throttle: sliding 15-minute window, counted per client key
# and globally. Successful logins never count; the clock is injectable so
# tests can fast-forward and reset_login_limiter() isolates them.
FAIL_WINDOW_SECONDS = 15 * 60
MAX_FAILURES_PER_KEY = 5
MAX_FAILURES_GLOBAL = 50


class LoginRateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._by_key: defaultdict[str, deque[float]] = defaultdict(deque)
        self._global: deque[float] = deque()

    def reset(self) -> None:
        self._by_key.clear()
        self._global.clear()

    @staticmethod
    def _prune(failures: deque[float], now: float) -> None:
        while failures and now - failures[0] >= FAIL_WINDOW_SECONDS:
            failures.popleft()

    def retry_after(self, key: str) -> int | None:
        """Seconds until the next attempt may be checked; None when allowed."""
        now = self._clock()
        self._prune(self._global, now)
        failures = self._by_key.get(key)
        if failures is not None:
            self._prune(failures, now)
            if not failures:
                # Spoofable X-Forwarded-For keys must not grow memory.
                del self._by_key[key]
                failures = None
        if len(self._global) >= MAX_FAILURES_GLOBAL:
            return self._wait(self._global[0], now)
        if failures is not None and len(failures) >= MAX_FAILURES_PER_KEY:
            return self._wait(failures[0], now)
        return None

    @staticmethod
    def _wait(oldest: float, now: float) -> int:
        return max(1, math.ceil(oldest + FAIL_WINDOW_SECONDS - now))

    def record_failure(self, key: str) -> None:
        now = self._clock()
        self._global.append(now)
        self._by_key[key].append(now)


_limiter = LoginRateLimiter()


def reset_login_limiter() -> None:
    _limiter.reset()


def _client_key(request: Request) -> str:
    # The backend sits behind the frontend /api proxy, so request.client.host
    # is the proxy container; the real client arrives as the first
    # X-Forwarded-For hop.
    first_hop = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if first_hop:
        return first_hop
    return request.client.host if request.client else "unknown"


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
async def login(body: LoginIn, request: Request) -> dict[str, Any]:
    key = _client_key(request)
    retry_after = _limiter.retry_after(key)
    if retry_after is not None:
        raise HTTPException(
            429,
            "too many failed login attempts; retry later",
            headers={"Retry-After": str(retry_after)},
        )
    password = get_settings().admin_password
    if not password or not hmac.compare_digest(body.password, password):
        _limiter.record_failure(key)
        raise HTTPException(403, "wrong password or admin disabled")
    return {"token": _issue_token(), "expires_in": TOKEN_TTL}
