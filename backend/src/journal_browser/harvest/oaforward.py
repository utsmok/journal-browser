"""OA Forward registry of open publishing agreements (formerly the ESAC registry).

The registry is one published Google Sheet with a row per agreement
reported to OA Forward, national and local, plus one HTML page per
agreement with the reported terms. openaccess.nl and JCT already cover the
Dutch national (UKB/SURF) deals, so this harvest keeps only the agreements
a hosted institution signed itself: rows whose "Consortium / Institution"
cell is a name of an active institution (its name, its short name, or a
name on its ROR record).

The registry has no journal list. A current agreement from it covers no
journals until an admin adds them in the deal editor, and stays flagged
for curation until then. Reconcile never merges these rows: an
institution's own agreement is not the narrative of a national
openaccess.nl deal.
"""

import json
import logging
from datetime import UTC, date, datetime
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import ColumnElement, exists, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..identifiers import normalize_ror
from ..ingest import IngestSession, apply_overrides
from ..models import Deal, DealInstitution, DealJournal, Institution, ManualOverride, Publisher
from .common import (
    download_to_landing,
    fetch_bytes,
    parse_csv_rows,
    require_headers,
    run_harvest,
)
from .deal_publishers import CODE_ALIASES, code_of
from .jct import split_esac_id
from .ror import ROR_API

logger = logging.getLogger(__name__)

SOURCE = "oaforward"
INDEX_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vQWVZX-8YWfPcMoOHU3WNzutKrNwMhQ3JXNHhMmkOwP7VSyosKNoinzb2shRHfWwP-FRkVEtdhGUllS"
    "/pub?output=csv"
)

#: Curation reason on a current agreement that has no journal list yet.
NO_JOURNALS_REASON = "OA Forward lists no journals for this agreement; add its journal list"

# Deal fields this source owns; ManualOverride rows win over re-ingestion.
_DEAL_FIELDS = ["publisher_id", "status", "start_year", "end_year", "summary"]

# Agreement-page rows the index sheet already carries.
_IDENTITY_LABELS = {
    "publisher",
    "agreement id",
    "agreement labeling",
    "agreement period",
    "consortia / institution",
    "country",
    "request contact to the licensee",
}

# Page headings with no question under them, in sentence case.
_HEADING_LABELS = {
    "OA LICENSE": "OA license",
    "PERPETUAL ACCESS RIGHTS": "Perpetual access rights",
    "WORKFLOW ASSESSMENT": "Workflow assessment",
}


def is_oaforward_deal() -> ColumnElement[bool]:
    """SQL test for a deal this harvest wrote (its provenance names it)."""
    return Deal.provenance.contains([{"source": SOURCE}])


def _ours(entry: Any) -> bool:
    return isinstance(entry, dict) and entry.get("source") == SOURCE


def from_oaforward(provenance: list[Any] | None) -> bool:
    return any(_ours(e) for e in provenance or [])


