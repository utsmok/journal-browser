"""Reconstruct eme2025ukb deal journals from the signed SURF-Emerald contract.

The JCT dump links eme2025ukb to the Elsevier sheet (upstream index error,
confirmed 2026-10-22) and publishes no correct Emerald sheet yet. Sam
extracted the journal title list from the contract PDF (scanned -> OCR ->
xlsx) at /mnt/c/users/sam/downloads. This job:

1. copies the contract file into the landing zone (evidence),
2. pulls all Emerald sources from OpenAlex (host_organization filter),
3. matches contract titles -> sources (normalized exact, then difflib),
4. upserts deal_journals (source='manual') + the home deal_institution,
5. clears needs_curation with the provenance in the reason.

Usage: uv run python jobs/ingest_emerald_contract.py [path-to-xlsx]
"""

import asyncio
import difflib
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import get_home_institution
from journal_browser.models import Deal, DealInstitution, DealJournal

CONTRACT_DEFAULT = Path(
    "/mnt/c/users/sam/downloads/Emerald Agreement 2025-2027_Geredigeerd-ocr copy.xlsx"
)
EMERALD_HOST_ORG = "P4310319811"
ESAC_ID = "eme2025ukb"


def _norm(title: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", str(title).casefold()).strip()


def load_contract_titles(path: Path) -> list[str]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb[wb.sheetnames[0]]
    titles = []
    for row in ws.iter_rows(values_only=True):
        title = row[0]
        # Data rows carry a subject collection in col B; footers and the
        # repeated OCR page-break headers ('Title') do not.
        if not title or row[1] is None or str(title).strip() == "Title":
            continue
        titles.append(str(title).strip())
    return titles


async def fetch_emerald_sources() -> list[dict]:
    """All OpenAlex sources under the Emerald host organization."""
    from aletheca import AlethecaClient
    from aletheca.endpoints import SourcesFilters

    out = []
    client_kwargs: dict = {}
    if api_key := get_settings().openalex_api_key:
        client_kwargs["api_key"] = api_key
    async with AlethecaClient(**client_kwargs) as client:
        async for s in client.sources.iterate(
            filters=SourcesFilters(host_organization=EMERALD_HOST_ORG)
        ):
            out.append(
                {
                    "id": s.id,
                    "display_name": s.display_name,
                    "issn": list(getattr(s, "issn", None) or []),
                    "issn_l": getattr(s, "issn_l", None),
                }
            )
    return out


def match_titles(contract: list[str], sources: list[dict]) -> tuple[dict[str, dict], list[str]]:
    """(contract title -> source) exact + fuzzy; unmatched titles returned.

    OpenAlex names are often shorter than contract titles (subtitles such
    as ': An International Journal' are dropped), so the primary part
    before a subtitle separator is matched too.
    """
    by_norm = {_norm(s["display_name"]): s for s in sources if s["display_name"]}

    def _hit(title: str) -> dict | None:
        norm = _norm(title)
        if hit := by_norm.get(norm):
            return hit
        if near := difflib.get_close_matches(norm, list(by_norm), n=1, cutoff=0.92):
            return by_norm[near[0]]
        # Primary part before a subtitle separator.
        primary = _norm(re.split(r"[:\-–]\s", title)[0] if re.search(r"[:\-–]\s", title) else title)
        if len(primary) >= 8:
            if hit := by_norm.get(primary):
                return hit
            if near := difflib.get_close_matches(primary, list(by_norm), n=1, cutoff=0.94):
                return by_norm[near[0]]
        return None

    # Titles the OCR scan mangled beyond fuzzy reach; value = OpenAlex
    # source id verified against the API (Archnet-IJAR, S4210183932).
    by_source_id = {s["id"]: s for s in sources if s.get("id")}
    aliases = {
        "Archnet-lJAR: International Journal of Architectural": by_source_id.get(
            "https://openalex.org/S4210183932"
        ),
    }

    matched: dict[str, dict] = {}
    unmatched: list[str] = []
    for title in contract:
        hit = _hit(title)
        if hit is None:
            # OCR text varies in lookalike glyphs/whitespace: match by
            # normalized prefix.
            hit = next(
                (src for key, src in aliases.items() if _norm(title).startswith(_norm(key)[:20])),
                None,
            )
        if hit is None:
            unmatched.append(title)
        else:
            matched[title] = hit
    return matched, unmatched


async def resolve_unmatched(unmatched: list[str]) -> dict[str, dict]:
    """Search OpenAlex sources by title for contract titles the host-org
    filter missed (renamed or differently-attributed Emerald journals).

    Raw API call: aletheca's sources.search maps the query to the `page`
    parameter (bibliofabric bug).
    """
    import httpx

    resolved: dict[str, dict] = {}
    if not unmatched:
        return resolved
    params_base: dict[str, Any] = {"per_page": 5}
    if api_key := get_settings().openalex_api_key:
        params_base["api_key"] = api_key
    async with httpx.AsyncClient(timeout=60) as client:
        for title in unmatched:
            try:
                resp = await client.get(
                    "https://api.openalex.org/sources",
                    params={**params_base, "search": title},
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])
            except Exception as exc:  # noqa: BLE001 - per-record resilience
                print(f"  search failed for {title!r}: {exc}")
                continue
            norm_query = _norm(title)
            for s in results[:3]:
                host = (s.get("host_organization_name") or "").casefold()
                same_name = _norm(s.get("display_name") or "") == norm_query
                if "emerald" not in host and not same_name:
                    continue
                resolved[title] = {
                    "id": s.get("id"),
                    "display_name": s.get("display_name"),
                    "issn": list(s.get("issn") or []),
                    "issn_l": s.get("issn_l"),
                }
                break
    return resolved


