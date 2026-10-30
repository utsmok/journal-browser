import asyncio
import contextlib
import logging
import xml.etree.ElementTree as ET
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...ingest import IngestSession
from .store import backfill_cerif, retire_absent, store_pure_work_authors, upsert_work
from .transport import (
    CRIS_PUBLICATIONS_SET,
    DEFAULT_YEAR_SET,
    MAX_TOKEN_RESTARTS,
    PREFIX_CERIF,
    PREFIX_DC,
    SOURCE,
    Pacer,
    PureOaiError,
    _oai_pages,
    oai_tag,
)
from .xmlrecords import (
    _cerif_publication_fields,
    _header_fields,
    pure_uuid_for,
    record_payload,
    year_for_set,
)

logger = logging.getLogger(__name__)


async def _ingest_oai_record(
    ingest: IngestSession,
    record: ET.Element,
    *,
    institution_id: int,
    year: int,
    run_id: int,
    entity_type: str,
) -> str:
    """Store one <record> verbatim + upsert the canonical row; returns kind."""
    oai_identifier, datestamp, _set_specs, status = _header_fields(record)
    if status == "deleted":
        # deletedRecord=no on this endpoint, so a deleted header is an anomaly.
        ingest.parse_failures += 1
        ingest.records_seen += 1
        logger.warning(
            "deleted record header on endpoint with deletedRecord=no: %s (%s)",
            oai_identifier,
            datestamp,
        )
        return "deleted"
    _, payload = record_payload(record)
    if entity_type == "work_cerif":
        metadata = record.find(oai_tag("metadata"))
        cerif = _cerif_publication_fields(metadata)
        if cerif:
            payload["cerif"] = cerif
    kind, _ = await ingest.ingest_record(oai_identifier, payload)
    if entity_type == "work":
        await upsert_work(
            ingest.session, payload, institution_id=institution_id, year=year, run_id=run_id
        )
    elif entity_type == "work_cerif" and payload.get("cerif"):
        await backfill_cerif(
            ingest.session,
            pure_uuid_for(oai_identifier),
            payload["cerif"],
            institution_id=institution_id,
        )
        authors = payload["cerif"].get("authors") or []
        if authors:
            # Pure's own author list (the standalone author path's
            # pure-side edges). Works-absent records skip silently; the
            # backfill job covers them once the works sweep lands.
            await store_pure_work_authors(
                ingest.session,
                pure_uuid_for(oai_identifier),
                authors,
                institution_id=institution_id,
            )
    return kind


# ── Set harvest (producer/consumer, per-page commit) ─────────────────────────

# Producer->consumer queue item: (records, token progress attrs) per page;
# None is the end sentinel.
PageItem = tuple[list[ET.Element], dict[str, str]] | None


async def _produce_oai_pages(
    base_url: str,
    base_params: dict[str, str],
    set_spec: str,
    pacer: Pacer,
    stats: dict[str, Any],
    queue: asyncio.Queue[PageItem],
) -> None:
    """Drive the resumption chain onto the queue; restart on badResumptionToken."""
    try:
        for attempt in range(MAX_TOKEN_RESTARTS + 1):
            try:
                async for page, token_attrs in _oai_pages(
                    base_url, "ListRecords", base_params, "record", pacer
                ):
                    await queue.put((page, token_attrs))
                return
            except PureOaiError as exc:
                if exc.code != "badResumptionToken" or attempt == MAX_TOKEN_RESTARTS:
                    raise
                stats["token_restarts"] += 1
                logger.warning(
                    "badResumptionToken on set %s (attempt %s); restarting set",
                    set_spec,
                    attempt + 1,
                )
    finally:
        task = asyncio.current_task()
        if task is not None and task.cancelling() == 0:
            await queue.put(None)


async def _consume_oai_pages(
    ingest: IngestSession,
    queue: asyncio.Queue[PageItem],
    stats: dict[str, Any],
    *,
    institution_id: int,
    year: int,
    entity_type: str,
    limit: int | None,
) -> None:
    """Parse + ingest a page, then commit it (a crash loses at most one page)."""
    while True:
        item = await queue.get()
        if item is None:
            break
        page, token_attrs = item
        stats["pages"] += 1
        if token_attrs.get("complete_list_size", "").isdigit():
            stats["complete_list_size"] = int(token_attrs["complete_list_size"])
        limit_reached = False
        for record in page:
            try:
                kind = await _ingest_oai_record(
                    ingest,
                    record,
                    institution_id=institution_id,
                    year=year,
                    run_id=ingest.run_id,
                    entity_type=entity_type,
                )
            except (PureOaiError, ET.ParseError) as exc:
                # Record-level parse problems leave the session healthy;
                # DB-level errors must propagate (the transaction is dead).
                await ingest.record_parse_failure(
                    {"source_pk": None, "reason": f"{type(exc).__name__}: {exc}"}
                )
                continue
            stats[kind] += 1
            if limit is not None and ingest.records_seen >= limit:
                stats["limit_reached"] = True
                limit_reached = True
                break
        await ingest.commit()
        if limit_reached:
            break


