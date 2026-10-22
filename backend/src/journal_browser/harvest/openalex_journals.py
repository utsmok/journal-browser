"""Harvest OpenAlex sources (journals) via aletheca.

Two routes (ut-metadata practice): seed lookups for deal-covered ISSNs
(keyless batch calls), then a full cursor-paged sweep for the browsable
corpus (keyed when OPENALEX_API_KEY/ALETHECA_OPENALEX_API_KEY is set).
Every payload lands verbatim in source_records before normalization;
the normalization step also feeds issn_map and the publishers table.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from aletheca import AlethecaClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..ingest import IngestSession
from ..models import Institution, Journal, Publisher
from .common import normalize_issn, upsert_issn_map

logger = logging.getLogger(__name__)

SOURCE = "openalex"
ENTITY_TYPE = "sources"
PER_PAGE = 100
DATA_WINDOW_START = 2020


def openalex_id_to_pk(openalex_id: str | None) -> str:
    """'https://openalex.org/S123' -> 'S123'."""
    return (openalex_id or "").rsplit("/", 1)[-1]


async def resolve_home_institution_id(client: AlethecaClient, session: AsyncSession) -> str:
    """OpenAlex I-id for the configured home institution (keyless lookup)."""
    settings = get_settings()
    inst = await session.scalar(
        select(Institution).where(Institution.ror == settings.institution_ror)
    )
    if inst and inst.openalex_id:
        return openalex_id_to_pk(inst.openalex_id)
    response = await client.institutions.search(
        filters={"ror": settings.institution_ror}, page_size=1
    )
    results = getattr(response, "results", None) or response.get("results", [])
    if not results:
        raise RuntimeError(f"no OpenAlex institution for ROR {settings.institution_ror}")
    i_id = openalex_id_to_pk(results[0].id)
    if inst is None:
        inst = Institution(
            name=settings.institution_name, ror=settings.institution_ror, is_home=True
        )
        session.add(inst)
        await session.flush()
    inst.openalex_id = f"https://openalex.org/{i_id}"
    await session.flush()
    logger.info("Resolved %s to OpenAlex %s", settings.institution_ror, i_id)
    return i_id


def _payload_dict(item: Any) -> dict[str, Any] | None:
    """Verbatim JSON payload for a parsed model or raw dict."""
    if isinstance(item, dict):
        return item
    dump = getattr(item, "model_dump", None)
    if dump is not None:
        data = dump(mode="json")
        data["id"] = openalex_id_to_pk(data.get("id"))
        return data
    return None


async def _upsert_journal(session: AsyncSession, payload: dict[str, Any]) -> str | None:
    """Normalize one source payload into journals; returns issn_l or None."""
    issn_l = normalize_issn(payload.get("issn_l"))
    if issn_l is None:
        return None
    title = payload.get("display_name") or payload.get("title")
    alternate_titles = payload.get("alternate_titles") or []
    topics = [
        {"id": t.get("id"), "display_name": t.get("display_name")}
        for t in (payload.get("topics") or [])[:5]
    ]
    counts = payload.get("counts_by_year") or []
    # counts_by_year entries are {year, works_count, ...}; latest year with works > 0.
    last_active = max(
        (int(e["year"]) for e in counts if int(e.get("works_count") or 0) > 0),
        default=None,
    )
    works_2020_plus = sum(
        int(e.get("works_count") or 0) for e in counts if int(e.get("year") or 0) >= 2020
    )
    values = dict(
        issn_l=issn_l,
        openalex_id=payload.get("id"),
        title=title,
        publisher_name=payload.get("host_organization_name"),
        type=payload.get("type"),
        is_oa=payload.get("is_oa"),
        is_in_doaj=payload.get("is_in_doaj"),
        homepage_url=payload.get("homepage_url"),
        country_code=payload.get("country_code"),
        issns=[i for i in (normalize_issn(x) for x in (payload.get("issn") or [])) if i],
        alternate_titles=alternate_titles,
        topics=topics,
        apc_prices=payload.get("apc_prices"),
        summary_stats=payload.get("summary_stats"),
        counts_by_year=counts,
        works_count=payload.get("works_count"),
        cited_by_count=payload.get("cited_by_count"),
        last_active_year=last_active,
        works_2020_plus=works_2020_plus,
        harvested_at=datetime.now(UTC),
        search_text=" ".join([title or "", *alternate_titles]).strip(),
    )
    await session.execute(
        pg_insert(Journal)
        .values(**values)
        .on_conflict_do_update(index_elements=["issn_l"], set_=values)
    )
    await upsert_issn_map(session, values["issns"], issn_l, SOURCE)
    return issn_l


async def seed_deal_journals(client: AlethecaClient, session: AsyncSession) -> dict[str, int]:
    """Fetch sources for all deal-list ISSNs (keyless, 50/batch)."""
    from ..models import DealJournal

    issns = [
        row.issn
        for row in (await session.execute(select(DealJournal.issn).distinct())).all()
        if row.issn
    ]
    stats = {"issns": len(issns), "sources_found": 0}
    for i in range(0, len(issns), 50):
        batch = issns[i : i + 50]
        found = await client.sources.batch_get(batch, field="issn")
        for source in found.values():
            payload = _payload_dict(source)
            if payload and await _upsert_journal(session, payload):
                stats["sources_found"] += 1
        await session.commit()
    return stats


async def sweep_all_sources(
    client: AlethecaClient, session: AsyncSession, limit: int | None
) -> dict:
    """Full cursor sweep of OpenAlex sources; keyed harvest, per-page commits."""
    ingest = IngestSession(session)
    filter_set = "all"
    config = {"per_page": PER_PAGE, "route": "sweep"}
    await ingest.start_run(SOURCE, ENTITY_TYPE, filter_set, config)

    async def commit_page(_page: int, _cursor: str | None) -> None:
        await ingest.commit()

    normalized = 0
    async for item in client.sources.iterate(page_size=PER_PAGE, on_page=commit_page):
        payload = _payload_dict(item)
        pk = payload.get("id") if payload else None
        if not pk:
            await ingest.record_parse_failure(
                {
                    "source_pk": None,
                    "reason": "source model parse failure",
                    "raw_type": type(item).__name__,
                }
            )
            continue
        await ingest.ingest_record(pk, payload)
        if await _upsert_journal(session, payload):
            normalized += 1
        if limit is not None and ingest.records_seen >= limit:
            logger.info("Reached --limit %s", limit)
            break
    stats = await ingest.finish_run("completed", {"journals_normalized": normalized})
    await session.commit()
    return stats


async def harvest_journals(
    session: AsyncSession, limit: int | None = None, seed_only: bool = False
) -> dict:
    """Run both routes. seed_only=True fetches just deal-covered journals."""
    client_kwargs: dict[str, Any] = {}
    api_key = get_settings().openalex_api_key
    if api_key:
        client_kwargs["api_key"] = api_key
    async with AlethecaClient(**client_kwargs) as client:
        await resolve_home_institution_id(client, session)
        await session.commit()
        seed_stats = await seed_deal_journals(client, session)
        await session.commit()
        sweep_stats = {} if seed_only else await sweep_all_sources(client, session, limit)
    return {"seed": seed_stats, "sweep": sweep_stats}


async def refresh_publisher_links(session: AsyncSession) -> int:
    """Link journals.publisher_id where the name matches a known publisher
    (deal publishers only; OpenAlex's long tail stays as publisher_name)."""
    rows = (await session.execute(select(Journal.issn_l, Journal.publisher_name))).all()
    known = {
        p.name.casefold().strip(): p.id
        for p in (await session.execute(select(Publisher))).scalars()
    }
    linked = 0
    for issn_l, publisher_name in rows:
        if not publisher_name:
            continue
        publisher_id = known.get(publisher_name.casefold().strip())
        if publisher_id is None:
            continue
        await session.execute(
            pg_insert(Journal)
            .values(issn_l=issn_l, publisher_id=publisher_id)
            .on_conflict_do_update(index_elements=["issn_l"], set_={"publisher_id": publisher_id})
        )
        linked += 1
    await session.commit()
    return linked