async def main(session, contract_path: Path) -> None:
    deal = (await session.execute(select(Deal).where(Deal.esac_id == ESAC_ID))).scalar_one()

    landing = Path(get_settings().landing_dir) / "emerald_contract"
    landing.mkdir(parents=True, exist_ok=True)
    local = landing / contract_path.name
    if contract_path.exists() and not local.exists():
        shutil.copy2(contract_path, local)

    titles = load_contract_titles(contract_path)
    sources = await fetch_emerald_sources()
    matched, unmatched = match_titles(titles, sources)
    resolved = await resolve_unmatched(unmatched)
    for title in resolved:
        unmatched.remove(title)
        matched[title] = resolved[title]

    # Replace any previous derived rows for this deal, then write the
    # contract-reconstructed list (never touches other deals).
    await session.execute(DealJournal.__table__.delete().where(DealJournal.deal_id == deal.id))
    for title, s in matched.items():
        issn = (s.get("issn") or [None])[0]
        if not issn:
            continue
        session.add(
            DealJournal(
                deal_id=deal.id,
                issn=issn,
                issn_l=s.get("issn_l"),
                journal_name=title,
                source="manual",
            )
        )
    home = await get_home_institution(session)
    # The contract parties for this SURF deal are Twente only; a JCT re-ingest
    # links the Elsevier sheet's institution set, so clear everything else.
    await session.execute(
        DealInstitution.__table__.delete().where(
            DealInstitution.deal_id == deal.id,
            DealInstitution.institution_id != home.id,
        )
    )
    await session.execute(
        pg_insert(DealInstitution)
        .values(
            deal_id=deal.id,
            institution_id=home.id,
            first_seen=str(date.today()),
            last_seen=str(date.today()),
        )
        .on_conflict_do_update(
            index_elements=["deal_id", "institution_id"],
            set_={"last_seen": str(date.today())},
        )
    )
    deal.needs_curation = bool(unmatched)
    deal.needs_curation_reason = (
        f"Journal list reconstructed from the signed SURF-Emerald contract "
        f"({len(matched)}/{len(titles)} titles matched to OpenAlex sources; "
        f"{len(unmatched)} unmatched). Derived manually because the JCT dump "
        f"still links this esac to the Elsevier sheet; a JCT re-ingest must "
        f"not overwrite the manual rows until JCT publishes correct data."
        if True
        else None
    )
    deal.last_reviewed = date.today()
    await session.commit()

    print(f"contract titles: {len(titles)}")
    print(f"openalex emerald sources: {len(sources)}")
    print(f"matched: {len(matched)}  unmatched: {len(unmatched)}")
    for t in unmatched:
        print("  UNMATCHED:", t)
    if local.exists():
        print(f"contract archived: {local}")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else CONTRACT_DEFAULT

    async def run() -> None:
        engine = create_async_engine(get_settings().database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await main(session, path)
        await engine.dispose()

    asyncio.run(run())