def parse_us_date(value: str | None) -> date | None:
    """'12/31/2025' -> date(2025, 12, 31); None when unparseable."""
    try:
        return datetime.strptime((value or "").strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def parse_registry(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Index sheet rows -> agreement dicts; rows without an Agreement ID are skipped."""
    require_headers(
        rows,
        {
            "Publisher",
            "Consortium / Institution",
            "Start date",
            "End date",
            "Labeling",
            "Agreement ID",
            "Link to agreement page",
        },
        "oaforward registry",
    )
    agreements = []
    seen: set[str] = set()
    for row in rows:
        esac_id = (row.get("Agreement ID") or "").strip()
        if not esac_id or esac_id in seen:
            continue
        seen.add(esac_id)
        agreements.append(
            {
                "esac_id": esac_id,
                "publisher": (row.get("Publisher") or "").strip(),
                "institution": (row.get("Consortium / Institution") or "").strip(),
                "start": parse_us_date(row.get("Start date")),
                "end": parse_us_date(row.get("End date")),
                "labeling": (row.get("Labeling") or "").strip() or None,
                "page_url": (row.get("Link to agreement page") or "").strip() or None,
                "raw": row,
            }
        )
    return agreements


def _lines(cell: Any) -> list[str]:
    return [s for s in (part.strip() for part in cell.get_text("\n").split("\n")) if s]


def parse_agreement_page(html: str) -> dict[str, str | None]:
    """Agreement page -> conditions_text (one "label: value" line per reported
    term) and article_types_text. Terms the index sheet carries are left out."""
    soup = BeautifulSoup(html, "lxml")
    conditions: list[str] = []
    article_types: str | None = None
    for tr in soup.select("table tr"):
        cells = tr.find_all("td")
        if len(cells) != 2:
            continue
        strong = cells[0].find("strong")
        heading = " ".join(strong.get_text(" ").split()) if strong else ""
        label_lines = _lines(cells[0])
        question = " ".join(line for line in label_lines if line != heading).strip()
        value = _lines(cells[1])
        if not value or (question or heading).casefold() in _IDENTITY_LABELS:
            continue
        if heading == "ARTICLE TYPES":
            article_types = "\n".join(value)
            continue
        label = question or _HEADING_LABELS.get(heading, heading.capitalize())
        conditions.append(f"{label}: {', '.join(value)}")
    return {
        "conditions_text": "\n".join(conditions) or None,
        "article_types_text": article_types,
    }


async def institution_names(session: AsyncSession) -> dict[str, int]:
    """Casefolded name -> institution id for every active institution: its
    name, short name, and the names on its ROR record."""
    names: dict[str, int] = {}
    institutions = (
        await session.scalars(select(Institution).where(Institution.active.is_(True)))
    ).all()
    for inst in institutions:
        candidates = [inst.name, inst.short_name]
        ror = normalize_ror(inst.ror)
        if ror:
            record = json.loads(await fetch_bytes(f"{ROR_API}{ror}"))
            candidates += [n.get("value") for n in record.get("names", [])]
        for name in candidates:
            if name and name.strip():
                names[name.strip().casefold()] = inst.id
    return names


async def _publisher_id(session: AsyncSession, esac_id: str, name: str) -> int:
    """The publisher row the deal sits on: the openaccess.nl name the ESAC
    code maps to, else the row with the registry's exact name, else a new
    row. Fuzzy matching is out: "The Royal Society" is not the Royal Society
    of Chemistry."""
    for candidate in (CODE_ALIASES.get(code_of(esac_id) or ""), name):
        if candidate:
            pid = await session.scalar(select(Publisher.id).where(Publisher.name == candidate))
            if pid is not None:
                return pid
    pub = Publisher(name=name)
    session.add(pub)
    await session.flush()
    return pub.id


async def _store_agreement(
    session: AsyncSession,
    agreement: dict[str, Any],
    page: dict[str, str | None],
    institution_id: int,
    today: date,
    fetched_at: str,
) -> Deal:
    existing = await session.scalar(select(Deal).where(Deal.esac_id == agreement["esac_id"]))
    start, end = agreement["start"], agreement["end"]
    start_year = start.year if start else None
    end_year = end.year if end else None
    links = [{"url": agreement["page_url"], "text": "OA Forward registry", "category": "registry"}]
    values: dict[str, Any] = {
        "publisher_id": await _publisher_id(session, agreement["esac_id"], agreement["publisher"]),
        "consortium": split_esac_id(agreement["esac_id"])[2],
        "status": "archive" if end is not None and end < today else "current",
        "start_year": start_year,
        "end_year": end_year,
        "duration_text": "-".join(str(y) for y in (start_year, end_year) if y is not None) or None,
        "summary": agreement["labeling"],
        "conditions_text": page["conditions_text"],
        "article_types_text": page["article_types_text"],
        "provenance": [
            *[e for e in (existing.provenance or [] if existing else []) if not _ours(e)],
            {"source": SOURCE, "url": INDEX_URL, "fetched_at": fetched_at},
            {"source": SOURCE, "url": agreement["page_url"], "fetched_at": fetched_at},
        ],
    }
    if existing is None:
        deal = Deal(esac_id=agreement["esac_id"], links=links, **values)
        session.add(deal)
        await session.flush()
    else:
        deal = existing
        for key, value in values.items():
            setattr(deal, key, value)
        other_links = [link for link in deal.links or [] if link.get("category") != "registry"]
        deal.links = [*other_links, *links]
    await apply_overrides(session, "deals", str(deal.id), deal, _DEAL_FIELDS)

    removed = await session.scalar(
        select(ManualOverride.id).where(
            ManualOverride.table_name == "deal_institutions",
            ManualOverride.row_key == f"{deal.id}:{institution_id}",
            ManualOverride.field == "removed",
        )
    )
    if removed is None:
        await session.execute(
            pg_insert(DealInstitution)
            .values(
                deal_id=deal.id,
                institution_id=institution_id,
                participation="named",
                participation_note="Licensee in the OA Forward registry",
            )
            .on_conflict_do_update(
                index_elements=["deal_id", "institution_id"],
                set_={"participation": "named"},
            )
        )

    has_journals = await session.scalar(
        select(exists().where(DealJournal.deal_id == deal.id, DealJournal.excluded.is_not(True)))
    )
    if deal.status == "current" and not has_journals:
        dismissed = not deal.needs_curation and deal.curation_resolved_reason == NO_JOURNALS_REASON
        if not deal.needs_curation and not dismissed:
            deal.needs_curation = True
            deal.needs_curation_reason = NO_JOURNALS_REASON
            deal.curation_resolved_reason = None
    elif deal.needs_curation_reason == NO_JOURNALS_REASON:
        deal.needs_curation = False
        deal.needs_curation_reason = None
    if deal.curation_resolved_reason == NO_JOURNALS_REASON and (
        deal.status != "current" or has_journals
    ):
        deal.curation_resolved_reason = None
    return deal


async def main(session: AsyncSession, limit: int | None = None) -> dict[str, Any]:
    """Store every registry agreement a hosted institution signed itself."""

    async def body(ingest: IngestSession) -> dict[str, Any]:
        fetched_at = datetime.now(UTC).isoformat()
        today = datetime.now(UTC).date()
        index_data, _ = await download_to_landing(
            session, ingest, SOURCE, "index", INDEX_URL, suffix=".csv"
        )
        agreements = parse_registry(parse_csv_rows(index_data))
        names = await institution_names(session)
        matched = [
            (a, names[a["institution"].casefold()])
            for a in agreements
            if a["institution"].casefold() in names
        ]
        if limit is not None:
            matched = matched[:limit]
        stats: dict[str, Any] = {
            "registry_rows": len(agreements),
            "agreements": 0,
            "current": 0,
            "failed": [],
        }
        for agreement, institution_id in matched:
            esac_id = agreement["esac_id"]
            try:
                page: dict[str, str | None] = {"conditions_text": None, "article_types_text": None}
                if agreement["page_url"]:
                    html, _ = await download_to_landing(
                        session,
                        ingest,
                        SOURCE,
                        "agreement",
                        agreement["page_url"],
                        suffix=".html",
                        source_pk=esac_id,
                    )
                    page = parse_agreement_page(html.decode("utf-8", errors="replace"))
                await ingest.ingest_record(
                    esac_id, payload={"index_row": agreement["raw"], "page": page}
                )
                deal = await _store_agreement(
                    session, agreement, page, institution_id, today, fetched_at
                )
            except Exception as exc:
                await session.rollback()
                stats["failed"].append({"esac_id": esac_id, "error": str(exc)[:200]})
                await ingest.record_parse_failure({"source_pk": esac_id, "reason": str(exc)[:200]})
                continue
            stats["agreements"] += 1
            stats["current"] += deal.status == "current"
            await ingest.commit()
        return stats

    stats = await run_harvest(
        SOURCE, "deal", "all", {"index_url": INDEX_URL, "limit": limit}, body, session
    )
    print(
        f"oaforward: registry_rows={stats.get('registry_rows')} "
        f"agreements={stats.get('agreements')} current={stats.get('current')} "
        f"failed={stats.get('failed')}"
    )
    return stats
