"""Which publisher a deal's journal list belongs to.

openaccess.nl is the primary source for the Dutch deals. The JCT dump is
secondary: it adds one Google Sheet per agreement with the journal and
participant lists. The JCT index can link an agreement to the sheet of
another publisher (live case 2026-11: `eme2025ukb`, the Emerald deal,
pointed at the Elsevier UKB sheet, so 2,572 Elsevier titles counted as
Emerald coverage).

This module judges a journal list by the publisher its journals resolve
to. The JCT ingest and the reconcile refuse a list that is not the deal's
own and flag the deal, instead of guessing.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Deal, DealJournal, IssnMap, Journal, ManualOverride, Publisher

#: ESAC ID code prefix -> openaccess.nl publisher name. Codes that share a
#: value ("els", "elsevier") are one publisher family. A code without an
#: entry is its own family, keyed by the name on its publisher row.
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
    "degruy": "De Gruyter Brill",
    "dgbrill": "De Gruyter Brill",
    "dgb": "De Gruyter Brill",
    "brill": "De Gruyter Brill",
    "ios": "IOS Press",
    "aup": "Amsterdam University Press (AUP)",
    "aap": "Annual Reviews",
    "annualreviews": "Annual Reviews",
    "cob": "The Company of Biologists",
    "compbio": "The Company of Biologists",
    "companyofbiologists": "The Company of Biologists",
}

#: A list is judged only when at least this many of its journals resolve to
#: a journal universe row; a smaller sample says nothing about the publisher.
MIN_RESOLVED_JOURNALS = 50
#: "Most of the journals belong to publisher X": the share X must hold.
DOMINANT_SHARE = 0.5

#: Key of a JCT sheet entry in Deal.provenance whose sheet was withheld.
SHEET_REJECTED_KEY = "sheet_rejected"
#: The two curation reasons this module writes. Both start with their
#: prefix, so a later run can tell its own flags from a page-quality or
#: admin reason.
REJECTED_PREFIX = "JCT journal list rejected"
MISMATCH_PREFIX = "Journal list is mostly another publisher's"

#: Words that do not tell publishers apart, and the parenthetical sigla
#: openaccess.nl names carry ("... (ACS)").
_FILLER_RE = re.compile(
    r"\(.*?\)|&|\b(?:publishing|publisher|publishers|group|limited|ltd|inc|gmbh|bv|nv"
    r"|plc|the|of|for|and|co)\b|[^a-z0-9]+"
)


def code_of(esac_id: str | None) -> str | None:
    """'kar2026caul' -> 'kar'; digits start the year segment."""
    if not esac_id:
        return None
    code = ""
    for ch in esac_id:
        if ch.isdigit():
            break
        code += ch
    return code.lower() or None


def canonical_name(code: str | None, publisher_name: str | None) -> str | None:
    """Publisher family name of a deal: the openaccess.nl name its ESAC code
    maps to, else the name on its publisher row (openaccess.nl-only deals
    and codes without an alias)."""
    if code and code in CODE_ALIASES:
        return CODE_ALIASES[code]
    return (publisher_name or "").strip() or None


def family_of(esac_id: str | None, publisher_name: str | None) -> str:
    """Casefolded family key; '' when neither is known."""
    return (canonical_name(code_of(esac_id), publisher_name) or "").casefold()


def name_matches(a: str, b: str) -> bool:
    """True for two spellings of one publisher: once filler words are gone,
    every word of one name is in the other ("Karger" / "Karger Publishers",
    "Elsevier" / "Elsevier BV", "De Gruyter Brill" / "Brill")."""
    words_a = set(_FILLER_RE.sub(" ", a.casefold()).split())
    words_b = set(_FILLER_RE.sub(" ", b.casefold()).split())
    return bool(words_a and words_b and (words_a <= words_b or words_b <= words_a))


def rejected_sheet(provenance: list[Any] | None) -> str | None:
    """Reason recorded on a JCT sheet entry that was withheld, or None.

    The JCT ingest rebuilds its sheet entry on every run, so a marker on
    the stored entry is always current."""
    for entry in provenance or []:
        if isinstance(entry, dict) and entry.get("source") == "jct" and SHEET_REJECTED_KEY in entry:
            reason = entry[SHEET_REJECTED_KEY]
            return str(reason) if reason is not None else None
    return None


def is_list_reason(reason: str | None) -> bool:
    """True for either reason this module writes."""
    return reason is not None and reason.startswith((REJECTED_PREFIX, MISMATCH_PREFIX))


def dismissal_applies(dismissed: str | None, reason: str | None) -> bool:
    """True when `dismissed`, the text the admin dismissed, is the class of
    `reason`. Both carry counts that move with the journal universe, so the
    text before the colon decides."""
    return (
        is_list_reason(dismissed)
        and reason is not None
        and dismissed is not None
        and dismissed.split(":", 1)[0] == reason.split(":", 1)[0]
    )


def list_flag_dismissed(deal: Deal, reason: str | None) -> bool:
    """True when the admin dismissed a flag of the class of `reason` on this
    deal: the sheet stays withheld, the flag is not raised again."""
    return dismissal_applies(deal.curation_resolved_reason, reason)


async def flag_owned(session: AsyncSession, deal_ids: Sequence[int]) -> set[int]:
    """Deals whose curation flag an admin owns through a ManualOverride row."""
    if not deal_ids:
        return set()
    rows = await session.execute(
        select(ManualOverride.row_key).where(
            ManualOverride.table_name == "deals",
            ManualOverride.row_key.in_([str(i) for i in deal_ids]),
            ManualOverride.field == "needs_curation",
        )
    )
    return {int(k) for (k,) in rows.all()}


def flag(deal: Deal, reason: str) -> None:
    """Set a live curation flag. A live flag never coexists with a dismissal."""
    deal.needs_curation = True
    deal.needs_curation_reason = reason
    deal.curation_resolved_reason = None


@dataclass(frozen=True)
class ListPublisher:
    """The publisher that dominates a journal list."""

    name: str
    count: int  # journals published by `name`
    resolved: int  # journals that resolve to a journal universe row

    @property
    def share(self) -> float:
        return self.count / self.resolved


def dominant_publisher(counts: Mapping[str, int]) -> ListPublisher | None:
    """None when too few journals resolve or no publisher holds the majority."""
    name, count = "", 0
    for candidate, n in counts.items():
        if candidate and n > count:  # "" marks a journal without a publisher name
            name, count = candidate, n
    resolved = sum(counts.values())
    if count < MIN_RESOLVED_JOURNALS or count < DOMINANT_SHARE * resolved:
        return None
    return ListPublisher(name, count, resolved)


async def publisher_counts(
    session: AsyncSession, deal_ids: Sequence[int] | None = None, *, jct_only: bool = False
) -> dict[int, Counter[str]]:
    """Per deal: {journals.publisher_name: rows} over the deal's shared,
    non-excluded journal rows that resolve to a journal universe row."""
    query = (
        select(DealJournal.deal_id, Journal.publisher_name, func.count())
        .select_from(DealJournal)
        .join(IssnMap, IssnMap.issn == DealJournal.issn)
        .join(Journal, Journal.issn_l == IssnMap.issn_l)
        .where(DealJournal.institution_id.is_(None), DealJournal.excluded.is_not(True))
        .group_by(DealJournal.deal_id, Journal.publisher_name)
    )
    if deal_ids is not None:
        if not deal_ids:
            return {}
        query = query.where(DealJournal.deal_id.in_(deal_ids))
    if jct_only:
        query = query.where(DealJournal.source == "jct")
    counts: dict[int, Counter[str]] = defaultdict(Counter)
    for deal_id, publisher_name, n in (await session.execute(query)).all():
        counts[deal_id][publisher_name or ""] += n
    return dict(counts)


async def issn_publisher_counts(session: AsyncSession, issns: Sequence[str]) -> Counter[str]:
    """{journals.publisher_name: journals} for the ISSNs that resolve."""
    counts: Counter[str] = Counter()
    if not issns:
        return counts
    rows = await session.execute(
        select(Journal.publisher_name, func.count())
        .select_from(Journal)
        .join(IssnMap, IssnMap.issn_l == Journal.issn_l)
        .where(IssnMap.issn.in_(issns))
        .group_by(Journal.publisher_name)
    )
    for publisher_name, n in rows.all():
        counts[publisher_name or ""] += n
    return counts


@dataclass(frozen=True)
class SheetPublishers:
    """What the stored JCT sheets say about each publisher family."""

    #: deal id -> dominant publisher of its stored JCT sheet
    sheets: dict[int, str]
    #: deal id -> family key (see family_of)
    families: dict[int, str]
    #: family key -> name as displayed
    names: dict[str, str]

    def vouches(self, family: str, publisher: str, exclude: int | None) -> bool:
        """Another deal of `family` has a stored sheet that `publisher`
        dominates. The vote of deal `exclude` does not count: a sheet never
        vouches for its own family."""
        return any(
            dominant == publisher and deal_id != exclude and self.families.get(deal_id) == family
            for deal_id, dominant in self.sheets.items()
        )

    def other_owner(self, family: str, publisher: str) -> str | None:
        """Name of the family, other than `family`, whose sheets `publisher`
        dominates most often; None when no other family's sheet has it."""
        votes: Counter[str] = Counter(
            self.families[deal_id]
            for deal_id, dominant in self.sheets.items()
            if dominant == publisher and self.families.get(deal_id) not in (None, family)
        )
        if not votes:
            return None
        owner = votes.most_common(1)[0][0]
        return self.names.get(owner, owner)


