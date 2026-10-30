"""Reconcile openaccess.nl deals with JCT agreements; curation report.

Matching: publisher (ESAC code alias -> openaccess.nl name) x duration
overlap. A matched pair converges into ONE deal row: the openaccess.nl
row becomes canonical (it carries the NL narrative the UI shows) and
absorbs the JCT row's esac_id, journal list, institutions, and source
links. Unmatched rows land in the curation report, never silently
dropped (limitation: jct-coverage).
"""

import logging
import re
from datetime import UTC, datetime

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import (
    Deal,
    DealInstitution,
    DealJournal,
    IssnMap,
    Journal,
    ManualOverride,
    Publisher,
)
from .common import get_active_institutions, get_home_institution
from .curation_report import render_curation_report as render_curation_report

logger = logging.getLogger(__name__)

#: ESAC ID code prefix -> canonical publisher name for auto-linking with
#: openaccess.nl publisher names. Anything absent here flows to the
#: curation report (manual esac_id overrides remain possible).
CODE_ALIASES = {
    "karger": "Karger",
    "kar": "Karger",
    "elsevier": "Elsevier",
    "els": "Elsevier",
    "oup": "Oxford University Press",
    "oxford": "Oxford University Press",
    "oxf": "Oxford University Press",
    "plos": "Public Library of Science (PLOS)",
    "thieme": "Thieme",
    "wiley": "Wiley",
    "springer": "Springer",
    "sn": "Springer",
    "sage": "SAGE",
    "acs": "American Chemical Society (ACS)",
    "acm": "ACM",
    "aip": "AIP Publishing (AIPP)",
    "iop": "IOP Publishing",
    "rsc": "Royal Society of Chemistry (RSC)",
    "tandf": "Taylor & Francis",
    "tf": "Taylor & Francis",
    "cambridge": "Cambridge University Press",
    "cup": "Cambridge University Press",
    "cam": "Cambridge University Press",
    "emerald": "Emerald Publishing group",
    "eme": "Emerald Publishing group",
    "lww": "Lippincott Williams & Wilkins (LWW)",
    "degruyter": "De Gruyter Brill",
    "dgbrill": "De Gruyter Brill",
    "dgb": "De Gruyter Brill",
    "brill": "De Gruyter Brill",
    "ios": "IOS Press",
    "aup": "Amsterdam University Press (AUP)",
    "aap": "Annual Reviews",
    "annualreviews": "Annual Reviews",
    "cob": "Company of Biologists",
    "companyofbiologists": "Company of Biologists",
}


def _code_of(esac_id: str | None) -> str | None:
    """'kar2026caul' -> 'kar'; digits start the year segment."""
    if not esac_id:
        return None
    code = ""
    for ch in esac_id:
        if ch.isdigit():
            break
        code += ch
    return code.lower() or None


def _canonical_name(code: str | None, publisher_name: str | None) -> str | None:
    if code and code in CODE_ALIASES:
        return CODE_ALIASES[code]
    return (publisher_name or "").strip() or None


def durations_overlap(a: Deal, b: Deal) -> bool:
    """Year-range overlap; open ranges (None ends) overlap generously.

    The year-0 substitution for a NULL start is the intended open-start
    semantics; 9999 fills an open end the same way."""
    a_end = a.end_year if a.end_year is not None else 9999
    b_end = b.end_year if b.end_year is not None else 9999
    a_start = a.start_year if a.start_year is not None else 0
    b_start = b.start_year if b.start_year is not None else 0
    return a_start <= b_end and b_start <= a_end


async def _jct_deals(session: AsyncSession) -> list[Deal]:
    """JCT deals not yet merged into a canonical row (no narrative URL)."""
    rows = await session.execute(
        select(Deal).where(
            Deal.esac_id.is_not(None),
            Deal.openaccess_nl_url.is_(None),
        )
    )
    return list(rows.scalars().all())


async def _home_institution_id(session: AsyncSession) -> int | None:
    """Home-institution row id (the env-seeded bootstrap institution)."""
    inst = await get_home_institution(session)
    return inst.id if inst else None


async def _publisher_names(session: AsyncSession) -> dict[int, str]:
    rows = await session.execute(select(Publisher.id, Publisher.name))
    return dict(rows.all())


