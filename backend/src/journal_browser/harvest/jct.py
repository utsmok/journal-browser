"""JCT (cOAlition S Journal Checker Tool) public dump harvest.

The dump is a two-level structure: an index sheet of current transformative
agreements (one row per ESAC ID, with a per-agreement published-CSV URL) and
one CSV per agreement whose rows are a journals x institutions cross product.
Everything is collected verbatim (landing copy + source_records) before any
normalization; publisher names are placeholder codes until reconcile.

openaccess.nl is the primary source for the Dutch deals. A journal list is
stored only when it is the agreement's own (deal_publishers judges it by
the publisher its journals resolve to), and JCT never overwrites the
publisher, status or period of a deal row that openaccess.nl owns.
"""

import asyncio
import logging
import random
import re
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import case, func, select, text
from sqlalchemy import delete as sa_delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..ingest import IngestSession, apply_overrides
from ..models import Deal, DealInstitution, DealJournal, Institution, ManualOverride, Publisher
from .common import (
    download_to_landing,
    normalize_issn,
    parse_csv_rows,
    require_headers,
    run_harvest,
)
from .deal_publishers import (
    SHEET_REJECTED_KEY,
    SheetPublishers,
    family_of,
    flag,
    flag_owned,
    issn_publisher_counts,
    judge,
    list_flag_dismissed,
    load_sheet_publishers,
    rejected_sheet,
    withheld,
)

logger = logging.getLogger(__name__)

INDEX_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vStezELi7qnKcyE8OiO2OYx2kqQDOnNsDX1JfAsK487n2uB_Dve5iDTwhUFfJ7eFPDhEjkfhXhqVTGw"
    "/pub?gid=1130349201&single=true&output=csv"
)

# e.g. kar2026caul -> ("kar", 2026, "caul"); letters/year optional.
_ESAC_RE = re.compile(r"^([A-Za-z]*)(\d{4})?(.*)$")

# Deal fields this source owns; ManualOverride rows win over re-ingestion.
_DEAL_FIELDS = [
    "publisher_id",
    "consortium",
    "status",
    "start_year",
    "end_year",
    "corresponding_authors_only",
    "jct_data_url",
    "last_reviewed",
    "provenance",
]


def split_esac_id(esac_id: str) -> tuple[str | None, int | None, str | None]:
    """ESAC ID -> (publisher code, start year, consortium) or Nones."""
    m = _ESAC_RE.match(esac_id.strip())
    assert m is not None  # every group is optional, so the pattern always matches
    code, year, suffix = m.group(1), m.group(2), m.group(3).strip()
    return (code.lower() or None, int(year) if year else None, suffix or None)