async def load_sheet_publishers(session: AsyncSession) -> SheetPublishers:
    """Snapshot of the stored JCT sheets and of every deal's family."""
    rows = (
        await session.execute(
            select(Deal.id, Deal.esac_id, Publisher.name).outerjoin(
                Publisher, Publisher.id == Deal.publisher_id
            )
        )
    ).all()
    families: dict[int, str] = {}
    names: dict[str, str] = {}
    for deal_id, esac_id, publisher_name in rows:
        display = canonical_name(code_of(esac_id), publisher_name)
        if display:
            families[deal_id] = display.casefold()
            names[display.casefold()] = display
    sheets: dict[int, str] = {}
    for deal_id, counts in (await publisher_counts(session, jct_only=True)).items():
        dominant = dominant_publisher(counts)
        if dominant is not None:
            sheets[deal_id] = dominant.name
    return SheetPublishers(sheets, families, names)


@dataclass(frozen=True)
class Verdict:
    """Judgement of one journal list.

    `publisher` is None when the list cannot be judged (too few journals
    resolve, or no majority). `own`: the dominant publisher is the deal's
    own family by name, or the publisher of another agreement of that
    family. `foreign`: display name of the family the journals belong to,
    when that is not the deal's own family; None when no other family's
    sheet says so."""

    publisher: ListPublisher | None
    own: bool
    foreign: str | None


