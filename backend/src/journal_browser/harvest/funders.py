"""Funder canon: OpenAlex + OpenAIRE sweeps and the JISC link matrix.

Identifier canon shared by all three tables: ror is the bare lowercase
ROR id ("04ad7pn51"), fundref the bare FundRef number ("100009795").
"""

import json
import logging
import re
from typing import Any

from aletheca import AlethecaClient
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from journal_browser.config import get_settings
from journal_browser.models import JiscFunder, OpenaireFunder, OpenalexFunder

try:
    from aireloom import AireloomClient
except ImportError:  # pragma: no cover
    AireloomClient = None

logger = logging.getLogger(__name__)

SWEEP_PAGE = 200  # aletheca cursor page size
OPENAIRE_PAGE_SIZE = 100  # OpenAIRE graph v3 pageSize maximum
UPSERT_CHUNK = 2_000  # asyncpg caps statements at 32,767 binds

_ROR_RE = re.compile(r"ror\.org/(0[0-9a-z]{8})", re.IGNORECASE)
_FUNDREF_RE = re.compile(r"10\.13039/(\d{6,})", re.IGNORECASE)
_BARE_FUNDREF_RE = re.compile(r"^\d{6,}$")


def normalize_ror(*values: Any) -> str | None:
    """Bare lowercase ROR id from any candidate string, else None."""
    for v in values:
        if v and (m := _ROR_RE.search(str(v))):
            return m.group(1).lower()
    return None


def normalize_fundref(*values: Any) -> str | None:
    """Bare FundRef number ("100009795") from a DOI-prefixed or bare
    numeric string, else None."""
    for v in values:
        s = str(v).strip() if v else ""
        if _BARE_FUNDREF_RE.fullmatch(s):
            return s
        if m := _FUNDREF_RE.search(s):
            return m.group(1)
    return None


async def _upsert(session: AsyncSession, model: Any, pk: str, rows: list[dict[str, Any]]) -> int:
    """Chunked INSERT ... ON CONFLICT (pk) DO UPDATE; updated_at re-stamps
    to now() on every rerun."""
    for at in range(0, len(rows), UPSERT_CHUNK):
        chunk = rows[at : at + UPSERT_CHUNK]
        stmt = pg_insert(model.__table__).values(chunk)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[pk],
                set_={
                    **{c: getattr(stmt.excluded, c) for c in chunk[0] if c != pk},
                    "updated_at": text("now()"),
                },
            )
        )
    return len(rows)


def _openalex_row(f: Any) -> dict[str, Any]:
    """openalex_funders row from an aletheca Funder entity."""
    ids = getattr(f, "ids", None)

    def _id(key: str) -> Any:
        if isinstance(ids, dict):
            return ids.get(key)
        return getattr(ids, key, None)

    openalex_id = getattr(f, "id", None)
    if not openalex_id:
        raise RuntimeError("openalex sweep: funder row without id")
    return {
        "openalex_id": openalex_id,
        "ror": normalize_ror(_id("ror")),
        # OpenAlex has no "fundref" id key: the FundRef DOI lives under
        # ids.doi ("10.13039/...") with the bare number in ids.crossref.
        "fundref": normalize_fundref(_id("fundref"), _id("doi"), _id("crossref")),
        "display_name": getattr(f, "display_name", None),
        "country_code": getattr(f, "country_code", None),
        "description": getattr(f, "description", None),
        "grant_count": getattr(f, "awards_count", None),
        "works_count": getattr(f, "works_count", None),
        "cited_by_count": getattr(f, "cited_by_count", None),
    }


async def harvest_openalex_funders(session: AsyncSession) -> dict[str, int]:
    """Full OpenAlex funder sweep -> openalex_funders upsert. Idempotent:
    reruns refresh every row."""
    stats = {"seen": 0, "upserted": 0, "with_ror": 0, "with_fundref": 0}
    rows: list[dict[str, Any]] = []
    client_kwargs: dict[str, Any] = {}
    if api_key := get_settings().openalex_api_key:
        client_kwargs["api_key"] = api_key
    async with AlethecaClient(**client_kwargs) as client:
        async for f in client.funders.iterate(page_size=SWEEP_PAGE, on_error="raise"):
            rows.append(_openalex_row(f))
            stats["seen"] += 1
    if not rows:
        raise RuntimeError("openalex sweep: zero funders returned")
    stats["upserted"] = await _upsert(session, OpenalexFunder, "openalex_id", rows)
    stats["with_ror"] = sum(1 for r in rows if r["ror"])
    stats["with_fundref"] = sum(1 for r in rows if r["fundref"])
    logger.info("harvest_openalex_funders: %s", stats)
    return stats


