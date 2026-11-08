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
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..ingest import IngestSession
from ..models import Institution, IssnMap, Journal, Publisher
from .common import issn_checksum_ok, normalize_issn, paced_single_gets, upsert_issn_map

logger = logging.getLogger(__name__)

SOURCE = "openalex"
ENTITY_TYPE = "sources"
PER_PAGE = 100


def openalex_id_to_pk(openalex_id: str | None) -> str:
    """'https://openalex.org/S123' -> 'S123'."""
    return (openalex_id or "").rsplit("/", 1)[-1]


async def resolve_institution_openalex_id(
    client: AlethecaClient, session: AsyncSession, institution: Institution
) -> str:
    """OpenAlex I-id for one hosted institution (keyless ROR lookup); the
    resolved id is cached on the institution row."""
    if institution.openalex_id:
        return openalex_id_to_pk(institution.openalex_id)
    ror = institution.ror
    if not ror:
        raise RuntimeError(f"institution {institution.code!r} has no ROR to resolve")
    response = await client.institutions.search(filters={"ror": ror}, page_size=1)
    results = getattr(response, "results", None) or response.get("results", [])
    if not results:
        raise RuntimeError(f"no OpenAlex institution for ROR {ror}")
    i_id = openalex_id_to_pk(results[0].id)
    institution.openalex_id = f"https://openalex.org/{i_id}"
    await session.flush()
    logger.info("Resolved %s to OpenAlex %s", ror, i_id)
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