def parse_index(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Index sheet rows -> agreement dicts; rows without ESAC ID + Data URL skipped."""
    require_headers(
        rows,
        {"ESAC ID", "Data URL", "End Date", "C/A Only", "Last Reviewed"},
        "jct index",
    )
    agreements = []
    seen: set[str] = set()
    for row in rows:
        esac_id = (row.get("ESAC ID") or "").strip()
        data_url = (row.get("Data URL") or "").strip()
        if not esac_id or not data_url or esac_id in seen:
            continue
        seen.add(esac_id)
        agreements.append(
            {
                "esac_id": esac_id,
                "end_date": (row.get("End Date") or "").strip(),
                "ca_only": (row.get("C/A Only") or "").strip().lower(),
                "data_url": data_url,
                "last_reviewed": (row.get("Last Reviewed") or "").strip(),
                "raw": row,
            }
        )
    return agreements


def row_issn(row: dict[str, str]) -> str | None:
    """Online ISSN preferred over print; None when neither is ISSN-shaped."""
    return normalize_issn(row.get("ISSN (Online)")) or normalize_issn(row.get("ISSN (Print)"))


def parse_agreement(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], int]:
    """Cross-product rows -> (unique journal rows, unique institution rows, skipped).

    Journal rows are unique by (name, print, online); rows where neither ISSN
    normalizes are skipped and counted once per unique journal. Institution
    rows are unique by ROR; rows without a ROR are ignored.
    Rows are returned verbatim.
    """
    require_headers(
        rows,
        {
            "Journal Name",
            "ISSN (Print)",
            "ISSN (Online)",
            "ROR ID",
            "Institution Name",
            "Institution First Seen",
            "Institution Last Seen",
            "Journal First Seen",
            "Journal Last Seen",
        },
        "jct agreement",
    )
    journals: list[dict[str, str]] = []
    institutions: list[dict[str, str]] = []
    seen_journals: set[tuple[str, str, str]] = set()
    seen_rors: set[str] = set()
    skipped_no_issn = 0
    for row in rows:
        journal_key = (
            (row.get("Journal Name") or "").strip(),
            (row.get("ISSN (Print)") or "").strip(),
            (row.get("ISSN (Online)") or "").strip(),
        )
        if journal_key not in seen_journals:
            seen_journals.add(journal_key)
            if row_issn(row) is None:
                skipped_no_issn += 1
            else:
                journals.append(row)
        ror = (row.get("ROR ID") or "").strip()
        if ror and ror not in seen_rors:
            seen_rors.add(ror)
            institutions.append(row)
    return journals, institutions, skipped_no_issn


def _parse_year(value: str) -> int | None:
    return int(value[:4]) if len(value) >= 4 and value[:4].isdigit() else None


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


def _download_failure(esac_id: str, url: str, exc: Exception) -> dict[str, Any]:
    """Stats record for a sheet download that exhausted its retries."""
    response = getattr(exc, "response", None)
    return {
        "esac_id": esac_id,
        "url": url,
        "status": getattr(response, "status_code", None),
        "body_snippet": (getattr(response, "text", None) or str(exc))[:200],
    }


async def _upsert_publisher(session: AsyncSession, code: str) -> int:
    """Placeholder publisher row per ESAC code; reconcile assigns real names."""
    name = code.upper()
    result = await session.execute(
        pg_insert(Publisher)
        .values(name=name)
        .on_conflict_do_nothing(index_elements=["name"])
        .returning(Publisher.id)
    )
    publisher_id = result.scalar()
    if publisher_id is None:
        publisher_id = await session.scalar(select(Publisher.id).where(Publisher.name == name))
    assert publisher_id is not None
    return publisher_id


async def _upsert_institution(session: AsyncSession, ror: str, name: str) -> int:
    """Insert the institution if its ROR is new; existing rows are left alone so
    reconciled names and configuration survive re-ingestion. institutions.name is
    unique across different RORs (e.g. two 'Open University's), so a colliding
    name gets the ROR id as a suffix."""
    institution_id = await session.scalar(select(Institution.id).where(Institution.ror == ror))
    if institution_id is not None:
        return institution_id
    if await session.scalar(select(Institution.id).where(Institution.name == name)) is not None:
        name = f"{name} [{ror.rsplit('/', 1)[-1]}]"
    institution_id = (
        await session.execute(
            pg_insert(Institution)
            .values(name=name, ror=ror)
            .on_conflict_do_nothing(index_elements=["ror"])
            .returning(Institution.id)
        )
    ).scalar()
    if institution_id is None:  # same ROR inserted earlier in this uncommitted run
        institution_id = await session.scalar(select(Institution.id).where(Institution.ror == ror))
    assert institution_id is not None
    return institution_id


async def _store_agreement(
    session: AsyncSession,
    agreement: dict[str, Any],
    journals: list[dict[str, str]],
    institutions: list[dict[str, str]],
    fetched_at: str,
    sheets: SheetPublishers | None = None,
) -> str | None:
    """Upsert the agreement row and its sheet. Returns the reason when the
    sheet belongs to another publisher and was withheld.

    A withheld sheet leaves no journal list on the deal: rows an earlier
    ingest stored from it go too. Excluded rows stay (an admin's removals
    are tombstones the next upsert must not resurrect). The participant list
    is stored either way: participation is a fact of the agreement, not of
    its journal list.
    """
    code, start_year, consortium = split_esac_id(agreement["esac_id"])
    # Refresh this source's provenance entries; entries from other sources
    # (owner curation docs, openaccess.nl merges) are history and stay.
    existing = await session.scalar(select(Deal).where(Deal.esac_id == agreement["esac_id"]))
    prior = [
        entry
        for entry in ((existing.provenance or []) if existing is not None else [])
        if not (isinstance(entry, dict) and entry.get("source") == "jct")
    ]
    if sheets is None:
        sheets = await load_sheet_publishers(session)
    sheet_entry: dict[str, Any] = {
        "source": "jct",
        "url": agreement["data_url"],
        "fetched_at": fetched_at,
    }
    deal_family = (sheets.families.get(existing.id) if existing is not None else None) or family_of(
        agreement["esac_id"], code.upper() if code else None
    )
    withheld_reason = withheld(
        judge(
            await issn_publisher_counts(session, [i for r in journals if (i := row_issn(r))]),
            family=deal_family,
            exclude=existing.id if existing is not None else None,
            sheets=sheets,
        ),
        rejected_sheet(existing.provenance if existing is not None else None),
    )
    if withheld_reason is not None:
        sheet_entry[SHEET_REJECTED_KEY] = withheld_reason
    values = {
        "publisher_id": await _upsert_publisher(session, code) if code else None,
        "esac_id": agreement["esac_id"],
        "consortium": consortium,
        "status": "current",  # the JCT index lists current agreements only
        "start_year": start_year,
        "end_year": _parse_year(agreement["end_date"]),
        "corresponding_authors_only": agreement["ca_only"] == "yes",
        "jct_data_url": None if withheld_reason is not None else agreement["data_url"],
        "last_reviewed": _parse_date(agreement["last_reviewed"]),
        "provenance": [
            *prior,
            {"source": "jct", "url": INDEX_URL, "fetched_at": fetched_at},
            sheet_entry,
        ],
    }
    stmt = pg_insert(Deal).values(**values)
    has_page = Deal.openaccess_nl_url.is_not(None)
    deal_id = (
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["esac_id"],
                set_={
                    **values,
                    # openaccess.nl is the primary source. JCT's publisher
                    # is a placeholder code, so it never replaces one another
                    # source set; on a row with an openaccess.nl page that
                    # source also owns the status and the period.
                    "publisher_id": Deal.publisher_id,
                    "status": case((has_page, Deal.status), else_=stmt.excluded.status),
                    "start_year": case((has_page, Deal.start_year), else_=stmt.excluded.start_year),
                    "end_year": case((has_page, Deal.end_year), else_=stmt.excluded.end_year),
                    "updated_at": func.now(),
                },
            ).returning(Deal.id)
        )
    ).scalar_one()
    deal = await session.get(Deal, deal_id)
    assert deal is not None
    await session.refresh(deal)  # the upsert ran in SQL; the loaded row is stale
    await apply_overrides(session, "deals", str(deal_id), deal, _DEAL_FIELDS)

    if withheld_reason is not None:
        await session.execute(
            sa_delete(DealJournal).where(
                DealJournal.deal_id == deal_id,
                DealJournal.source == "jct",
                DealJournal.institution_id.is_(None),
                DealJournal.excluded.is_not(True),
            )
        )
        owned = await flag_owned(session, [deal_id])
        if deal_id not in owned and not list_flag_dismissed(deal, withheld_reason):
            flag(deal, withheld_reason)
    else:
        for row in journals:
            issn = row_issn(row)
            if issn is None:  # pragma: no cover - parse_agreement already filtered
                continue
            name = _clean(row.get("Journal Name"))
            first_seen = _clean(row.get("Journal First Seen"))
            last_seen = _clean(row.get("Journal Last Seen"))
            # issn_l stays NULL; a later issn_map sweep resolves it.
            await session.execute(
                pg_insert(DealJournal)
                .values(
                    deal_id=deal_id,
                    issn=issn,
                    journal_name=name,
                    first_seen=first_seen,
                    last_seen=last_seen,
                    source="jct",
                )
                .on_conflict_do_update(
                    index_elements=["deal_id", "issn"],
                    index_where=text("institution_id IS NULL"),
                    set_={
                        "journal_name": name,
                        "first_seen": first_seen,
                        "last_seen": last_seen,
                    },
                )
            )

    for row in institutions:
        ror = row.get("ROR ID", "").strip()
        name = _clean(row.get("Institution Name")) or ror
        institution_id = await _upsert_institution(session, ror, name)
        # An admin removal is recorded as an override tombstone; respect it.
        removed = await session.scalar(
            select(ManualOverride.id).where(
                ManualOverride.table_name == "deal_institutions",
                ManualOverride.row_key == f"{deal_id}:{institution_id}",
                ManualOverride.field == "removed",
            )
        )
        if removed is not None:
            continue
        first_seen = _clean(row.get("Institution First Seen"))
        last_seen = _clean(row.get("Institution Last Seen"))
        await session.execute(
            pg_insert(DealInstitution)
            .values(
                deal_id=deal_id,
                institution_id=institution_id,
                first_seen=first_seen,
                last_seen=last_seen,
            )
            .on_conflict_do_update(
                index_elements=["deal_id", "institution_id"],
                set_={"first_seen": first_seen, "last_seen": last_seen},
            )
        )
    return withheld_reason


async def main(session: AsyncSession, limit: int | None = None) -> dict[str, Any]:
    """Download + store the whole JCT dump; `limit` caps agreements fetched."""

    async def body(ingest: IngestSession) -> dict[str, Any]:
        fetched_at = datetime.now(UTC).isoformat()
        index_data, _ = await download_to_landing(
            session, ingest, "jct", "index", INDEX_URL, suffix=".csv"
        )
        agreements = parse_index(parse_csv_rows(index_data))
        if limit is not None:
            agreements = agreements[:limit]
        # One snapshot of the stored sheets; each agreement's list is judged
        # against it.
        sheets = await load_sheet_publishers(session)
        stats: dict[str, Any] = {
            "agreements": 0,
            "agreements_failed": 0,
            "failed_downloads": [],
            "parse_failures": [],
            "journals": 0,
            "institutions": 0,
            "skipped_no_issn": 0,
            "sheets_withheld": [],
        }
        for agreement in agreements:
            # Google throttles bursts of published-CSV fetches; pace with jitter.
            await asyncio.sleep(random.uniform(0.5, 1.5))
            try:
                csv_data, _ = await download_to_landing(
                    session,
                    ingest,
                    "jct",
                    "agreement",
                    agreement["data_url"],
                    suffix=".csv",
                    source_pk=agreement["esac_id"],
                    retries=5,
                )
            except Exception as exc:
                await session.rollback()
                stats["agreements_failed"] += 1
                stats["failed_downloads"].append(
                    _download_failure(agreement["esac_id"], agreement["data_url"], exc)
                )
                await ingest.record_parse_failure(
                    {"source_pk": agreement["esac_id"], "reason": "download failed"}
                )
                continue
            try:
                journals, institutions, skipped = parse_agreement(parse_csv_rows(csv_data))
                await ingest.ingest_record(
                    agreement["esac_id"],
                    payload={
                        "index_row": agreement["raw"],
                        "journals": journals,
                        "institutions": institutions,
                    },
                )
                withheld_reason = await _store_agreement(
                    session, agreement, journals, institutions, fetched_at, sheets
                )
            except Exception as exc:
                await session.rollback()
                stats["agreements_failed"] += 1
                stats["parse_failures"].append(
                    {
                        "esac_id": agreement["esac_id"],
                        "url": agreement["data_url"],
                        "error": str(exc)[:200],
                    }
                )
                await ingest.record_parse_failure(
                    {"source_pk": agreement["esac_id"], "reason": "parse/store failed"}
                )
                continue
            stats["agreements"] += 1
            if withheld_reason is not None:
                stats["sheets_withheld"].append(agreement["esac_id"])
            else:
                stats["journals"] += len(journals)
            stats["institutions"] += len(institutions)
            stats["skipped_no_issn"] += skipped
            await ingest.commit()

        default_ror = get_settings().institution_ror
        default_esac_ids = list(
            (
                await session.execute(
                    select(Deal.esac_id)
                    .join(DealInstitution, DealInstitution.deal_id == Deal.id)
                    .join(Institution, Institution.id == DealInstitution.institution_id)
                    .where(Institution.ror == default_ror)
                )
            ).scalars()
        )
        stats["default_deals"] = len(default_esac_ids)
        stats["default_esac_ids"] = default_esac_ids
        return stats

    stats = await run_harvest(
        "jct", "deal", "all", {"index_url": INDEX_URL, "limit": limit}, body, session
    )
    print(
        "jct: "
        f"agreements={stats.get('agreements')} failed={stats.get('agreements_failed')} "
        f"journals={stats.get('journals')} institutions={stats.get('institutions')} "
        f"skipped_no_issn={stats.get('skipped_no_issn')} "
        f"default_deals={stats.get('default_deals')}"
    )
    print(f"jct default-institution esac_ids: {stats.get('default_esac_ids')}")
    print(f"jct sheets withheld (another publisher's): {stats.get('sheets_withheld')}")
    for failure in stats.get("failed_downloads", []):
        print(f"jct failed download: {failure}")
    return stats
