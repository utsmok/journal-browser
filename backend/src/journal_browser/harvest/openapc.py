"""OpenAPC harvest: land release CSVs, journal ISSN-L×period aggregates, per-article evidence.

ODbL data from github.com/OpenAPC/openapc-de. Collect-only: raw files land
before any normalization, and every normalization pass re-reads the landed
copy, never in-memory fetch bytes.
"""

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from statistics import fmean
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..harvest.denorm import refresh_apcs
from ..ingest import IngestSession, sha256_bytes
from ..models import ApcEvidence, JournalApcAggregate, RawFile, SourceRecord
from .common import (
    download_to_landing,
    get_home_institution,
    issn_checksum_ok,
    lookup_issn_l,
    normalize_issn,
    parse_csv_rows,
    run_harvest,
)

logger = logging.getLogger(__name__)

SOURCE = "openapc"
BASE = "https://raw.githubusercontent.com/OpenAPC/openapc-de/master/data"

# entity_type -> URL. Every file lands raw; only apc + ta are normalized.
FILES: dict[str, str] = {
    "apc": f"{BASE}/apc_de.csv",
    "ta": f"{BASE}/transformative_agreements/transformative_agreements.csv",
    "contracts": f"{BASE}/transformative_agreements/contracts.csv",
    "additional_costs": f"{BASE}/additional_costs.csv",
    "bpc": f"{BASE}/bpc.csv",
}

Resolver = Callable[[str | None], Awaitable[str | None]]

# OpenAPC writes missing values as NA (plus the usual empties).
_MISS = {"", "na", "nan", "none", "null", "-"}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    return v if v.lower() not in _MISS else None


def _to_int(value: str | None) -> int | None:
    v = _clean(value)
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _to_euro(value: str | None) -> float | None:
    v = _clean(value)
    if v is None:
        return None
    try:
        return round(float(v), 2)
    except ValueError:
        return None


def _to_bool(value: str | None) -> bool | None:
    v = _clean(value)
    if v is None:
        return None
    return {"true": True, "false": False}.get(v.lower())


