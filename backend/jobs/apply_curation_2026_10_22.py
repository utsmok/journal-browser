"""Apply the owner curation of 2026-10-22 (decision 13 evidence snapshot).

Reads docs/research/openaccess-nl-current-deals-2026-10-22.json (openaccess.nl
current-deals table parsed + owner_notes with journal lists) and:

1. canonicalizes publisher rows for the Twente register (real display names,
   openaccess.nl slugs, JCT code kept as alias);
2. verifies the 16 Twente deals: fills summary/conditions/workflow/contract
   from the snapshot, stamps last_reviewed, clears needs_curation, links the
   home institution;
3. seeds deal journals: parsed owner lists for AIP/IOP/IOS, publisher-derived
   sets for the "all journals" deals (ACM/ACS/AUP), leaving JCT/contract rows
   untouched.

Idempotent; existing deal_journals rows are never modified or removed.

Usage: uv run python jobs/apply_curation_2026_10_22.py
"""

import asyncio
import json
import re
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.denorm import refresh_home_deal_flags
from journal_browser.models import (
    Deal,
    DealInstitution,
    DealJournal,
    Institution,
    IssnMap,
    Journal,
    Publisher,
)

SNAPSHOT = (
    Path(__file__).resolve().parents[2]
    / "docs/research/openaccess-nl-current-deals-2026-10-22.json"
)
REVIEWED = date(2026, 10, 22)
PROVENANCE = {
    "source": "owner_curation",
    "date": "2026-10-22",
    "doc": "docs/research/openaccess-nl-current-deals-2026-10-22.json",
}

# Consortium deals already keyed by ESAC id; the rest live as openaccess.nl
# national rows (ACM/ACS/AUP/IOS) or must be created (IOP has no current NL row).
ESAC_BY_SLUG = {
    "aip-publishing-aipp": "aip2026ukb",
    "cambridge-university-press": "cam2024ukb",
    "elsevier": "els2025ukb",
    "emerald-publishing-group": "eme2025ukb",
    "oxford-university-press": "oxf2024ukb",
    "public-library-of-science-plos": "plos2025ukb",
    "royal-society-of-chemistry-rsc": "rsc2025ukb",
    "sage": "sage2026ukb",
    "springer": "sn2024ukb",
    "taylor-francis": "tf2024ukb",
    "wiley": "wiley2024ukb",
}

# JCT placeholder publisher codes, to alias/rename where no full-name row exists.
CODE_BY_SLUG = {
    "aip-publishing-aipp": "AIP",
    "american-chemical-society-acs": "ACS",
    "cambridge-university-press": "CAM",
    "de-gruyter-brill": "DGB",
    "elsevier": "ELS",
    "emerald-publishing-group": "EME",
    "iop-publishing": "IOP",
    "karger": "KAR",
    "oxford-university-press": "OXF",
    "public-library-of-science-plos": "PLOS",
    "royal-society-of-chemistry-rsc": "RSC",
    "springer": "SN",
    "taylor-francis": "TF",
    "the-company-of-biologists": "COMPBIO",
    "wiley": "WILEY",
}

# "All journals from publisher X" deals: journals.publisher_name ILIKE patterns.
PUBLISHER_PATTERNS = {
    "acm": ["association for computing machinery%"],
    "american-chemical-society-acs": ["american chemical society%"],
    "amsterdam-university-press-aup": ["amsterdam university press%"],
}


def parse_years(duration: str) -> tuple[int, int]:
    nums = re.findall(r"\d{4}", duration)
    if not nums:
        raise ValueError(duration)
    return int(nums[0]), int(nums[-1])


def parse_aip_list(notes: str) -> list[tuple[str, str]]:
    rows = []
    for chunk in notes.split("**")[1:]:
        parts = [p.strip() for p in chunk.split("|")]
        if len(parts) >= 2 and re.fullmatch(r"\d{4}-\d{3}[\dXx]", parts[1]):
            rows.append((parts[1].upper(), parts[0]))
    # fallback: rows that lost their pipe separators ("Title issn https://...")
    seen = {issn for issn, _ in rows}
    for m in re.finditer(
        r"([A-Za-z][A-Za-z0-9 .&'\-]*?)\s+(\d{4}-\d{3}[\dXx])\s+(?=https?://)", notes
    ):
        if m.group(2).upper() not in seen:
            rows.append((m.group(2).upper(), m.group(1).strip()))
    return rows


