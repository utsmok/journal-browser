"""Import a Pure backend export file (OAI-PMH ListRecords, CERIF 1.2) into
source_records as work_cerif_full.

The live OAI stream truncates author identity (live-verified 2026-11-05: 5
of 22 authors carried Person ids on one multi-author work); the backend
export of the same set carries every author's person id and org-unit
affiliations. Records land verbatim under entity_type=work_cerif_full so
the pure-authors backfill and the entity mining prefer them over the
stream's work_cerif versions (harvest.pure.entities.latest_publication_records).

Idempotent: IngestSession dedupes by content hash, so re-running with the
same file stores nothing.

uv run python jobs/import_pure_export.py --file <export.xml> [--institution ut]
"""

import argparse
import asyncio
import contextlib
import json
import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import resolve_institution
from journal_browser.harvest.pure.doi import extract_doi
from journal_browser.harvest.pure.transport import CRIS_PUBLICATIONS_SET, SOURCE, oai_tag
from journal_browser.harvest.pure.xmlrecords import (
    _cerif_publication_fields,
    _header_fields,
    record_payload,
)
from journal_browser.ingest import IngestSession

logger = logging.getLogger(__name__)

PAGE_SIZE = 1000


def _iter_records(file: Path):
    """<record> elements one at a time; cleared as consumed (230 MB file)."""
    record_tag = oai_tag("record")
    for _event, elem in ET.iterparse(file, events=("end",)):
        if elem.tag == record_tag:
            yield elem
            elem.clear()


async def import_pure_export(session, file: Path, institution) -> dict:
    """Store every record in the export file verbatim as work_cerif_full."""
    started = time.monotonic()
    ingest = IngestSession(session)
    config = {"origin": "pure_export_file", "file": str(file)}
    await ingest.start_run(
        SOURCE, "work_cerif_full", CRIS_PUBLICATIONS_SET, config, institution_id=institution.id
    )
    try:
        page: list[tuple[str, dict[str, Any]]] = []
        for record in _iter_records(file):
            oai_identifier, datestamp, _set_specs, status = _header_fields(record)
            if status == "deleted":
                ingest.parse_failures += 1
                ingest.records_seen += 1
                logger.warning(
                    "deleted record header in export file: %s (%s)", oai_identifier, datestamp
                )
                continue
            _pk, payload = record_payload(record)
            cerif = _cerif_publication_fields(record.find(oai_tag("metadata")))
            if cerif:
                payload["cerif"] = cerif
                if "doi_normalized" not in payload and (doi := extract_doi(cerif.get("doi") or "")):
                    payload["doi_normalized"] = doi
            page.append((oai_identifier, payload))
            if len(page) >= PAGE_SIZE:
                await ingest.ingest_records(page)
                page.clear()
        if page:
            await ingest.ingest_records(page)
    except Exception as exc:
        await ingest.finish_run("failed", {"error": f"{type(exc).__name__}: {exc}"[:200]})
        with contextlib.suppress(Exception):
            await session.commit()
        raise
    stats = {"file": str(file), "seconds": round(time.monotonic() - started, 1)}
    return await ingest.finish_run("completed", stats)


async def main(file: Path, code: str | None = "ut") -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        institution = await resolve_institution(session, code)
        stats = await import_pure_export(session, file, institution)
        await session.commit()
    await engine.dispose()
    print(json.dumps(stats))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path, help="path to the export XML file")
    parser.add_argument("--institution", default="ut", help="institution code (default: ut)")
    args = parser.parse_args()
    asyncio.run(main(args.file, args.institution))
