"""Scimagojr SJR + quartile ingest (per-year CSV export).

scimagojr.com sits behind a browser challenge for plain HTTP clients, so
this harvester reads the export from the landing dir: `fetch_step.py` in
the repo (or a manual download of journalrank.php?out=xls&year=<y>) puts
the file at landing/scimagojr/export_<year>.csv. Everything downstream
works from that landed copy.
"""

import csv
import io
import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..ingest import IngestSession
from ..models import Journal, ScimagojrMetric
from .common import issn_checksum_ok, lookup_issn_l, normalize_issn, require_headers

logger = logging.getLogger(__name__)

SOURCE = "scimagojr"
ENTITY_TYPE = "export"

# The export is semicolon-separated, latin-1 encoded, with a 2-line preamble.
COLUMNS = {
    "Rank": "rank",
    "Sourceid": "sourceid",
    "Title": "title",
    "Issn": "issn",
    "SJR": "sjr",
    "SJR Best Quartile": "quartile",
    "H index": "h_index",
}


def parse_export(data: bytes) -> list[dict[str, str]]:
    """Parse a scimagojr yearly export into row dicts (verbatim strings)."""
    text = data.decode("latin-1", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=";", quotechar='"')
    rows = []
    header = None
    for values in reader:
        if not values or not any(v.strip() for v in values):
            continue
        if header is None:
            if values[0].strip() != "Rank":
                continue  # preamble lines
            header = [h.strip() for h in values]
            continue
        values = [v.strip() for v in values]
        if len(values) < len(header):
            values += [""] * (len(header) - len(values))
        rows.append(dict(zip(header, values, strict=False)))
    require_headers(rows, set(COLUMNS), "scimagojr export")
    return rows


def issn_candidates(raw: str) -> list[str]:
    """The export sometimes lists several ISSNs in one cell. Checksum-bad
    ones are dropped: they can never resolve to a journal row."""
    return [
        i
        for i in (normalize_issn(part) for part in re.split(r"[^0-9Xx]+", raw or ""))
        if i and issn_checksum_ok(i)
    ]


async def ingest_year(session: AsyncSession, year: int, landing_dir: Path) -> dict[str, Any]:
    """Ingest one yearly export file from the landing dir."""
    path = landing_dir / SOURCE / f"export_{year}.csv"
    if not path.exists():
        return {"year": year, "status": "missing_file", "path": str(path)}
    data = path.read_bytes()

    ingest = IngestSession(session)
    await ingest.start_run(SOURCE, ENTITY_TYPE, f"year={year}", {"file": str(path)})
    kind, _ = await ingest.ingest_record(
        str(year), {"filename": path.name, "bytes_sha_head": data[:64].hex()}
    )
    rows = parse_export(data)
    metrics_upserted = 0
    unresolved = 0
    ghost_skipped = 0
    for row in rows:
        try:
            sjr = float(row.get("SJR", "").replace(",", ".")) if row.get("SJR") else None
            h_index = int(row["H index"]) if row.get("H index", "").isdigit() else None
            quartile = row.get("SJR Best Quartile") or None
            resolved = False
            for issn in issn_candidates(row.get("Issn", "")):
                issn_l = await lookup_issn_l(session, issn)
                if issn_l:
                    values = dict(
                        sjr=sjr,
                        best_quartile=quartile,
                        h_index=h_index,
                        extras={k: v for k, v in row.items() if k not in COLUMNS},
                    )
                    await session.execute(
                        pg_insert(ScimagojrMetric)
                        .values(issn_l=issn_l, year=year, **values)
                        .on_conflict_do_update(index_elements=["issn_l", "year"], set_=values)
                    )
                    # Quality-bar flag (decisions.md #12); backfills rows
                    # harvested before this export landed. UPDATE-only: never
                    # mint a title-less ghost journal for scimago-only ISSNs.
                    flag = await session.execute(
                        update(Journal).where(Journal.issn_l == issn_l).values(in_scimago=True)
                    )
                    if not flag.rowcount:
                        ghost_skipped += 1
                    resolved = True
                    metrics_upserted += 1
            if not resolved:
                unresolved += 1
        except Exception as exc:  # per-record isolation
            await ingest.record_parse_failure(
                {"source_pk": row.get("Sourceid"), "reason": str(exc)[:200]}
            )
    stats = await ingest.finish_run(
        "completed",
        {
            "rows": len(rows),
            "metrics_upserted": metrics_upserted,
            "unresolved_issn": unresolved,
            "ghost_journal_skips": ghost_skipped,
        },
    )
    await session.commit()
    logger.info(
        "scimagojr %s: %s rows, %s metrics, %s unresolved, %s ghost-journal flags skipped",
        year,
        len(rows),
        metrics_upserted,
        unresolved,
        ghost_skipped,
    )
    return {"year": year, "status": "ok", **stats}