async def _override_protected(session: AsyncSession, deal_ids: list[int]) -> set[int]:
    if not deal_ids:
        return set()
    rows = await session.execute(
        select(ManualOverride.row_key).where(
            ManualOverride.table_name == "deals",
            ManualOverride.row_key.in_([str(i) for i in deal_ids]),
            ManualOverride.field.in_(["needs_curation", "esac_id"]),
        )
    )
    return {int(k) for (k,) in rows.all()}


#: Journal-publisher name patterns for openaccess.nl deal publishers whose
#: name in the OpenAlex journals universe differs from the canonical name.
PUBLISHER_JOURNAL_PATTERNS = {"acm": ["association for computing machinery%"]}

#: Wording that marks a deal page WITH an institution enumeration. Pages
#: that list none of these describe a national (UKB-wide) deal instead, so
#: every Dutch university participates unless the text says otherwise.
ENUMERATION_HINTS = ("University of", "Universiteit", "TU Delft", "TU/e")


def _name_variants(home_name: str) -> tuple[str, ...]:
    """Casefolded spellings the deal pages use for the home institution
    ("University of Groningen" pages may write "Groningen University")."""
    variants = [home_name]
    m = re.match(r"university of (.+)", home_name)
    if m:
        variants.append(f"{m.group(1)} university")
    return tuple(variants)


def _participation(conditions_text: str | None, home_name: str) -> str | None:
    """'named', 'consortium', or None (deal not open to the home institute)."""
    text = conditions_text or ""
    if not text.strip():
        return None
    if any(v in text.casefold() for v in _name_variants(home_name)):
        return "named"
    enumerated = any(h in text for h in ENUMERATION_HINTS)
    if not enumerated and "universit" in text.casefold():
        return "consortium"
    return None


async def derive_nl_deal_coverage(session: AsyncSession) -> dict[str, int]:
    """Participation + journal coverage for openaccess.nl-only deals.

    These deals have no JCT sheet, but the deal pages state both facts:
    participation as an institution list in the conditions text
    ("Participating in the agreement are: ... <institution> ...") or, when
    no institutions are enumerated, as a national UKB-wide deal; and
    coverage as all journals of the publisher. Participation is derived
    once per hosted institution from the same conditions text; journals
    coverage rows are shared (institution_id NULL). Non-participating
    institutions simply get no deal_institutions row; publishers with no
    corpus match keep their needs_curation flag.
    """
    hosted = await get_active_institutions(session)
    stats = {"nl_deals": 0, "linked": 0, "covered": 0, "pattern_journals": 0}
    if not hosted:
        return stats
    deals = list(
        (
            await session.execute(
                select(Deal).where(
                    Deal.openaccess_nl_url.is_not(None),
                    Deal.esac_id.is_(None),
                    Deal.status == "current",
                )
            )
        ).scalars()
    )
    stats["nl_deals"] = len(deals)
    publisher_names = await _publisher_names(session)
    protected = await _override_protected(session, [d.id for d in deals])
    for deal in deals:
        participants = [
            inst
            for inst in hosted
            if _participation(deal.conditions_text, (inst.name or "").casefold()) is not None
        ]
        if not participants:
            continue
        linked = await session.scalar(
            select(DealInstitution.deal_id).where(
                DealInstitution.deal_id == deal.id,
                DealInstitution.institution_id.in_([i.id for i in participants]),
            )
        )
        has_journals = await session.scalar(
            select(func.count()).select_from(DealJournal).where(DealJournal.deal_id == deal.id)
        )
        if linked is None:
            await session.execute(
                pg_insert(DealInstitution)
                .values([{"deal_id": deal.id, "institution_id": inst.id} for inst in participants])
                .on_conflict_do_nothing(index_elements=["deal_id", "institution_id"])
            )
            stats["linked"] += len(participants)
        if linked is not None and has_journals:
            # Earlier reconcile already derived this deal; the flag pass
            # above re-flagged it, so clear it again (idempotent rerun).
            if deal.id not in protected and deal.needs_curation:
                deal.needs_curation = False
                deal.needs_curation_reason = None
            continue
        pname = (publisher_names.get(deal.publisher_id) or "").strip()
        # openaccess.nl names carry parenthetical sigla ("... (ACS)") that
        # OpenAlex publisher names lack; match on the bare name.
        base = re.sub(r"\s*\([^)]*\)\s*$", "", pname).strip()
        patterns = PUBLISHER_JOURNAL_PATTERNS.get(pname.casefold(), [f"{base}%"]) if base else []
        if has_journals or not patterns:
            continue
        journals = (
            await session.execute(
                select(Journal.issn_l, Journal.title).where(
                    or_(*[Journal.publisher_name.ilike(p) for p in patterns]),
                    Journal.issn_l.is_not(None),
                )
            )
        ).all()
        if not journals:
            continue
        await session.execute(
            pg_insert(DealJournal)
            .values(
                [
                    {
                        "deal_id": deal.id,
                        "issn": issn_l,
                        "issn_l": issn_l,
                        "journal_name": title,
                        "source": "publisher-pattern",
                    }
                    for issn_l, title in journals
                ]
            )
            .on_conflict_do_nothing(
                index_elements=["deal_id", "issn"],
                index_where=text("institution_id IS NULL"),
            )
        )
        deal.provenance = [
            *list(deal.provenance or []),
            {
                "source": "reconcile",
                "derived": "publisher-pattern",
                "participants": [i.code or i.name for i in participants],
                "patterns": patterns,
                "at": datetime.now(UTC).isoformat(),
            },
        ]
        if deal.id not in protected and deal.needs_curation:
            deal.needs_curation = False
            deal.needs_curation_reason = None
        stats["covered"] += 1
        stats["pattern_journals"] += len(journals)
    return stats


