"""/api/v1/api-docs and /api/v1/openapi.json: the public API reference.

The public schema is the full app.openapi() schema cut down to the data
routes: the institution directory and the institution-scoped surface
(/api/v1/{code}/...), plus the component schemas those routes reference.
The admin, feedback, usage, health and in-app docs routes stay out of it.
The full schema, which the frontend types are generated from, still comes
from scripts/dump_openapi.py.
"""

import json
import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse

from ..config import get_settings

router = APIRouter(include_in_schema=False)

PUBLIC_SCHEMA_PATH = "/api/v1/openapi.json"
_SCHEMA_REF = re.compile(r'"#/components/schemas/([^"]+)"')

_DESCRIPTION = """\
Read-only access to the data behind Open Journal Browser: journals, open access
deals, publishers, funders, authors, organisational units and collaborations.

Most routes take an institution code as their first path segment. List the
available codes with `GET /api/v1/institutions`; the University of Twente is
`ut`. No API key is needed.

Each client IP address may make {default} requests per minute. CSV exports and
the semantic search, recommendation and similar-journal routes have a separate
limit of {heavy} requests per minute. Every response carries `RateLimit-Limit`
and `RateLimit-Remaining` headers. Over the limit, the API answers
`429 Too Many Requests` with a `Retry-After` header in seconds.

The API serves the Open Journal Browser website first, so response shapes can
change when the site changes. Questions and bulk data requests go to {contact}.
"""


def is_public_path(path: str) -> bool:
    return path == "/api/v1/institutions" or path.startswith("/api/v1/{institution_code}/")


def public_openapi(full: dict[str, Any]) -> dict[str, Any]:
    paths = {p: ops for p, ops in full["paths"].items() if is_public_path(p)}
    all_schemas = full.get("components", {}).get("schemas", {})
    # Keep only the component schemas the public paths reach, transitively.
    keep: set[str] = set()
    pending = set(_SCHEMA_REF.findall(json.dumps(paths)))
    while pending:
        name = pending.pop()
        if name in keep or name not in all_schemas:
            continue
        keep.add(name)
        pending |= set(_SCHEMA_REF.findall(json.dumps(all_schemas[name])))
    settings = get_settings()
    return {
        **full,
        "info": {
            **full["info"],
            "title": "Open Journal Browser API",
            "description": _DESCRIPTION.format(
                default=settings.rate_limit_per_minute,
                heavy=settings.rate_limit_heavy_per_minute,
                contact=settings.support_email,
            ),
        },
        "paths": paths,
        "components": {"schemas": {n: s for n, s in all_schemas.items() if n in keep}},
    }


@router.get("/openapi.json")
async def public_schema(request: Request) -> dict[str, Any]:
    return public_openapi(request.app.openapi())


@router.get("/api-docs")
async def public_docs() -> HTMLResponse:
    return get_swagger_ui_html(
        openapi_url=PUBLIC_SCHEMA_PATH, title="Open Journal Browser API reference"
    )
