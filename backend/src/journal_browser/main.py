from fastapi import APIRouter, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import __version__
from .config import get_settings
from .db import get_session
from .routers import admin, deals, journals, meta

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(journals.router)
api_router.include_router(deals.router)
api_router.include_router(meta.router)
api_router.include_router(admin.router)


@api_router.get("/healthz")
async def healthz(session: AsyncSession = Depends(get_session)) -> dict:
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "version": __version__}


def create_app() -> "FastAPI":  # noqa: F821
    from fastapi import FastAPI

    settings = get_settings()
    app = FastAPI(title="Journal Browser API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    return app


app = create_app()
