import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager, suppress

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import __version__
from .config import get_settings
from .db import get_engine, get_session
from .logging_setup import REQUEST_ID_HEADER, configure_logging, new_request_id, request_id_ctx
from .routers import (
    admin,
    authors,
    deals,
    docs,
    feedback,
    funders,
    institutions,
    journals,
    meta,
    orgunits,
    publishers,
    usage,
)

logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(institutions.router)
# Admin before the scoped router: /admin/deals must not be captured by
# /{institution_code}/deals.
api_router.include_router(admin.router)
# Feedback intake before the scoped router, same reason as /admin.
api_router.include_router(feedback.router)
# Docs before the scoped router, same reason as /admin: /api/v1/docs must
# not be captured by /{institution_code}.
api_router.include_router(docs.router)
# Usage intake before the scoped router, same reason as /admin.
api_router.include_router(usage.router)
# Institution-scoped surface: /api/v1/{code}/journals|deals|meta/...
scoped_router = APIRouter(prefix="/{institution_code}")
scoped_router.include_router(journals.router)
scoped_router.include_router(funders.router)
scoped_router.include_router(authors.router)
scoped_router.include_router(publishers.router)
scoped_router.include_router(orgunits.router)
scoped_router.include_router(deals.router)
scoped_router.include_router(meta.router)
api_router.include_router(scoped_router)


@api_router.get("/healthz")
async def healthz(session: AsyncSession = Depends(get_session)) -> dict:
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "version": __version__}


class RequestObservabilityMiddleware:
    """Outermost ASGI middleware: adopt an inbound X-Request-ID (or mint
    one), echo it on the response, and write one line per request with
    method, path, status, and duration. configure_logging() puts the id on
    every log line emitted while the request runs, so server errors and
    harvest logs become greppable to the same id."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = _inbound_request_id(scope) or new_request_id()
        token = request_id_ctx.set(rid)
        started = time.perf_counter()
        status: int | None = None

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, rid)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            request_id_ctx.reset(token)
            logger.info(
                "%s %s -> %s (%s ms)",
                scope.get("method", "-"),
                scope.get("path", "-"),
                status if status is not None else "no-response",
                elapsed_ms,
            )


def _inbound_request_id(scope: Scope) -> str | None:
    for key, value in scope.get("headers") or []:
        if key == REQUEST_ID_HEADER.encode():
            candidate = value.decode("latin-1").strip()
            if candidate and len(candidate) <= 128:
                return candidate
    return None


def _warm_embedding_model() -> None:
    """Load the ~130 MB ONNX query encoder off the request path, so the
    first semantic search after a restart does not pay the model load.
    JB_SKIP_EMBEDDING_WARMUP=1 skips the load (offline schema dumps, CI)."""
    if os.environ.get("JB_SKIP_EMBEDDING_WARMUP") == "1":
        return
    import threading

    from .services.embeddings import encode_query

    threading.Thread(target=lambda: encode_query("warmup"), daemon=True).start()


USAGE_PRUNE_FIRST_DELAY_S = 60
USAGE_PRUNE_INTERVAL_S = 24 * 60 * 60
VECTOR_WARM_DELAY_S = 5


async def _warm_vector_index_task() -> None:
    """Pre-walk the journals HNSW graph once after boot: the first author
    pages after a restart otherwise pay seconds of cold random reads on
    the ~350 MB vector index before it lands in the page cache. Errors
    are logged, never propagated (fresh deployments may have no
    embeddings yet)."""
    if os.environ.get("JB_SKIP_EMBEDDING_WARMUP") == "1":
        return
    await asyncio.sleep(VECTOR_WARM_DELAY_S)
    try:
        from .services.embeddings import warm_journal_vector_index

        async with async_sessionmaker(get_engine(), expire_on_commit=False)() as session:
            ran = await warm_journal_vector_index(session)
            await session.commit()
        logger.info("vector index warm: %d hnsw search(es)", ran)
    except Exception:
        logger.exception("vector index warm failed")


async def _usage_ip_retention_loop(days: int) -> None:
    """Nightly: null raw usage-event IPs older than `days` (rows and
    country stay). Errors are logged, never propagated."""
    from .services.usage_retention import prune_old_ips

    delay = USAGE_PRUNE_FIRST_DELAY_S
    while True:
        await asyncio.sleep(delay)
        try:
            async with async_sessionmaker(get_engine(), expire_on_commit=False)() as session:
                nulled = await prune_old_ips(session, days)
            logger.info("usage ip retention: nulled ip on %d event(s)", nulled)
        except Exception:
            logger.exception("usage ip retention run failed")
        # Subsequent runs are a full day apart; only the first waits 60s.
        delay = USAGE_PRUNE_INTERVAL_S


@asynccontextmanager
async def _lifespan(app: FastAPI):
    days = get_settings().usage_retention_days
    task = asyncio.create_task(_usage_ip_retention_loop(days)) if days > 0 else None
    warm_task = asyncio.create_task(_warm_vector_index_task())
    yield
    for t in (task, warm_task):
        if t is not None:
            t.cancel()
            with suppress(asyncio.CancelledError):
                await t


def create_app() -> "FastAPI":
    settings = get_settings()
    configure_logging()
    app = FastAPI(title="Journal Browser API", version=__version__, lifespan=_lifespan)
    # CORS first, observability second: add_middleware prepends, so the
    # request-id middleware runs outermost and even CORS-rejected requests
    # get a request id.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestObservabilityMiddleware)
    app.include_router(api_router)

    # parse_cursor and friends raise ValueError for malformed input; map it
    # to 400. FastAPI's own RequestValidationError (422) handles params it
    # validates at the boundary.
    @app.exception_handler(ValueError)
    async def value_error_to_400(request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    _warm_embedding_model()
    return app


app = create_app()
