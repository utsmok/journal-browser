"""Per-client request limits for the public /api surface.

The site sits behind Cloudflare, Caddy and the Next.js /api rewrite, so the
TCP peer is the frontend container and the first X-Forwarded-For hop is a
Cloudflare edge. client_ip() therefore prefers CF-Connecting-IP. A request
with no forwarding headers from a private or loopback peer is internal
(Next.js server-side fetches, healthchecks, the test client) and is never
limited: public traffic always arrives through the proxies, which add them.

Counters are fixed 60-second windows held in process memory. The backend
runs one uvicorn worker, so the counts are exact for the deployment; a
restart resets them. The limits come from settings on every request, and a
limit of 0 turns its group off.
"""

import ipaddress
import json
import math
import time
from collections.abc import Callable, Mapping

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import get_settings

WINDOW_SECONDS = 60
# A spoofed header per request must not grow memory without bound: past
# this many tracked clients, stale windows are dropped, and if every entry
# is current the table is cleared (the limiter fails open, not closed).
MAX_TRACKED_KEYS = 50_000
# Feedback carries a page_data dump capped at 1 MB serialized; nothing else
# posts more than a few kilobytes.
MAX_BODY_BYTES = 2_000_000

# Endpoints that run the embedding model or stream a full CSV export.
_HEAVY_SUFFIXES = (".csv", "/similar", "/journals/semantic-search", "/journals/recommend")


def _parse_ip(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return str(ipaddress.ip_address(raw.strip()))
    except ValueError:
        return None


def client_ip(headers: Mapping[str, str], peer: str | None) -> str | None:
    """The originating client address: CF-Connecting-IP, else the first
    X-Forwarded-For hop, else the TCP peer. The first header present wins;
    an unparseable value yields None rather than a proxy's address."""
    if (cf := headers.get("cf-connecting-ip")) is not None:
        return _parse_ip(cf)
    if (xff := headers.get("x-forwarded-for")) is not None:
        return _parse_ip(xff.split(",")[0])
    return _parse_ip(peer)


def _is_internal(headers: Mapping[str, str], peer: str | None) -> bool:
    if "cf-connecting-ip" in headers or "x-forwarded-for" in headers:
        return False
    ip = _parse_ip(peer)
    return ip is not None and (
        ipaddress.ip_address(ip).is_private or ipaddress.ip_address(ip).is_loopback
    )


def limit_group(method: str, path: str) -> str | None:
    """The limit group a request counts against; None = not limited."""
    if not path.startswith("/api/") or method == "OPTIONS":
        return None
    if method == "POST" and path.rstrip("/") == "/api/v1/feedback":
        return "feedback"
    if path.endswith(_HEAVY_SUFFIXES):
        return "heavy"
    return "default"


def _group_limit(group: str) -> int:
    settings = get_settings()
    return {
        "default": settings.rate_limit_per_minute,
        "heavy": settings.rate_limit_heavy_per_minute,
        "feedback": settings.rate_limit_feedback_per_minute,
    }[group]


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        # (group, client) -> [window index, requests counted in it]
        self._counts: dict[tuple[str, str], list[int]] = {}

    def reset(self) -> None:
        self._counts.clear()

    def hit(self, group: str, client: str, limit: int) -> tuple[int, int | None]:
        """Count one request. Returns (remaining, retry_after); retry_after
        is None when the request is allowed."""
        now = self._clock()
        window = int(now // WINDOW_SECONDS)
        key = (group, client)
        entry = self._counts.get(key)
        if entry is None or entry[0] != window:
            if entry is None and len(self._counts) >= MAX_TRACKED_KEYS:
                self._evict(window)
            entry = [window, 0]
            self._counts[key] = entry
        if entry[1] >= limit:
            return 0, max(1, math.ceil((window + 1) * WINDOW_SECONDS - now))
        entry[1] += 1
        return limit - entry[1], None

    def _evict(self, window: int) -> None:
        self._counts = {k: v for k, v in self._counts.items() if v[0] == window}
        if len(self._counts) >= MAX_TRACKED_KEYS:
            self._counts.clear()


_limiter = RateLimiter()


def reset_rate_limiter() -> None:
    _limiter.reset()


async def _send_error(send: Send, status: int, detail: str, headers: dict[str, str]) -> None:
    body = json.dumps({"detail": detail}).encode()
    raw = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    raw += [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    await send({"type": "http.response.start", "status": status, "headers": raw})
    await send({"type": "http.response.body", "body": body})


class RateLimitMiddleware:
    """Rejects over-limit clients with 429 and oversized bodies with 413,
    and reports the remaining budget in RateLimit-* response headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        group = limit_group(scope["method"], scope["path"])
        headers = Headers(scope=scope)
        peer = scope["client"][0] if scope.get("client") else None
        if group is None or _is_internal(headers, peer):
            await self.app(scope, receive, send)
            return

        length = headers.get("content-length")
        if length is not None and length.isdigit() and int(length) > MAX_BODY_BYTES:
            await _send_error(send, 413, f"request body over {MAX_BODY_BYTES} bytes", {})
            return

        limit = _group_limit(group)
        if limit > 0:
            client = client_ip(headers, peer) or "unknown"
            remaining, retry_after = _limiter.hit(group, client, limit)
            if retry_after is not None:
                await _send_error(
                    send,
                    429,
                    f"rate limit exceeded: {limit} requests per minute for this "
                    f"endpoint group; retry in {retry_after} s",
                    {
                        "Retry-After": str(retry_after),
                        "RateLimit-Limit": str(limit),
                        "RateLimit-Remaining": "0",
                    },
                )
                return

            async def send_with_headers(message: Message) -> None:
                if message["type"] == "http.response.start":
                    out = MutableHeaders(scope=message)
                    out["RateLimit-Limit"] = str(limit)
                    out["RateLimit-Remaining"] = str(remaining)
                await send(message)
        else:
            send_with_headers = send

        received = 0

        async def capped_receive() -> Message:
            # Chunked bodies carry no Content-Length: count them as they
            # stream and end the request once they pass the cap.
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_BODY_BYTES:
                    return {"type": "http.disconnect"}
            return message

        await self.app(scope, capped_receive, send_with_headers)
