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
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Deal, DealInstitution, DealJournal, Institution, ManualOverride, Publisher

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
    "emerald": "Emerald",
    "eme": "Emerald",
    "lww": "Lippincott, Williams & Wilkins (LWW)",
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
    """Year-range overlap; open ranges (None ends) overlap generously."""
    a_end = a.end_year or 9999
    b_end = b.end_year or 9999
    a_start = a.start_year or 0
    b_start = b.start_year or 0
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
    """Home-institution row id (single is_home row; config-not-constants rule)."""
    return await session.scalar(select(Institution.id).where(Institution.is_home.is_(True)))


async def _publisher_names(session: AsyncSession) -> dict[int, str]:
    rows = await session.execute(select(Publisher.id, Publisher.name))
    return {pid: name for pid, name in rows.all()}


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
        name = _canonical_name(_code_of(jct.esac_id), publisher_names.get(jct.publisher_id or 0))
        target = None
        for deal in oanl_deals:
            if target or deal.id in consumed or deal.esac_id:
                # esac set means this canonical already absorbed another
                # agreement; a second match would collide on journal rows.
                continue
            deal_name = publisher_names.get(deal.publisher_id or 0, "")
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
    bare = [
        d.id
        for d in merged_canonicals
        if d.id not in twente_deal_ids
        and not (
            await session.execute(
                select(DealInstitution.deal_id)
                .join(Institution, Institution.id == DealInstitution.institution_id)
                .where(DealInstitution.deal_id == d.id, Institution.is_home.is_(True))
            )
        ).first()
    ]
    if bare:
        protected_bare = await _override_protected(session, bare)
        for did in set(bare) - protected_bare:
            deal = await session.get(Deal, did)
            deal.needs_curation = True
            deal.needs_curation_reason = (
                "consortium deal (ukb/surf) without enumerated members; "
                "verify Twente participation"
            )
        stats["consortium_needs_review"] = len(set(bare) - protected_bare)
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
    await session.execute(
        update(DealJournal).where(DealJournal.deal_id == jct.id).values(deal_id=canonical.id)
    )
    await session.execute(
        update(DealInstitution)
        .where(DealInstitution.deal_id == jct.id)
        .values(deal_id=canonical.id)
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
    canonical.provenance = list(canonical.provenance or []) + [
        {"source": "jct", "esac_id": esac_id, "merged_at": datetime.now(UTC).isoformat()}
    ]
    await session.flush()


def _esc(text: str | None) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def render_curation_report(session: AsyncSession) -> Path:
    """Read-only HTML report for library staff."""
    publisher_names = await _publisher_names(session)
    deals = list((await session.execute(select(Deal))).scalars())
    oanl = [d for d in deals if d.openaccess_nl_url]
    flagged = [d for d in deals if d.needs_curation]
    unresolvable = list(
        (
            await session.execute(select(DealJournal).where(DealJournal.needs_curation.is_(True)))
        ).scalars()
    )

    sections: list[str] = []

    def deal_row(d: Deal) -> str:
        return (
            f"<li>#{d.id} <strong>{_esc(publisher_names.get(d.publisher_id or 0, '?'))}</strong> "
            f"[{_esc(d.status)}] {_esc(d.duration_text)} — "
            f"{_esc(d.needs_curation_reason or '')} "
            f"<a href='{_esc(d.openaccess_nl_url)}'>openaccess.nl</a> "
            f"{f'<a href="{_esc(d.jct_data_url)}">JCT</a>' if d.jct_data_url else ''}</li>"
        )

    if flagged:
        sections.append(
            "<h2>Deals flagged for curation</h2><ul>"
            + "".join(deal_row(d) for d in flagged)
            + "</ul>"
        )
    no_list = [d for d in oanl if d.esac_id is None]
    if no_list:
        sections.append(
            "<h2>openaccess.nl deals without a JCT agreement (no journal list)</h2><ul>"
            + "".join(deal_row(d) for d in no_list)
            + "</ul>"
        )
    jct_only = [d for d in deals if d.esac_id and not d.openaccess_nl_url]
    home = await _home_institution_id(session)
    if home is not None:
        twente_deal_ids = set(
            (
                await session.execute(
                    select(DealInstitution.deal_id).where(DealInstitution.institution_id == home)
                )
            ).scalars()
        )
    else:
        twente_deal_ids = set()
    relevant = [d for d in jct_only if d.id in twente_deal_ids]
    skipped = len(jct_only) - len(relevant)
    if relevant:
        sections.append(
            "<h2>Twente-relevant JCT agreements with no openaccess.nl deal "
            "(publisher/duration unmatched)</h2><ul>"
            + "".join(
                f"<li>#{d.id} {_esc(publisher_names.get(d.publisher_id or 0, '?'))} "
                f"{_esc(d.esac_id)} [{_esc(d.status)}] {_esc(d.duration_text)}</li>"
                for d in relevant
            )
            + "</ul>"
        )
    if skipped:
        sections.append(
            f"<p>{skipped} JCT agreements are not Twente-affiliated and are out of "
            "scope for this browser; they stay in the database for provenance.</p>"
        )
    # Upstream sanity: JCT agreement CSVs sometimes carry another
    # publisher's journal list (eme2025ukb ships Elsevier's list verbatim).
    # Flag Twente-relevant pairs with near-identical ISSN sets.
    twente_deals = [d for d in deals if d.id in twente_deal_ids]
    lists = {}
    for d in twente_deals:
        rows = await session.execute(
            select(DealJournal.issn).where(DealJournal.deal_id == d.id)
        )
        sets = frozenset(r[0] for r in rows.all())
        if len(sets) >= 50:
            lists[d] = sets
    seen: set[tuple[int, int]] = set()
    overlaps: list[str] = []
    items = sorted(lists.items(), key=lambda kv: kv[0].esac_id or "")
    for i, (da, sa) in enumerate(items):
        for db_, sb in items[i + 1 :]:
            pair = (min(da.id, db_.id), max(da.id, db_.id))
            if pair in seen:
                continue
            seen.add(pair)
            j = len(sa & sb) / max(1, min(len(sa), len(sb)))
            if j >= 0.9:
                overlaps.append(
                    f"<li>{_esc(da.esac_id or '')} vs {_esc(db_.esac_id or '')}: "
                    f"{j:.0%} identical ISSN sets ({len(sa)} vs {len(sb)}) — likely "
                    "an upstream data error; verify with the JCT curators</li>"
                )
    if overlaps:
        sections.append(
            "<h2>Suspicious journal-list overlap between Twente-relevant agreements</h2><ul>"
            + "".join(overlaps)
            + "</ul>"
        )
    if unresolvable:
        sections.append(
            "<h2>Deal journals with unresolved ISSN-L</h2><ul>"
            + "".join(
                f"<li>deal #{r.deal_id}: {_esc(r.journal_name)} ISSN {_esc(r.issn)}</li>"
                for r in unresolvable[:200]
            )
            + (f"<li>… and {len(unresolvable) - 200} more</li>" if len(unresolvable) > 200 else "")
            + "</ul>"
        )
    counts = {
        "deals_total": len(deals),
        "deals_with_esac": sum(1 for d in deals if d.esac_id),
        "needs_curation": len(flagged),
        "unresolved_journal_issns": len(unresolvable),
    }
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Journal Browser — curation report</title>"
        "<style>body{font-family:system-ui;max-width:60rem;margin:2rem auto;padding:0 1rem}"
        "li{margin:.2rem 0}h2{border-bottom:1px solid #ddd}</style></head><body>"
        f"<h1>Curation report</h1><p>Generated {datetime.now(UTC).isoformat()}</p>"
        f"<pre>{_esc(str(counts))}</pre>" + "".join(sections) + "</body></html>"
    )
    path = Path(get_settings().curation_report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)
    logger.info("curation report written to %s", path)
    return path
