"""Funder canon: OpenAlex + OpenAIRE sweeps and the JISC link matrix.

Identifier canon shared by all three tables: ror is the bare lowercase
ROR id ("04ad7pn51"), fundref the bare FundRef number ("100009795").
"""

import json
import logging
import re
from typing import Any

import httpx
from aletheca import AlethecaClient
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from journal_browser.config import get_settings
from journal_browser.models import (
    FunderLink,
    JiscFunder,
    OpenaireFunder,
    OpenaireFunderStream,
    OpenalexFunder,
)

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
    stats["funder_links"] = await refresh_funder_links(session)
    logger.info("harvest_openalex_funders: %s", stats)
    return stats


#: Curated OpenAIRE funder codes for the canon pull. OpenAIRE Graph v3 has
#: no funder enumeration endpoint (verified 2026-11-02 against v1/v2/v3 +
#: SKG-IF api-docs), but the projects endpoint accepts fundingShortName and
#: every hit carries the funder canon in funding[].funder. Codes verified
#: live 2026-11-02 (projects numFound): NWO 48170, EC 130457, WT 21507,
#: NSF 601434. ERC/EU returned 0 (ERC projects ride under EC streams).
#: Extend this list only after live-verifying a code, never blind.
OPENAIRE_FUNDER_CODES = ("NWO", "EC", "WT", "NSF")


def _openaire_row(funder: Any) -> dict[str, Any]:
    """openaire_funders row from an aireloom FundingFunder payload."""
    oid = str(getattr(funder, "id", "") or "").strip()
    if not oid:
        raise RuntimeError("openaire sweep: funder row without id")
    jurisdiction = getattr(funder, "jurisdiction", None)
    pid = getattr(funder, "pid", None)
    return {
        "openaire_id": oid,
        "name": getattr(funder, "name", None),
        "short_name": getattr(funder, "shortname", None),
        "website_url": None,
        "jurisdiction": getattr(jurisdiction, "code", None),
        "ror": normalize_ror(pid, json.dumps(funder.model_dump(), default=str)),
    }


async def harvest_openaire_funders(session: AsyncSession) -> dict[str, int]:
    """Curated OpenAIRE funder canon pull -> openaire_funders upsert.

    OpenAIRE Graph v3 exposes no funder enumeration (see
    OPENAIRE_FUNDER_CODES), so we sample one page of projects per verified
    fundingShortName and collect the funder canon from funding[].funder.
    Idempotent: reruns refresh every row.
    """
    if AireloomClient is None:  # pragma: no cover
        raise RuntimeError("openaire sweep: aireloom not installed")
    stats = {"codes": 0, "projects_seen": 0, "upserted": 0, "with_ror": 0}
    by_id: dict[str, dict[str, Any]] = {}
    async with AireloomClient() as client:
        for code in OPENAIRE_FUNDER_CODES:
            resp = await client.projects.search(
                filters={"fundingShortName": code}, page_size=OPENAIRE_PAGE_SIZE, page=1
            )
            stats["codes"] += 1
            results = resp.results or []
            stats["projects_seen"] += len(results)
            for project in results:
                # funding is one ProjectFunding object (hierarchical v3
                # structure); fundings, when present, is the flat list.
                fundings = list(project.fundings or [])
                if project.funding is not None:
                    fundings.append(project.funding)
                for f in fundings:
                    canon = getattr(f, "funder", None)
                    if canon is None or not getattr(canon, "id", None):
                        continue
                    by_id.setdefault(canon.id, _openaire_row(canon))
    rows = list(by_id.values())
    if not rows:
        raise RuntimeError("openaire sweep: zero funders returned")
    stats["upserted"] = await _upsert(session, OpenaireFunder, "openaire_id", rows)
    stats["with_ror"] = sum(1 for r in rows if r["ror"])
    stats["funder_links"] = await refresh_funder_links(session)
    stats["streams"] = await harvest_openaire_funder_streams(session)
    logger.info("harvest_openaire_funders: %s", stats)
    return stats