async def build_aggregates(
    rows: list[dict[str, str]], resolve: Resolver
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Group apc_de + TA rows by (issn_l, period) -> insert-ready aggregate dicts.

    A row's own issn_l column wins; otherwise resolve(issn), a strict
    issn_map lookup (None when unmapped — never key a non-linking ISSN).
    Rows with no ISSN-L or no parseable period are skipped and counted.
    """
    groups: dict[tuple[str, int], list[float | None]] = {}
    counters = {"rows": len(rows), "unresolved_issn": 0, "invalid_issn": 0, "skipped": 0}
    for row in rows:
        try:
            issn_l = normalize_issn(_clean(row.get("issn_l")))
            if issn_l is None:
                issn_l = await resolve(_clean(row.get("issn")))
            if issn_l is not None and not issn_checksum_ok(issn_l):
                counters["invalid_issn"] += 1
                logger.warning(
                    "openapc: checksum-invalid ISSN %r skipped (doi=%s)", issn_l, row.get("doi")
                )
                continue
            period = _to_int(row.get("period"))
            if issn_l is None:
                counters["unresolved_issn"] += 1
                continue
            if period is None:
                counters["skipped"] += 1
                continue
            groups.setdefault((issn_l, period), []).append(_to_euro(row.get("euro")))
        except Exception:  # per-record isolation: one bad row never kills the run
            counters["skipped"] += 1
            logger.warning("openapc aggregate row skipped: %r", row.get("doi"))
    aggregates = []
    for (issn_l, period), euros in sorted(groups.items()):
        vals = [e for e in euros if e is not None]
        aggregates.append(
            {
                "issn_l": issn_l,
                "period": period,
                "source": SOURCE,
                "article_count": len(euros),
                "euro_min": min(vals) if vals else None,
                "euro_max": max(vals) if vals else None,
                "euro_mean": round(fmean(vals), 2) if vals else None,
            }
        )
    return aggregates, counters


async def build_evidence(
    ta_rows: list[dict[str, str]],
    institution_name: str,
    resolve: Resolver,
    contracts_map: dict[str, str],
) -> tuple[list[dict[str, Any]], int]:
    """TA rows for one institution -> apc_evidence field dicts (+ verbatim payloads).

    resolve must return None when unmapped: a third-party ISSN is not
    assumed to be a linking ISSN. Returns (items, agreements filled from
    contracts). Items get their final source_pk in ingest_evidence().
    """
    target = institution_name.strip().lower()
    items: list[dict[str, Any]] = []
    filled = 0
    for row in ta_rows:
        institution = _clean(row.get("institution"))
        if institution is None or institution.lower() != target:
            continue
        group_id = _clean(row.get("group_id"))
        doi = _clean(row.get("doi"))
        issn_l = normalize_issn(_clean(row.get("issn_l")))
        if issn_l is not None and not issn_checksum_ok(issn_l):
            logger.warning(
                "openapc evidence: checksum-invalid ISSN %r dropped (doi=%s)", issn_l, doi
            )
            issn_l = None
        if issn_l is None:
            issn_l = await resolve(_clean(row.get("issn")))
        agreement = _clean(row.get("agreement"))
        if agreement is None and group_id and group_id in contracts_map:
            agreement = contracts_map[group_id]
            filled += 1
        items.append(
            {
                "source_pk": f"{group_id}|{doi}" if (group_id or doi) else None,
                "payload": dict(row),
                "fields": {
                    "doi": doi,
                    "period": _to_int(row.get("period")),
                    "euro": _to_euro(row.get("euro")),
                    "is_hybrid": _to_bool(row.get("is_hybrid")),
                    "agreement": agreement,
                    "group_id": group_id,
                    "issn_l": issn_l,
                },
            }
        )
    return items, filled


async def _body(ingest: IngestSession, limit: int | None) -> dict[str, Any]:
    session = ingest.session
    settings = get_settings()
    stats: dict[str, Any] = {"files_new": 0, "files_known": 0}

    # 1. Land every file; record paths from raw_files so normalization always
    # re-reads the stored copy.
    paths: dict[str, Path] = {}
    for entity_type, url in FILES.items():
        data, is_new = await download_to_landing(
            session, ingest, SOURCE, entity_type, url, ".csv", source_pk=url
        )
        raw = await session.scalar(
            select(RawFile).where(
                RawFile.source == SOURCE,
                RawFile.entity_type == entity_type,
                RawFile.source_pk == url,
                RawFile.content_hash == sha256_bytes(data),
            )
        )
        assert raw is not None, f"landed file not recorded for {entity_type}"
        paths[entity_type] = Path(raw.path)
        stats["files_new" if is_new else "files_known"] += 1
    await ingest.commit()

    def rows_for(entity_type: str) -> list[dict[str, str]]:
        rows = parse_csv_rows(paths[entity_type].read_bytes())
        return rows[:limit] if limit else rows

    # In-memory caches: the TA file alone holds tens of thousands of ISSNs.
    # Strict (issn_map only) per coordinator: never key on a passthrough ISSN.
    resolved: dict[str | None, str | None] = {}

    async def resolve(issn: str | None) -> str | None:
        if issn not in resolved:
            resolved[issn] = await lookup_issn_l(session, issn)
        return resolved[issn]

    # 2. contracts.csv -> group_id -> contract_name (live-verified columns).
    contract_rows = parse_csv_rows(paths["contracts"].read_bytes())
    stats["contracts_rows"] = len(contract_rows)
    contracts_map = {
        gid: name
        for r in contract_rows
        if (gid := _clean(r.get("group_id"))) and (name := _clean(r.get("contract_name")))
    }
    logger.info(
        "contracts.csv: %d rows, %d with group_id+contract_name",
        len(contract_rows),
        len(contracts_map),
    )

    # 3. Journal aggregates over apc_de + TA (full replace).
    aggregates, agg_counters = await build_aggregates(rows_for("apc") + rows_for("ta"), resolve)
    stats.update({f"aggregate_{k}": v for k, v in agg_counters.items()})
    stats["aggregate_rows"] = len(aggregates)
    await session.execute(delete(JournalApcAggregate).where(JournalApcAggregate.source == SOURCE))
    if aggregates:
        await session.execute(insert(JournalApcAggregate), aggregates)
    await ingest.commit()

    # 4. Per-article evidence for the home institution (full replace).
    home = await get_home_institution(session)
    evidence, filled = await build_evidence(
        rows_for("ta"), settings.institution_name, resolve, contracts_map
    )
    stats["twente_rows"] = len(evidence)
    stats["contracts_agreement_fills"] = filled
    stats["evidence_unresolved_issn"] = sum(1 for e in evidence if e["fields"]["issn_l"] is None)
    for i, item in enumerate(evidence):
        item["source_pk"] = item["source_pk"] or str(i)
        await ingest.ingest_record(item["source_pk"], item["payload"])
    await ingest.commit()  # source_records need ids before apc_evidence can link them
    # Latest source_record per evidence pk. Unchanged rows are ingest
    # duplicates (no row for THIS run), so the lookup cannot be scoped to
    # the current run or a second run would NULL every provenance link.
    record_ids = dict(
        (
            await session.execute(
                select(SourceRecord.source_pk, SourceRecord.id)
                .ext(distinct_on(SourceRecord.source_pk))
                .where(
                    SourceRecord.source == SOURCE,
                    SourceRecord.entity_type == "apc_row",
                    SourceRecord.source_pk.in_([i["source_pk"] for i in evidence]),
                )
                .order_by(SourceRecord.source_pk, SourceRecord.harvested_at.desc())
            )
        ).all()
    )
    await session.execute(delete(ApcEvidence).where(ApcEvidence.source == SOURCE))
    if evidence:
        await session.execute(
            insert(ApcEvidence),
            [
                {
                    **item["fields"],
                    "institution_id": home.id,
                    "source": SOURCE,
                    "source_record_id": record_ids.get(item["source_pk"]),
                }
                for item in evidence
            ],
        )
    stats["evidence_rows"] = len(evidence)
    await ingest.commit()
    return stats


async def main(session: AsyncSession, limit: int | None = None) -> dict[str, Any]:
    """Land OpenAPC CSVs, rebuild journal aggregates + home-institution evidence.

    --limit caps rows parsed per normalized file (smoke runs).
    """
    stats = await run_harvest(
        SOURCE,
        "apc_row",
        "all",
        {"urls": list(FILES.values()), "limit": limit},
        lambda ingest: _body(ingest, limit),
        session,
    )
    await refresh_apcs(session)
    await session.commit()
    for key in sorted(stats):
        print(f"{key}: {stats[key]}")
    return stats