async def reconcile_deals(session: AsyncSession) -> dict[str, int]:
    """Match + merge; returns report counters."""
    publisher_names = await _publisher_names(session)
    jct_deals = await _jct_deals(session)
    matched = unmatched_jct = 0

    oanl_deals = list(
        (await session.execute(select(Deal).where(Deal.openaccess_nl_url.is_not(None)))).scalars()
    )
    already = {d.esac_id for d in oanl_deals if d.esac_id}
    consumed: set[int] = set()

    # Prefer agreements that carry the home institution; when UKB (Dutch
    # university libraries) or SURF joint deals don't enumerate members,
    # the Dutch-consortium suffix still outranks foreign consortia.
    home_id = await _home_institution_id(session)
    twente_deal_ids: set[int] = set()
    if home_id is not None:
        twente_deal_ids = set(
            (
                await session.execute(
                    select(DealInstitution.deal_id).where(DealInstitution.institution_id == home_id)
                )
            ).scalars()
        )
    dutch = {"ukb", "surf", "nl"}
    year_re = re.compile(r"^[A-Za-z]+(\d{4})([A-Za-z]*)$")

    def _tier(d: Deal) -> int:
        if d.id in twente_deal_ids:
            return 0
        m = year_re.match(d.esac_id or "")
        return 1 if m and m.group(2).lower() in dutch else 2

    # Tier 2 (foreign consortium, no Twente membership) never merges: it
    # would mislabel the canonical row and Twente-coverage queries would
    # ignore it anyway. Those rows stay in the database for provenance.
    jct_deals.sort(key=lambda d: (_tier(d), d.esac_id or ""))

    for jct in jct_deals:
        if _tier(jct) == 2:
            unmatched_jct += 1
            continue
        if jct.esac_id in already:
            # A previous reconcile merged this agreement; the JCT ingest
            # re-created its row. Drop the shadow copy again.
            await session.delete(jct)
            matched += 1
            continue
        name = _canonical_name(_code_of(jct.esac_id), publisher_names.get(jct.publisher_id))
        target = None
        for deal in oanl_deals:
            if target or deal.id in consumed or deal.esac_id:
                # esac set means this canonical already absorbed another
                # agreement; a second match would collide on journal rows.
                continue
            deal_name = publisher_names.get(deal.publisher_id, "")
            if not deal_name or not name:
                continue
            if deal_name.casefold().strip() == name.casefold().strip() and durations_overlap(
                deal, jct
            ):
                target = deal
        if target is None:
            unmatched_jct += 1
            continue
        consumed.add(target.id)
        await _merge(session, target, jct)
        matched += 1

    # openaccess.nl deals with no JCT counterpart: flag for curation,
    # except where staff set a manual override on this exact field
    # (reconcile runs after the normalizers, so an unguarded flag would
    # clobber curated values on every refresh).
    candidates = [d for d in oanl_deals if d.esac_id is None]
    protected = await _override_protected(session, [d.id for d in candidates])
    for deal in candidates:
        if deal.id in protected:
            continue
        deal.needs_curation = True
        deal.needs_curation_reason = "no matching JCT agreement (local or non-Plan-S deal?)"

    stats = {
        "matched": matched,
        "unmatched_jct": unmatched_jct,
        "unmatched_oanl": len([d for d in candidates if d.id not in protected]),
    }
    # Dutch-consortium merges whose member list omits institutions (UKB
    # joint deals do not always enumerate members): flag for review so
    # Twente participation is verified, never assumed.
    merged_canonicals = (
        await session.execute(
            select(Deal).where(
                Deal.esac_id.is_not(None),
                Deal.openaccess_nl_url.is_not(None),
                Deal.needs_curation.is_(False),
            )
        )
    ).scalars()
    # Refresh the home-linked set: a canonical that just absorbed a
    # home-linked JCT row is home-linked now, even though the set computed
    # before the merge loop does not contain it.
    if home_id is not None:
        twente_deal_ids = set(
            (
                await session.execute(
                    select(DealInstitution.deal_id).where(DealInstitution.institution_id == home_id)
                )
            ).scalars()
        )
    bare = [d.id for d in merged_canonicals if d.id not in twente_deal_ids]
    if bare:
        protected_bare = await _override_protected(session, bare)
        for did in set(bare) - protected_bare:
            deal = await session.get(Deal, did)
            deal.needs_curation = True
            deal.needs_curation_reason = (
                "consortium deal (ukb/surf) without enumerated members; "
                f"verify {get_settings().institution_name} participation"
            )
        stats["consortium_needs_review"] = len(set(bare) - protected_bare)
    # openaccess.nl-only deals: parse participation + derive publisher
    # coverage before the commit (may clear the no-JCT curation flags).
    stats.update(await derive_nl_deal_coverage(session))
    await session.commit()
    logger.info("reconcile: %s", stats)
    return stats


