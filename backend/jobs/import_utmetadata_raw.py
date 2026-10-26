"""One-shot import: ut-metadata verbatim source records -> this deployment.

Copies every external work record that links to the imported canonical
corpus (source_identity -> pure_item_population) into the local landing
store, keyed per stream in this app's conventions:

- openalex works  -> source_records('openalex', 'works_stats'): feeds the
  journal works list, per-year OA stats and the FWCI/retraction metrics
  for all years, not just the window the live harvest covered. The
  per-journal/year stats rows are rebuilt window-bounded from the copied
  payloads afterwards.
- openaire works  -> ('openaire', 'work'); DOI matches confirm
  work_identity rows exactly like the live harvest does.
- pure works      -> ('pure', 'work'); landing evidence only (the parsed
  corpus already lives in `works`).
- crossref works  -> ('crossref', 'work'), source_pk remapped to the
  local 'doi:<doi>' convention.

Then refreshes pure_canon stats + journal_flags. Idempotent: content-hash
dedupe skips records already stored; stats/identity steps recompute.

Usage: uv run --no-dev python jobs/import_utmetadata_raw.py [--institution ut]
"""

import argparse
import asyncio
import json
from collections import Counter

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import resolve_institution
from journal_browser.harvest.denorm import refresh_institution_stats
from journal_browser.harvest.institution_stats import (
    _oa_status,
    _source_issn_map,
    _write_journal_stats,
    write_pure_canon_stats,
)
from journal_browser.harvest.openaire import _confirm
from journal_browser.harvest.pure import extract_doi
from journal_browser.ingest import IngestSession
from journal_browser.models import Institution
from journal_browser.services.ut_metadata import _get_engine, normalize_doi

PAGE = 400

# Latest verbatim version per source_pk, linked to the importable corpus.
# entity_type on the ut-metadata side is always 'works'; this app names
# work streams per harvester (works_stats / work).
STREAM_SQL = """
SELECT DISTINCT ON (sr.source_pk) sr.source_pk, sr.payload
FROM source_records sr
JOIN source_identity si ON si.source_pk = sr.source_pk AND si.entity_type = 'works'
JOIN pure_item_population pop ON pop.canonical_id = si.canonical_id
WHERE sr.source = :source AND sr.entity_type = 'works'
  AND pop.canonical_id IS NOT NULL
  AND sr.source_pk > :last
ORDER BY sr.source_pk, sr.id DESC
LIMIT :n
"""
# Pure records key by OAI identifier, not source_identity; the uuid is the
# identifier tail.
PURE_STREAM_SQL = """
SELECT DISTINCT ON (sr.source_pk) sr.source_pk, sr.payload
FROM source_records sr
JOIN pure_item_population pop
  ON sr.source_pk = 'oai:ris.utwente.nl:publications/' || pop.uuid
WHERE sr.source = 'pure' AND sr.entity_type = 'works'
  AND pop.canonical_id IS NOT NULL
  AND sr.source_pk > :last
ORDER BY sr.source_pk, sr.id DESC
LIMIT :n
"""

# openalex streams: (ut-metadata source, local entity_type)
STREAMS = [
    ("openalex", "works_stats"),
    ("openaire", "work"),
    ("pure", "work"),
    ("crossref", "work"),
]


def resolve_dsn(institution: Institution) -> str | None:
    """Per-institution DSN first, global ut-metadata setting as fallback."""
    return institution.external_works_dsn or get_settings().ut_metadata_dsn or None


def _adapt(source: str, pk: str, payload: dict) -> tuple[str, dict] | None:
    """Local convention for (source_pk, payload); None = skip record."""
    if source == "crossref":
        doi = normalize_doi(payload.get("doi")) or normalize_doi(pk)
        return (f"doi:{doi}", payload) if doi else None
    if source == "pure":
        # Match the local harvester's payload shape so content hashes line
        # up with already-stored records where the payload is identical.
        payload.setdefault("oai_identifier", pk)
    return pk, payload


def _extract_openaire_doi(payload: dict) -> str | None:
    doi = extract_doi(payload.get("doi") or "")
    if doi:
        return doi
    for pid in payload.get("pids") or []:
        if (pid.get("scheme") or "").lower() == "doi":
            doi = extract_doi(pid.get("value") or "")
            if doi:
                return doi
    return None