def _openaire_row(item: dict[str, Any]) -> dict[str, Any]:
    """openaire_funders row from one graph v3 funder payload."""
    oid = str(item.get("id") or "").strip()
    if not oid:
        raise RuntimeError("openaire sweep: funder row without id")
    # ROR when obvious: website URL or any ror.org occurrence in the payload.
    return {
        "openaire_id": oid,
        "name": item.get("name"),
        "short_name": item.get("shortName"),
        "website_url": item.get("websiteUrl"),
        "jurisdiction": item.get("jurisdiction"),
        "ror": normalize_ror(item.get("websiteUrl"), json.dumps(item)),
    }


async def harvest_openaire_funders(session: AsyncSession) -> dict[str, int]:
    """OpenAIRE graph v3 funders page sweep -> openaire_funders upsert.
    Idempotent: reruns refresh every row."""
    if AireloomClient is None:  # pragma: no cover
        raise RuntimeError("openaire sweep: aireloom not installed")
    # Dormant: OpenAIRE Graph API exposes no funders endpoint (verified
    # 2026-11-02 against v1/v2/v3 + SKG-IF api-docs); funders exist only
    # embedded in projects.fundings[]; awaiting upstream endpoint.
    # Remove this guard when OpenAIRE ships /graph/v3/funders; the page
    # loop below lights up unchanged.
    raise RuntimeError(
        "openaire sweep: OpenAIRE Graph API exposes no funders endpoint "
        "(verified 2026-11-02 against v1/v2/v3 + SKG-IF api-docs); funders "
        "exist only embedded in projects.fundings[]; awaiting upstream endpoint"
    )
    stats = {"pages": 0, "seen": 0, "upserted": 0, "with_ror": 0}
    by_id: dict[str, dict[str, Any]] = {}
    async with AireloomClient() as client:
        page = 1
        while True:
            resp = await client.request(
                "GET", "funders", params={"page": page, "pageSize": OPENAIRE_PAGE_SIZE}, raw=True
            )
            data = resp.json() if hasattr(resp, "json") else resp
            if isinstance(data, dict):
                results = data.get("results") or (data.get("response") or {}).get("results")
            else:
                results = data
            if not isinstance(results, list):
                raise RuntimeError(f"openaire sweep: page {page} response shape unexpected")
            stats["pages"] += 1
            for item in results:
                row = _openaire_row(item)
                by_id[row["openaire_id"]] = row
            if len(results) < OPENAIRE_PAGE_SIZE:
                break
            page += 1
    rows = list(by_id.values())
    if not rows:
        raise RuntimeError("openaire sweep: zero funders returned")
    stats["seen"] = len(rows)
    stats["upserted"] = await _upsert(session, OpenaireFunder, "openaire_id", rows)
    stats["with_ror"] = sum(1 for r in rows if r["ror"])
    logger.info("harvest_openaire_funders: %s", stats)
    return stats


async def funder_link_matrix(session: AsyncSession) -> dict[str, int]:
    """How many jisc funders link to openalex/openaire canon via ror
    (and fundref -> openalex.fundref). Report only; no link table."""
    jisc = (await session.execute(select(JiscFunder.ror, JiscFunder.fundref))).all()
    jisc_ror = {r for (r, _) in jisc if r}
    jisc_fundref = {f for (_, f) in jisc if f}

    oa = (await session.execute(select(OpenalexFunder.ror, OpenalexFunder.fundref))).all()
    oa_ror = {r for (r, _) in oa if r}
    oa_fundref = {f for (_, f) in oa if f}

    aire_ror = {
        r
        for (r,) in (
            await session.execute(select(OpenaireFunder.ror).where(OpenaireFunder.ror.is_not(None)))
        ).all()
    }

    matrix = {
        "jisc_funders": len(jisc),
        "jisc_with_ror": len(jisc_ror),
        "jisc_with_fundref": len(jisc_fundref),
        "openalex_funders": len(oa),
        "openalex_with_ror": len(oa_ror),
        "openalex_with_fundref": len(oa_fundref),
        "openaire_funders": int(
            (
                await session.execute(select(func.count()).select_from(OpenaireFunder.__table__))
            ).scalar()
            or 0
        ),
        "openaire_with_ror": len(aire_ror),
        "jisc_ror_in_openalex": len(jisc_ror & oa_ror),
        "jisc_fundref_in_openalex": len(jisc_fundref & oa_fundref),
        "jisc_ror_in_openaire": len(jisc_ror & aire_ror),
        "jisc_ror_in_both_sources": len(jisc_ror & oa_ror & aire_ror),
    }
    logger.info("funder_link_matrix: %s", matrix)
    return matrix