def journal_values(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one source payload into journals column values; None when
    the record has no usable linking ISSN (missing or bad checksum)."""
    issn_l = normalize_issn(payload.get("issn_l"))
    if issn_l is None:
        return None
    if not issn_checksum_ok(issn_l):
        logger.warning(
            "openalex %s: checksum-invalid issn_l %r; journal skipped",
            payload.get("id"),
            issn_l,
        )
        return None
    title = payload.get("display_name") or payload.get("title")
    alternate_titles = payload.get("alternate_titles") or []
    # count = that source's works in the topic (OpenAlex source field); the
    # author topic weighting spreads venue mass across the list by it and
    # labels it by subfield (coarser and stabler than topic names).
    topics = [
        {
            "id": t.get("id"),
            "display_name": t.get("display_name"),
            "count": t.get("count"),
            "subfield": (t.get("subfield") or {}).get("display_name"),
        }
        for t in (payload.get("topics") or [])[:5]
    ]
    counts = payload.get("counts_by_year") or []
    # counts_by_year entries are {year, works_count, ...}; latest year with works > 0.
    # Entries without a year are skipped, not page-aborting KeyErrors.
    last_active = max(
        (
            int(e["year"])
            for e in counts
            if e.get("year") is not None and int(e.get("works_count") or 0) > 0
        ),
        default=None,
    )
    settings = get_settings()
    window_end = settings.data_window_end if settings.data_window_end is not None else 9999
    works_2020_plus = sum(
        int(e.get("works_count") or 0)
        for e in counts
        if settings.data_window_start <= int(e.get("year") or 0) <= window_end
    )
    return {
        "issn_l": issn_l,
        "openalex_id": payload.get("id"),
        "title": title,
        "publisher_name": payload.get("host_organization_name"),
        "type": payload.get("type"),
        "is_oa": payload.get("is_oa"),
        "is_in_doaj": payload.get("is_in_doaj"),
        "homepage_url": payload.get("homepage_url"),
        "country_code": payload.get("country_code"),
        "issns": [
            i
            for i in (normalize_issn(x) for x in (payload.get("issn") or []))
            if i and issn_checksum_ok(i)
        ],
        "alternate_titles": alternate_titles,
        "topics": topics,
        "apc_prices": payload.get("apc_prices"),
        "summary_stats": payload.get("summary_stats"),
        "counts_by_year": counts,
        "works_count": payload.get("works_count"),
        "cited_by_count": payload.get("cited_by_count"),
        "last_active_year": last_active,
        "works_2020_plus": works_2020_plus,
        "harvested_at": datetime.now(UTC),
        "search_text": " ".join([title or "", *alternate_titles]).strip(),
    }


async def _upsert_journal(session: AsyncSession, payload: dict[str, Any]) -> str | None:
    """Normalize one source payload into journals; returns issn_l or None."""
    values = journal_values(payload)
    if values is None:
        return None
    # Re-key guard (see _upsert_journal_page): an upstream issn_l change
    # must not crash on the openalex_id unique key; keep the stored row and
    # map the variant ISSNs onto it so links keep resolving.
    stored_issn_l = await session.scalar(
        select(Journal.issn_l).where(Journal.openalex_id == values["openalex_id"])
    )
    if stored_issn_l is not None and stored_issn_l != values["issn_l"]:
        logger.warning(
            "openalex %s: source re-keyed upstream (stored issn_l=%s, payload issn_l=%s); "
            "variant skipped, issn_map pointed at stored row",
            values["openalex_id"],
            stored_issn_l,
            values["issn_l"],
        )
        await upsert_issn_map(session, values["issns"], stored_issn_l, SOURCE)
        return stored_issn_l
    await session.execute(
        pg_insert(Journal)
        .values(**values)
        .on_conflict_do_update(index_elements=["issn_l"], set_=values)
    )
    await upsert_issn_map(session, values["issns"], values["issn_l"], SOURCE)
    return values["issn_l"]


async def seed_deal_journals(client: AlethecaClient, session: AsyncSession) -> dict[str, int]:
    """Fetch sources for all deal-list ISSNs (keyless, 50/batch)."""
    from ..models import DealJournal

    ingest = IngestSession(session)
    await ingest.start_run(SOURCE, ENTITY_TYPE, "all", {"route": "seed"})
    issns = [
        row.issn
        for row in (await session.execute(select(DealJournal.issn).distinct())).all()
        if row.issn
    ]
    stats = {"issns": len(issns), "sources_found": 0}
    for i in range(0, len(issns), 50):
        batch = issns[i : i + 50]
        found = await client.sources.batch_get(batch, field="issn")
        page = []
        for source in found.values():
            payload = _payload_dict(source)
            if payload and payload.get("id"):
                page.append((payload["id"], payload))
        await ingest.ingest_records(page)
        for _, payload in page:
            if await _upsert_journal(session, payload):
                stats["sources_found"] += 1
        await session.commit()
    stats = await ingest.finish_run("completed", stats)
    await session.commit()
    return stats


async def _upsert_journal_page(session: AsyncSession, payloads: list[dict[str, Any]]) -> int:
    """Bulk-normalize one page of source payloads: one journals upsert and
    one issn_map upsert. Returns the number of payloads normalized.

    Per-page memo keyed by issn_l / variant ISSN; the last record wins,
    matching the sequential per-record upsert order.
    """
    journal_rows: dict[str, dict[str, Any]] = {}
    issn_rows: dict[str, dict[str, Any]] = {}
    counted = 0
    for payload in payloads:
        values = journal_values(payload)
        if values is None:
            continue
        counted += 1
        journal_rows[values["issn_l"]] = values
        for issn in set(values["issns"]) | {values["issn_l"]}:
            issn_rows[issn] = {"issn": issn, "issn_l": values["issn_l"], "source": SOURCE}
    if journal_rows:
        rows = list(journal_rows.values())
        # OpenAlex can re-key a source's issn_l upstream. The sweep then
        # offers the same openalex_id under a new issn_l while the stored
        # row (old issn_l) still exists; the issn_l arbiter cannot merge
        # those and the openalex_id unique key would abort the page. Skip
        # the re-keyed variant (raw payload stays in source_records).
        existing = (
            await session.execute(
                select(Journal.issn_l, Journal.openalex_id).where(
                    Journal.openalex_id.in_([r["openalex_id"] for r in rows])
                )
            )
        ).all()
        keyed_issn: dict[str, str] = {oid: il for il, oid in existing}
        rows = [r for r in rows if keyed_issn.get(r["openalex_id"]) in (None, r["issn_l"])]
        if rows:
            stmt = pg_insert(Journal).values(rows)
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["issn_l"],
                    set_={k: stmt.excluded[k] for k in rows[0] if k != "issn_l"},
                )
            )
    if issn_rows:
        rows = list(issn_rows.values())
        stmt = pg_insert(IssnMap).values(rows)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["issn"],
                set_={"issn_l": stmt.excluded.issn_l, "source": stmt.excluded.source},
            )
        )
    return counted


async def prune_orphan_issn_map(session: AsyncSession) -> int:
    """Drop issn_map rows whose issn_l has no journals row; returns count.

    Map writes are not transactional with journal creation, and an
    upstream issn_l re-key can retire a target while its map rows survive
    (production residue since 2026-10-22: variants pointing at the absent
    issn_l 1760-7760). The sweep re-adds rows for live targets, so pruning
    here converges the map to the journal universe on every full sweep.
    """
    result = await session.execute(
        delete(IssnMap).where(IssnMap.issn_l.not_in(select(Journal.issn_l)))
    )
    return result.rowcount or 0


async def sweep_all_sources(
    client: AlethecaClient, session: AsyncSession, limit: int | None
) -> dict:
    """Full cursor sweep of OpenAlex sources; keyed harvest, per-page commits.

    Per page: one bulk source_records store, one bulk journals upsert, one
    bulk issn_map upsert (memoized per page). ~3 round trips per 100-source
    page instead of ~1.25M sequential ones.
    """
    ingest = IngestSession(session)
    filter_set = "all"
    config = {"per_page": PER_PAGE, "route": "sweep"}
    await ingest.start_run(SOURCE, ENTITY_TYPE, filter_set, config)

    async def commit_page(_page: int, _cursor: str | None) -> None:
        await ingest.commit()

    normalized = 0
    seen = 0
    page: list[tuple[str, dict[str, Any]]] = []

    async for item in client.sources.iterate(page_size=PER_PAGE, on_page=commit_page):
        payload = _payload_dict(item)
        pk = payload.get("id") if payload else None
        if not pk:
            seen += 1
            await ingest.record_parse_failure(
                {
                    "source_pk": None,
                    "reason": "source model parse failure",
                    "raw_type": type(item).__name__,
                }
            )
            continue
        seen += 1
        page.append((pk, payload))
        if len(page) >= PER_PAGE:
            await ingest.ingest_records(page)
            normalized += await _upsert_journal_page(session, [p for _, p in page])
            page = []
        if limit is not None and seen >= limit:
            logger.info("Reached --limit %s", limit)
            break
    await ingest.ingest_records(page)
    pruned = await prune_orphan_issn_map(session)
    stats = await ingest.finish_run(
        "completed", {"journals_normalized": normalized, "issn_map_pruned": pruned}
    )
    await session.commit()
    return stats


async def harvest_journals_delta(
    client: AlethecaClient, session: AsyncSession, limit: int | None = None
) -> dict:
    """Fetch full source payloads for journals cited by stored works but
    missing from journals — paced free single-entity GETs, no listing.

    The full sweep seeded the table once; refreshes only need journals
    the corpus actually cites, and singletons cost no credits so the
    delta works even with the daily budget at zero. Lands raws in
    source_records exactly like the sweep so downstream derivations see
    them. Idempotent: reruns fetch nothing."""
    referenced = sorted(
        {
            pk
            for (pk,) in (
                await session.execute(
                    text(
                        "SELECT DISTINCT payload->'primary_location'->'source'->>'id'"
                        " FROM source_records"
                        " WHERE source = 'openalex' AND entity_type = 'work'"
                        " AND payload->'primary_location'->'source'->>'id' IS NOT NULL"
                    )
                )
            ).all()
        }
    )
    todo = sorted(
        {openalex_id_to_pk(pk) for pk in referenced}
        - {r for (r,) in (await session.execute(select(Journal.openalex_id))).all()}
    )
    if limit is not None:
        todo = todo[:limit]
    stats: dict[str, int] = {
        "referenced": len(referenced),
        "todo": len(todo),
        "ingested": 0,
        "missing": 0,
        "failed": 0,
    }
    if not todo:
        return stats
    ingest = IngestSession(session)
    await ingest.start_run(SOURCE, ENTITY_TYPE, "delta", {"route": "delta", "per_id": True})
    payloads, failed = await paced_single_gets(
        client.sources.get, [f"https://openalex.org/{pk}" for pk in todo]
    )
    stats["failed"] = len(failed)
    if failed:
        logger.warning(
            "journals delta: %d lookups failed, e.g. %s", len(failed), sorted(failed)[:5]
        )
    page: list[tuple[str, dict[str, Any]]] = []
    for pk in todo:
        entity = payloads.get(f"https://openalex.org/{pk}")
        payload = _payload_dict(entity)
        if payload is None:
            stats["missing"] += 1
            continue
        page.append((pk, payload))
        if len(page) >= PER_PAGE:
            await ingest.ingest_records(page)
            stats["ingested"] += await _upsert_journal_page(session, [p for _, p in page])
            page = []
    await ingest.ingest_records(page)
    stats["ingested"] += await _upsert_journal_page(session, [p for _, p in page])
    await ingest.commit()
    final = await ingest.finish_run("completed", stats)
    await session.commit()
    return final


async def harvest_journals(
    session: AsyncSession,
    limit: int | None = None,
    seed_only: bool = False,
    sweep_all: bool = False,
) -> dict:
    """Refresh route: seed deal ISSNs (keyless batches) plus the delta of
    works-referenced journals (free singletons). sweep_all=True runs the
    full listing sweep instead of the delta — a rare manual operation,
    not a per-refresh step: journal metadata does not change every
    refresh and the sweep costs credits."""
    client_kwargs: dict[str, Any] = {}
    api_key = get_settings().openalex_api_key
    if api_key:
        client_kwargs["api_key"] = api_key
    async with AlethecaClient(**client_kwargs) as client:
        # Institution OpenAlex ids resolve lazily in each institution's
        # stats harvest (resolve_institution_openalex_id); the journals
        # harvest itself is institution-neutral.
        seed_stats = await seed_deal_journals(client, session)
        await session.commit()
        main_stats: dict = {}
        if not seed_only:
            if sweep_all:
                main_stats = await sweep_all_sources(client, session, limit)
            else:
                main_stats = await harvest_journals_delta(client, session, limit)
    return {"seed": seed_stats, "delta": main_stats}


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