async def _merge(session: AsyncSession, canonical: Deal, jct: Deal) -> None:
    """Absorb the JCT row into the openaccess.nl canonical row."""
    esac_id = jct.esac_id
    data_url = jct.jct_data_url
    cao = jct.corresponding_authors_only
    reviewed = jct.last_reviewed
    status = jct.status
    # Drop the shadow row first: esac_id is UNIQUE, the canonical row
    # cannot take the value while this row holds it.
    dupes_j = select(DealJournal.issn).where(DealJournal.deal_id == canonical.id)
    await session.execute(
        sa_delete(DealJournal).where(DealJournal.deal_id == jct.id, DealJournal.issn.in_(dupes_j))
    )
    await session.execute(
        update(DealJournal).where(DealJournal.deal_id == jct.id).values(deal_id=canonical.id)
    )
    # The derive pass may have linked the canonical already; drop the JCT
    # row's duplicates before re-pointing the rest.
    dupes = select(DealInstitution.institution_id).where(DealInstitution.deal_id == canonical.id)
    await session.execute(
        sa_delete(DealInstitution).where(
            DealInstitution.deal_id == jct.id,
            DealInstitution.institution_id.in_(dupes),
        )
    )
    await session.execute(
        update(DealInstitution)
        .where(DealInstitution.deal_id == jct.id)
        .values(deal_id=canonical.id)
    )
    # A canonical override on the same field would collide with the re-keyed
    # row under uq_manual_overrides; the canonical row wins, the shadow's
    # duplicate field drops.
    dup_fields = select(ManualOverride.field).where(
        ManualOverride.table_name == "deals", ManualOverride.row_key == str(canonical.id)
    )
    await session.execute(
        sa_delete(ManualOverride).where(
            ManualOverride.table_name == "deals",
            ManualOverride.row_key == str(jct.id),
            ManualOverride.field.in_(dup_fields),
        )
    )
    await session.execute(
        update(ManualOverride)
        .where(ManualOverride.table_name == "deals", ManualOverride.row_key == str(jct.id))
        .values(row_key=str(canonical.id))
    )
    await session.delete(jct)
    await session.flush()

    canonical.esac_id = esac_id
    canonical.jct_data_url = data_url
    canonical.corresponding_authors_only = cao
    canonical.last_reviewed = reviewed
    if canonical.status != status:
        canonical.needs_curation = True
        canonical.needs_curation_reason = (
            f"status conflict: openaccess.nl={canonical.status}, JCT={status}"
        )
    canonical.provenance = [
        *list(canonical.provenance or []),
        {"source": "jct", "esac_id": esac_id, "merged_at": datetime.now(UTC).isoformat()},
    ]
    await session.flush()


