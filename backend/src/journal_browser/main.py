import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager, suppress

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
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
    collaborations,
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
scoped_router.include_router(collaborations.router)
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
SNAPSHOT_WARM_DELAY_S = 2
SNAPSHOT_REFRESH_INTERVAL_S = 6 * 3600


async def _warm_snapshots_task() -> None:
    """Build list snapshots, default browse facets, and fast detail bundles
    for every institution with authors after boot and every six hours."""
    # Boot warmers skip wholesale in CI and offline dumps.
    if os.environ.get("JB_SKIP_EMBEDDING_WARMUP") == "1":
        return
    await asyncio.sleep(SNAPSHOT_WARM_DELAY_S)
    while True:
        try:
            from datetime import UTC, datetime

            from .models import Author, Institution
            from .routers import deals as deals_router
            from .services import authors, collaborations, funders, orgunits, publishers
            from .services.cache import SWR_CACHE, swr_put
            from .services.search import search_journals
            from .services.works_query import clamped_year_range

            async with async_sessionmaker(get_engine(), expire_on_commit=False)() as session:
                subq = select(Author.institution_id).distinct()
                rows = await session.scalars(select(Institution).where(Institution.id.in_(subq)))
                insts = rows.all()
                cur_year = datetime.now(UTC).year
                for inst in insts:
                    fac_res = await orgunits.search_orgunits(
                        session, institution=inst, level="faculty"
                    )
                    pub_res = await publishers.search_publishers(session, institution_id=inst.id)
                    await authors.search_authors(
                        session,
                        inst.id,
                        None,
                        limit=20,
                        require_confirmed=inst.require_confirmed_affiliation,
                    )
                    await search_journals(session, institution_id=inst.id, limit=1)

                    # Warm deals, funders, collaborations, and Last-5-Years presets.
                    try:
                        epoch_d, built_d = await deals_router._build_deals_list(
                            session, inst, "current"
                        )
                        swr_put(SWR_CACHE, ("deals_list", inst.id, "current"), epoch_d, built_d)
                    except Exception:
                        logger.exception("warm deals failed for %s", inst.code)

                    try:
                        canon = await funders.canon_links(session)
                        await funders.ut_work_counts(session, inst)
                        await funders.ut_funder_work_counts(session, inst, canon.bare_ids)
                    except Exception:
                        logger.exception("warm funders failed for %s", inst.code)

                    try:
                        await collaborations.search_collaborations(
                            session,
                            inst,
                            collaborations.CollaborationFilters(),
                            sort="works",
                            direction="desc",
                            offset=0,
                            limit=25,
                            include_facets=True,
                        )
                    except Exception:
                        logger.exception("warm collaborations failed for %s", inst.code)

                    last5_end = min(inst.data_window_end or cur_year, cur_year)
                    last5_start = max(inst.data_window_start, last5_end - 4)
                    last5 = clamped_year_range(inst, last5_start, last5_end)
                    if last5 is not None:
                        try:
                            await publishers.search_publishers(
                                session, institution_id=inst.id, years=last5, include_facets=False
                            )
                            await orgunits.search_orgunits(
                                session, institution=inst, level="faculty", year_range=last5
                            )
                            await search_journals(
                                session,
                                institution_id=inst.id,
                                limit=1,
                                year_from=last5[0],
                                year_to=last5[1],
                            )
                        except Exception:
                            logger.exception("warm last5 failed for %s", inst.code)

                    # Warm lightweight detail bundles (include_gaps=False) so first visits are
                    # instant.
                    for unit in fac_res.get("items", []):
                        uname = unit.get("name")
                        if uname:
                            try:
                                await orgunits.orgunit_detail(
                                    session, inst, "faculty", uname, include_gaps=False
                                )
                            except Exception:
                                logger.exception("warm faculty detail %s failed", uname)

                    for pub in pub_res.get("items", [])[:10]:
                        pname = pub.get("name")
                        if pname:
                            try:
                                await publishers.publisher_detail(
                                    session, inst, pname, include_gaps=False
                                )
                            except Exception:
                                logger.exception("warm publisher detail %s failed", pname)

            logger.info("snapshot warm: %d institution(s)", len(insts))
        except Exception:
            logger.exception("snapshot warm failed")
        # 6h beats the caches' 86400s TTL, and a harvest bump changes the
        # cache_epoch cache key: the next pass rebuilds the new key in the
        # background, so no visitor pays a cold build.
        await asyncio.sleep(SNAPSHOT_REFRESH_INTERVAL_S)


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
    snapshot_task = asyncio.create_task(_warm_snapshots_task())
    yield
    for t in (task, warm_task, snapshot_task):
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