def parse_iop_list(notes: str) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(r"([A-Za-z0-9&\-]+)\s+(\d{4}-\d{3}[\dXx])\s+\[([^\]]+)\]", notes):
        out.append((m.group(2).upper(), m.group(3).strip()))
    return out


def parse_ios_list(notes: str) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(r"([^|]+?)\s+(\d{4}-\d{3}[\dXx])(?:\s+\S{1,3})?\s*(?:\||$)", notes):
        name = m.group(1).strip()
        # strip a leading previous-entry residue: names run up to the issn
        name = re.sub(r"^.*?\d{4}-\d{3}[\dXx]\s*", "", name)
        out.append((m.group(2).upper(), name))
    return out


LIST_PARSERS = {
    "aip-publishing-aipp": parse_aip_list,
    "iop-publishing": parse_iop_list,
    "ios-press": parse_ios_list,
}


async def canonical_publisher(session, slug: str, name: str) -> Publisher:
    row = (
        await session.execute(select(Publisher).where(Publisher.openaccess_nl_slug == slug))
    ).scalar_one_or_none()
    if row is None:
        row = (
            await session.execute(select(Publisher).where(Publisher.name == name))
        ).scalar_one_or_none()
    code = CODE_BY_SLUG.get(slug)
    if row is None and code:
        row = (
            await session.execute(select(Publisher).where(Publisher.name == code))
        ).scalar_one_or_none()
    if row is None:
        row = Publisher(name=name)
        session.add(row)
        await session.flush()
    row.name = name
    row.openaccess_nl_slug = slug
    aliases = list(row.aliases or [])
    for candidate in (code, slug):
        if candidate and candidate not in aliases:
            aliases.append(candidate)
    row.aliases = aliases
    return row


async def resolve_issn_l(session, issn: str) -> str | None:
    row = await session.get(IssnMap, issn)
    if row:
        return row.issn_l
    hit = await session.execute(select(Journal.issn_l).where(Journal.issn_l == issn))
    return hit.scalar_one_or_none()


async def seed_journals(session, deal_id: int, entries: list[tuple[str, str]]) -> dict:
    added = unresolved = 0
    for issn, name in entries:
        issn_l = await resolve_issn_l(session, issn)
        if issn_l is None:
            unresolved += 1
        stmt = (
            pg_insert(DealJournal)
            .values(
                deal_id=deal_id,
                issn=issn,
                issn_l=issn_l,
                journal_name=name,
                source="manual",
                needs_curation=issn_l is None,
            )
            .on_conflict_do_nothing(index_elements=["deal_id", "issn"])
        )
        res = await session.execute(stmt)
        added += int(res.rowcount or 0)
    return {"added": added, "unresolved": unresolved, "total": len(entries)}