async def _harvest_set(
    ingest: IngestSession,
    set_spec: str,
    metadata_prefix: str,
    *,
    base_url: str,
    institution_id: int,
    from_date: str | None = None,
    until_date: str | None = None,
    limit: int | None = None,
    pacer: Pacer | None = None,
) -> dict[str, Any]:
    """ListRecords over one set with resumption; restart on badResumptionToken."""
    settings = get_settings()
    pacer = pacer or Pacer(settings.pure_oai_min_spacing)
    base_params = {"metadataPrefix": metadata_prefix, "set": set_spec}
    if from_date:
        base_params["from"] = from_date
    if until_date:
        base_params["until"] = until_date

    stats: dict[str, Any] = {
        "pages": 0,
        "token_restarts": 0,
        "new": 0,
        "duplicate": 0,
        "deleted": 0,
        "complete_list_size": None,
    }
    queue: asyncio.Queue[PageItem] = asyncio.Queue(maxsize=3)
    prod = asyncio.create_task(
        _produce_oai_pages(base_url, base_params, set_spec, pacer, stats, queue)
    )
    year = year_for_set(set_spec) or 0
    cons = asyncio.create_task(
        _consume_oai_pages(
            ingest,
            queue,
            stats,
            institution_id=institution_id,
            year=year,
            entity_type=ingest.entity_type or "work",
            limit=limit,
        )
    )
    try:
        await cons
    finally:
        if not prod.done():
            prod.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await prod
    if not prod.cancelled():
        exc = prod.exception()
        if exc is not None:
            raise exc
    return stats


# Full sweep = every configured window year (settings.data_window_*). Drives
# the retirement pass (works absent from a full sweep are marked, never deleted).
async def harvest_pure_years(
    session: AsyncSession,
    institution,
    years: list[int],
    *,
    limit: int | None = None,
    full_sweep: bool = False,
) -> dict[str, Any]:
    """Harvest one institution's publications:year{Y} sets (oai_dc) into
    source_records + works.

    One harvest_run per year set. full_sweep=True covers every window year
    of the institution in one go and retires works absent from the sweep
    afterwards — so `years` MUST span the whole window, or retirement would
    stamp works that were simply not part of this (partial) run.
    """
    base_url = institution.pure_oai_base_url
    if not base_url:
        raise ValueError(f"institution {institution.code!r} has no pure_oai_base_url")
    if full_sweep:
        expected = set(institution.window_years)
        if set(years) != expected:
            raise ValueError(
                f"full_sweep requires every window year {sorted(expected)}, got {sorted(years)}"
            )
    stats: dict[str, Any] = {"sets": {}}
    totals = {"records_seen": 0, "records_stored": 0, "parse_failures": 0}
    run_ids: list[int] = []
    for year in years:
        set_spec = DEFAULT_YEAR_SET.format(year=year)
        ingest = IngestSession(session)
        config = {
            "base_url": base_url,
            "metadata_prefix": PREFIX_DC,
            "full_sweep": full_sweep,
        }
        await ingest.start_run(SOURCE, "work", set_spec, config, institution_id=institution.id)
        run_ids.append(ingest.run_id)
        try:
            set_stats = await _harvest_set(
                ingest,
                set_spec,
                PREFIX_DC,
                base_url=base_url,
                institution_id=institution.id,
                limit=limit,
            )
        except Exception as exc:
            # Commit the failed-run marker: finish_run only flushes, and the
            # re-raise would otherwise roll the run row back into nothing.
            await ingest.finish_run("failed", {"error": f"{type(exc).__name__}: {exc}"[:200]})
            with contextlib.suppress(Exception):
                await session.commit()
            raise
        final = await ingest.finish_run("completed", set_stats)
        await ingest.commit()
        stats["sets"][set_spec] = final
        for key in totals:
            totals[key] += final.get(key, 0) or 0
    # Retirement is only sound against the runs of THIS sweep: per-year sets
    # each get their own harvest_run, so retiring against only the last run
    # would retire every other year.
    stats["retired"] = await retire_absent(session, run_ids, institution.id) if full_sweep else 0
    await session.commit()
    stats.update(totals)
    return stats


async def harvest_pure_cerif(
    session: AsyncSession,
    institution,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Enrichment pass: openaire_cris_publications over oai_cerif_openaire.

    Stores records verbatim (entity_type=work_cerif) and backfills
    cerif_issn/publisher/doi/oa_status onto matching works rows.
    """
    base_url = institution.pure_oai_base_url
    if not base_url:
        raise ValueError(f"institution {institution.code!r} has no pure_oai_base_url")
    ingest = IngestSession(session)
    config = {"base_url": base_url, "metadata_prefix": PREFIX_CERIF}
    await ingest.start_run(
        SOURCE, "work_cerif", CRIS_PUBLICATIONS_SET, config, institution_id=institution.id
    )
    try:
        set_stats = await _harvest_set(
            ingest,
            CRIS_PUBLICATIONS_SET,
            PREFIX_CERIF,
            base_url=base_url,
            institution_id=institution.id,
            limit=limit,
        )
    except Exception as exc:
        await ingest.finish_run("failed", {"error": f"{type(exc).__name__}: {exc}"[:200]})
        with contextlib.suppress(Exception):
            await session.commit()
        raise
    final = await ingest.finish_run("completed", set_stats)
    await ingest.commit()
    return final
