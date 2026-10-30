import os

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import __version__
from .config import get_settings
from .db import get_session
from .routers import (
    admin,
    authors,
    deals,
    docs,
    feedback,
    institutions,
    journals,
    meta,
    orgunits,
    publishers,
)

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
# Institution-scoped surface: /api/v1/{code}/journals|deals|meta/...
scoped_router = APIRouter(prefix="/{institution_code}")
scoped_router.include_router(journals.router)
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


def _warm_embedding_model() -> None:
    """Load the ~130 MB ONNX query encoder off the request path, so the
    first semantic search after a restart does not pay the model load.
    JB_SKIP_EMBEDDING_WARMUP=1 skips the load (offline schema dumps, CI)."""
    if os.environ.get("JB_SKIP_EMBEDDING_WARMUP") == "1":
        return
    import threading

    from .services.embeddings import encode_query

    threading.Thread(target=lambda: encode_query("warmup"), daemon=True).start()


def create_app() -> "FastAPI":
    settings = get_settings()
    app = FastAPI(title="Journal Browser API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
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