async def main() -> None:
    snapshot = json.loads(SNAPSHOT.read_text())
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    stats = []
    async with maker() as session:
        home = (
            await session.execute(select(Institution.id).where(Institution.is_home.is_(True)))
        ).scalar_one()
        for deal_json in snapshot["deals"]:
            slug = deal_json["publisher_slug"]
            pub = await canonical_publisher(session, slug, deal_json["publisher"])
            # Re-point every deal of a placeholder code row (SN, CAM, ...) at
            # the canonical publisher so no view shows code names.
            code = CODE_BY_SLUG.get(slug)
            if code and pub.name != code:
                stale = (
                    await session.execute(select(Publisher).where(Publisher.name == code))
                ).scalar_one_or_none()
                if stale is not None:
                    await session.execute(
                        Deal.__table__.update()
                        .where(Deal.publisher_id == stale.id)
                        .values(publisher_id=pub.id)
                    )
            if not deal_json["twente_participates"]:
                continue

            deal = None
            esac = ESAC_BY_SLUG.get(slug)
            if esac:
                deal = (
                    await session.execute(select(Deal).where(Deal.esac_id == esac))
                ).scalar_one_or_none()
            if deal is None:
                rows = (
                    (
                        await session.execute(
                            select(Deal).where(
                                Deal.publisher_id == pub.id,
                                Deal.status == "current",
                                Deal.openaccess_nl_url.is_not(None),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(rows) == 1:
                    deal = rows[0]
            if deal is None:
                start, end = parse_years(deal_json["duration"])
                if slug == "acm":
                    start, end = 2026, 2028  # Twente's local deal within 2021-2030
                deal = Deal(
                    esac_id=f"oanl-{slug}" if slug == "iop-publishing" else None,
                    publisher_id=pub.id,
                    status="current",
                    start_year=start,
                    end_year=end,
                    duration_text=deal_json["duration"],
                    openaccess_nl_url=deal_json["publisher_page_url"],
                )
                session.add(deal)
                await session.flush()

            # fields from the owner-reviewed snapshot
            contract = next(
                (link["url"] for link in deal_json["links"] if link["category"] == "contract"),
                None,
            )
            deal.publisher_id = pub.id
            deal.status = "current"
            if slug == "acm":
                deal.start_year, deal.end_year = 2026, 2028
                deal.duration_text = (
                    "2026-2028 (Twente local deal; the national ACM programme "
                    "spans 2021-2030 across participating institutions)"
                )
            else:
                deal.start_year, deal.end_year = parse_years(deal_json["duration"])
                deal.duration_text = deal_json["duration"]
            deal.summary = deal_json["summary"]
            deal.conditions_text = deal_json["license_and_conditions"] or None
            deal.workflow_text = deal_json["how_does_it_work"] or None
            deal.contract_url = contract or deal.contract_url
            deal.openaccess_nl_url = deal.openaccess_nl_url or deal_json["publisher_page_url"]
            deal.needs_curation = False
            deal.needs_curation_reason = None
            deal.last_reviewed = REVIEWED
            prov = list(deal.provenance or [])
            if PROVENANCE not in prov:
                prov.append(PROVENANCE)
            deal.provenance = prov

            await session.execute(
                pg_insert(DealInstitution)
                .values(deal_id=deal.id, institution_id=home)
                .on_conflict_do_nothing(index_elements=["deal_id", "institution_id"])
            )

            if esac:
                # Reconcile may have missed the national row (e.g. Emerald was
                # absent from JCT when it last ran); retire it as a duplicate.
                dupes = (
                    (
                        await session.execute(
                            select(Deal).where(
                                Deal.id != deal.id,
                                Deal.publisher_id == pub.id,
                                Deal.status == "current",
                                Deal.esac_id.is_(None),
                                Deal.openaccess_nl_url.is_not(None),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for dupe in dupes:
                    dupe.status = "archive"
                    dupe.needs_curation_reason = (
                        f"duplicate of {deal.esac_id} (canonical consortium row)"
                    )

            jstat: dict = {"mode": "existing"}
            if slug in LIST_PARSERS:
                entries = LIST_PARSERS[slug](deal_json["owner_notes"])
                jstat = {"mode": "owner_list", **await seed_journals(session, deal.id, entries)}
            elif slug in PUBLISHER_PATTERNS:
                conds = [Journal.publisher_name.ilike(p) for p in PUBLISHER_PATTERNS[slug]]
                rows = (
                    await session.execute(
                        select(Journal.issn_l, Journal.title).where(
                            Journal.type == "journal", *conds
                        )
                    )
                ).all()
                entries = [(issn_l, title or "") for issn_l, title in rows if issn_l]
                jstat = {
                    "mode": "publisher_all",
                    **await seed_journals(session, deal.id, entries),
                }
            stats.append(
                {
                    "slug": slug,
                    "deal_id": deal.id,
                    "esac": deal.esac_id,
                    "publisher": pub.name,
                    **jstat,
                }
            )
        await refresh_home_deal_flags(session)
        await session.commit()
    await engine.dispose()
    for s in stats:
        print(json.dumps(s, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