async def enforce_unique_agreement_data(session: AsyncSession) -> list[dict[str, str]]:
    """Detect agreements whose JCT journal lists are near-identical and fix.

    The JCT public dump sometimes links two agreements to the same Google
    Sheet (live case 2026-10: eme2025ukb served the Elsevier UKB sheet, so
    Emerald's coverage silently doubled as Elsevier). For each suspect pair,
    the agreement whose publisher matches the shared list's dominant
    publisher keeps its rows; the other loses its journal rows (verbatim
    evidence stays in source_records + landing) and keeps a needs_curation
    flag until the JCT curators publish the correct sheet. Institution
    links survive: consortium participation is real even when the sheet
    is wrong.

    Returns the actions taken, for the curation report.
    """
    actions: list[dict[str, str]] = []
    jct_deals = await _jct_deals(session)
    if not jct_deals:
        return actions
    lists: dict[int, frozenset[str]] = {}
    for d in jct_deals:
        rows = await session.execute(select(DealJournal.issn).where(DealJournal.deal_id == d.id))
        issns = frozenset(r[0] for r in rows.all() if r[0])
        if len(issns) >= 50:
            lists[d.id] = issns
    items = sorted(lists.items())
    by_id = {d.id: d for d in jct_deals}
    # Collect cross-publisher suspect pairs, then resolve each deal once
    # against its highest-overlap partner (a wrong sheet can duplicate
    # several legitimate agreements of the same publisher).
    best: dict[int, tuple[float, int]] = {}
    for i, (ida, sa) in enumerate(items):
        for idb, sb in items[i + 1 :]:
            overlap = len(sa & sb) / max(1, min(len(sa), len(sb)))
            if overlap < 0.9:
                continue
            # Same-publisher agreements legitimately share most of their
            # journal corpus across consortia; only cross-publisher
            # duplication signals a mis-linked sheet.
            if _code_of(by_id[ida].esac_id) == _code_of(by_id[idb].esac_id):
                continue
            for low, high, o in ((ida, idb, overlap), (idb, ida, overlap)):
                if low not in best or o > best[low][0]:
                    best[low] = (o, high)
    for loser_id, (overlap, keeper_id) in sorted(best.items()):
        if loser_id not in by_id:
            continue
        keeper, loser = await _resolve_pair(
            session, by_id[keeper_id], by_id[loser_id], lists[keeper_id] | lists[loser_id]
        )
        if loser is None:
            continue
        await session.execute(sa_delete(DealJournal).where(DealJournal.deal_id == loser.id))
        reason = (
            f"JCT data CSV is a duplicate of {keeper.esac_id} "
            f"({overlap:.0%} identical ISSNs) - upstream index error; "
            "awaiting the correct sheet from the JCT curators"
        )
        loser.needs_curation = True
        loser.needs_curation_reason = reason
        actions.append(
            {
                "keeper": keeper.esac_id or str(keeper.id),
                "loser": loser.esac_id or str(loser.id),
                "overlap": f"{overlap:.0%}",
                "action": "purged derived rows + flagged needs_curation",
            }
        )
    await session.commit()
    return actions


async def _resolve_pair(
    session: AsyncSession, a: Deal, b: Deal, combined: frozenset[str]
) -> tuple[Deal, Deal | None]:
    """Pick keeper/loser for a duplicate pair by dominant publisher match.

    Returns (a, b) ordered so the keeper comes first; (a, None) when the
    dominant publisher cannot be determined (keep both, report only).
    """
    # Dominant publisher of the shared journal list, by journal count.
    rows = await session.execute(
        select(Journal.publisher_name, func.count())
        .join(IssnMap, IssnMap.issn_l == Journal.issn_l)
        .where(IssnMap.issn.in_(combined))
        .group_by(Journal.publisher_name)
        .order_by(func.count().desc())
        .limit(1)
    )
    row = rows.first()
    dominant = (row[0] or "").casefold() if row else ""
    if not dominant:
        return a, None
    names = {
        a.id: (await _publisher_names(session)).get(a.publisher_id) or "",
        b.id: (await _publisher_names(session)).get(b.publisher_id) or "",
    }

    def _matches(d: Deal) -> bool:
        name = names[d.id].casefold()
        alias = (_canonical_name(_code_of(d.esac_id), name) or "").casefold()
        return dominant in name or dominant in alias or alias in dominant

    a_match, b_match = _matches(a), _matches(b)
    if a_match and not b_match:
        return a, b
    if b_match and not a_match:
        return b, a
    return a, None