def judge(
    counts: Mapping[str, int], *, family: str, exclude: int | None, sheets: SheetPublishers
) -> Verdict:
    """Judge a journal list against the deal's family and the stored sheets.

    `family` is the deal's own family key and `exclude` its deal id. A
    dominant publisher that another family's sheets own is foreign before
    any sibling sheet can vouch for it: two agreements of one family can
    be linked to the same wrong sheet, and each would vouch for the other."""
    dominant = dominant_publisher(counts)
    if dominant is None or not family:
        return Verdict(None, False, None)
    if name_matches(family, dominant.name):
        return Verdict(dominant, True, None)
    other = sheets.other_owner(family, dominant.name)
    if other is not None:
        return Verdict(dominant, False, other)
    # An imprint name such as Routledge matches no family name, but it
    # dominates the other Taylor & Francis agreements.
    return Verdict(dominant, sheets.vouches(family, dominant.name, exclude), None)


def withheld(verdict: Verdict, prior_reason: str | None) -> str | None:
    """Reason to keep a JCT sheet out, or None to attach it.

    A sheet rejected earlier stays out until it proves to be the deal's
    own; a fresh sheet is attached unless it belongs to another family."""
    if verdict.foreign is not None:
        assert verdict.publisher is not None
        publisher = verdict.publisher
        return (
            f"{REJECTED_PREFIX}: {publisher.count} of {publisher.resolved} journals that resolve "
            f"({publisher.share:.0%}) are published by {publisher.name}, the publisher of the "
            f"{verdict.foreign} agreements, not of this deal. The JCT index links this agreement "
            "to a sheet that is not its own (upstream index error), so its journals were not "
            "attached; the sheet URL is kept in provenance."
        )
    if not verdict.own and prior_reason is not None:
        return prior_reason
    return None


def mismatch_reason(verdict: Verdict) -> str:
    """Reason for a stored list that is another publisher's (rows stay)."""
    assert verdict.publisher is not None and verdict.foreign is not None
    publisher = verdict.publisher
    return (
        f"{MISMATCH_PREFIX}: {publisher.count} of {publisher.resolved} journals that resolve "
        f"({publisher.share:.0%}) are published by {publisher.name}, the publisher of the "
        f"{verdict.foreign} agreements, not of this deal. Check where this deal's journal list "
        "came from (JCT sheet, contract list or admin import)."
    )