async def harvest_openaire_funder_streams(session: AsyncSession) -> int:
    """Top funding streams per OPENAIRE_FUNDER_CODES funder -> rebuild.

    Source is the explore backend facet search (portal-search, fast): the
    fundinglevel0_id facet per fundingShortName -- the funding the funder
    distributes, with project counts. Top 10 per funder (the facet
    endpoint's cap); grant amounts are deliberately not harvested (zero
    or missing for most funders, so sums would mislead). Idempotent:
    replaces the whole table every run."""
    known = set(
        (
            await session.execute(
                select(OpenaireFunder.openaire_id).where(
                    OpenaireFunder.short_name.in_(OPENAIRE_FUNDER_CODES)
                )
            )
        ).scalars()
    )
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for code in OPENAIRE_FUNDER_CODES:
            resp = await client.get(
                "https://services.openaire.eu/portal-search/projects/facetSearch",
                params={
                    "fundingShortName": code,
                    "facet": "true",
                    "facetFields": "fundinglevel0_id",
                    "page": 1,
                    "size": 1,
                },
            )
            resp.raise_for_status()
            facets = (
                resp.json()
                .get("body", {})
                .get("facetResponse", {})
                .get("facets", {})
                .get("fundinglevel0_id", [])
            )
            for facet in facets:
                level0_id = str(facet.get("id") or "")
                # level-0 ids are "<funder_id>::<stream>"; drop the stream
                # suffix to attribute the facet to its funder row.
                funder_id = level0_id.rsplit("::", 1)[0]
                if funder_id not in known:
                    continue
                name = str(facet.get("name") or "").split("|", 1)[-1] or None
                rows.append(
                    {
                        "funder_openaire_id": funder_id,
                        "level0_id": level0_id,
                        "name": name,
                        "n_projects": int(facet.get("count") or 0),
                    }
                )
    await session.execute(text("delete from openaire_funder_streams"))
    for chunk in range(0, len(rows), UPSERT_CHUNK):
        await session.execute(
            pg_insert(OpenaireFunderStream).values(rows[chunk : chunk + UPSERT_CHUNK])
        )
    await session.commit()
    logger.info(
        "harvest_openaire_funder_streams: %d rows across %d funders",
        len(rows),
        len({r["funder_openaire_id"] for r in rows}),
    )
    return len(rows)


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


async def refresh_funder_links(session: AsyncSession) -> int:
    """Rebuild funder_links from the ror/fundref columns (idempotent).

    Called after each funder harvest so the table never goes stale; the
    API's canon links, search aliases and OpenAIRE identity blocks read it.
    """
    await session.execute(text("delete from funder_links"))
    for source_sql in (
        "INSERT INTO funder_links (funder_id, source, source_id, via)"
        " SELECT j.id, 'openalex', o.openalex_id, 'ror'"
        " FROM jisc_funders j JOIN openalex_funders o ON o.ror = j.ror"
        " WHERE j.ror IS NOT NULL",
        "INSERT INTO funder_links (funder_id, source, source_id, via)"
        " SELECT j.id, 'openalex', o.openalex_id, 'fundref'"
        " FROM jisc_funders j JOIN openalex_funders o ON o.fundref = j.fundref"
        " WHERE j.fundref IS NOT NULL",
        "INSERT INTO funder_links (funder_id, source, source_id, via)"
        " SELECT j.id, 'openaire', a.openaire_id, 'ror'"
        " FROM jisc_funders j JOIN openaire_funders a ON a.ror = j.ror"
        " WHERE j.ror IS NOT NULL",
    ):
        await session.execute(text(source_sql))
    await session.commit()
    n = int(
        (await session.execute(select(func.count()).select_from(FunderLink.__table__))).scalar()
        or 0
    )
    logger.info("refresh_funder_links: %d links", n)
    return n