async def copy_stream(
    ext, session, institution, source: str, entity_type: str, link_sql: str
) -> dict:
    ingest = IngestSession(session)
    await ingest.start_run(
        source,
        entity_type,
        f"inst:{institution.code}",
        {"source": "ut-metadata raw import"},
        institution_id=institution.id,
    )
    stats = {"copied": 0, "duplicate": 0, "skipped": 0}
    last = ""
    while True:
        rows = (
            await ext.execute(
                text(link_sql), {"source": source, "last": last, "n": PAGE}
            )
        ).all()
        if not rows:
            break
        records = []
        for pk, payload in rows:
            last = pk
            adapted = _adapt(source, pk, payload)
            if adapted is None:
                stats["skipped"] += 1
                continue
            records.append(adapted)
        added = await ingest.ingest_records(records)
        stats["copied"] += added
        stats["duplicate"] += len(records) - added
        await ingest.commit()
    final = await ingest.finish_run("completed", stats)
    await ingest.commit()
    return final


async def rebuild_openalex_stats(session, institution) -> dict:
    """Window-bounded per-journal/year OA stats from the copied payloads.

    Same aggregation as harvest_institution_stats, over the latest stored
    version per work across this institution's runs.
    """
    window_end = institution.data_window_end or 9999
    sql = text(
        """
        WITH latest AS (
            SELECT DISTINCT ON (sr.source_pk) sr.source_pk, sr.payload
            FROM source_records sr
            JOIN harvest_runs hr ON hr.id = sr.harvest_run_id
            WHERE sr.source = 'openalex' AND sr.entity_type = 'works_stats'
              AND hr.institution_id = :iid
            ORDER BY sr.source_pk, sr.harvested_at DESC
        )
        SELECT payload->'primary_location'->'source'->>'id' AS src_id,
               payload->>'publication_year' AS yr,
               payload->'open_access'->>'oa_status' AS oa,
               count(*) AS n
        FROM latest
        GROUP BY 1, 2, 3
        """
    )
    issn_by_source = await _source_issn_map(session)
    per_journal_year: Counter[tuple[str, int, str]] = Counter()
    unlinked = out_of_window = no_year = 0
    for src_id, yr, oa, n in (await session.execute(sql, {"iid": institution.id})).all():
        try:
            year = int(yr)
        except (TypeError, ValueError):
            no_year += n
            continue
        if not (institution.data_window_start <= year <= window_end):
            out_of_window += n
            continue
        issn_l = issn_by_source.get((src_id or "").rsplit("/", 1)[-1])
        if not issn_l:
            unlinked += n
            continue
        per_journal_year[(issn_l, year, _oa_status({"open_access": {"oa_status": oa}}))] += n
    await _write_journal_stats(session, institution.id, per_journal_year)
    return {
        "openalex_stats_rows": len({(i, y) for (i, y, _s) in per_journal_year}),
        "openalex_unlinked_to_journal": unlinked,
        "openalex_out_of_window": out_of_window,
        "openalex_no_year": no_year,
    }


async def main(code: str) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        institution = await resolve_institution(session, code)
        dsn = resolve_dsn(institution)
        if not dsn:
            raise SystemExit(f"no ut-metadata DSN for {institution.code}; set it first")
        ext_engine = _get_engine(dsn)
        async with ext_engine.connect() as ext:
            totals: dict = {}
            for source, entity_type in STREAMS:
                link_sql = PURE_STREAM_SQL if source == "pure" else STREAM_SQL
                totals[source] = await copy_stream(
                    ext, session, institution, source, entity_type, link_sql
                )

        # DOI identities for the copied OpenAIRE records (same rule as the
        # live harvest: best-effort DOI -> confirmed work_identity).
        doi_to_work = {
            doi: uuid
            for doi, uuid in (
                await session.execute(
                    text(
                        "SELECT doi_normalized, pure_uuid FROM works "
                        "WHERE institution_id = :iid "
                        "AND doi_normalized IS NOT NULL AND retired_at IS NULL"
                    ),
                    {"iid": institution.id},
                )
            ).all()
        }
        confirmed = 0
        async with ext_engine.connect() as ext:
            last = ""
            while True:
                rows = (
                    await ext.execute(
                        text(STREAM_SQL),
                        {"source": "openaire", "last": last, "n": PAGE},
                    )
                ).all()
                if not rows:
                    break
                for pk, payload in rows:
                    last = pk
                    doi = _extract_openaire_doi(payload)
                    if doi and (uuid := doi_to_work.get(doi)):
                        await _confirm(
                            session,
                            institution_id=institution.id,
                            source_pk=pk,
                            work_id=uuid,
                        )
                        confirmed += 1
        totals["openaire_doi_confirmed"] = confirmed
        await session.commit()

        totals.update(await rebuild_openalex_stats(session, institution))
        totals["pure_canon_rows"] = await write_pure_canon_stats(session, institution)
        await refresh_institution_stats(session, institution)
        await session.commit()
    await engine.dispose()
    print(json.dumps(totals))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution", default="ut", help="institution code")
    args = parser.parse_args()
    asyncio.run(main(args.institution))
