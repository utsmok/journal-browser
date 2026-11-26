"""Guided Journal Finder recommendation engine.

Retrieves topical candidates via local bge-small-en-v1.5 embeddings + pgvector
HNSW strict_order scan, enriches them with EUR-standardized APC evidence,
institutional deals, Jisc green-OA routes, and funder-policy fit, evaluates
budget/funder constraints with graceful relaxation, and ranks deterministically
with explicit plain-language argumentation.

Privacy contract: the user's manuscript title and abstract are NEVER logged or
stored anywhere.
"""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Deal,
    DealInstitution,
    DealJournal,
    Institution,
    JiscFunder,
    Journal,
    Publisher,
    ScimagojrMetric,
)
from ..schemas import (
    FunderFitOut,
    RecommendApcDisplay,
    RecommendDealSummary,
    RecommendedJournal,
    RecommendReason,
    RecommendRequest,
    RecommendResponse,
)
from ..vocab import ApcSource, OaType
from . import embeddings
from .deal_coverage import deal_institution_join, dj_scope
from .funder_fit import FunderFit, JournalFacts, compute_funder_fit, policy_structured
from .search.query import attach_apc_display, base_query
from .search.recommendable import active_since

#: Maximum character budget sent into bge-small-en-v1.5 (512-token window).
MAX_QUERY_CHARS = 1800
#: Number of nearest semantic candidates pulled before policy/budget filtering.
CANDIDATE_POOL_LIMIT = 240
#: Generous cosine-distance recall cap; anything beyond 0.45 is topically weak.
RECOMMEND_MAX_DISTANCE = 0.45
#: Minimum strict matches desired before appending relaxed fallback alternatives.
MIN_STRICT_BEFORE_RELAX = 3
#: Maximum relaxed fallback alternatives returned alongside sparse strict hits.
MAX_ALTERNATIVES = 5

#: Heuristic to spot discount-only deals (no 100% / full APC waiver).
_DISCOUNT_RE = re.compile(r"\b\d{1,2}\s*%\s*discount\b|\bdiscount(?:ed)?\b", re.IGNORECASE)
_FULL_WAIVER_RE = re.compile(
    r"\b100\s*%|\bfree\b|\bno\s+(?:extra\s+)?cost\b|\bno\s+apc\b|\bfull\s+waiver\b|\bwaived\b",
    re.IGNORECASE,
)


def build_query_text(title: str, abstract: str, max_chars: int = MAX_QUERY_CHARS) -> str:
    """Combine manuscript title and abstract within bge-small's token budget."""
    parts = [p for p in (title.strip(), abstract.strip()) if p]
    combined = "\n\n".join(parts)
    if len(combined) <= max_chars:
        return combined
    trimmed = combined[:max_chars]
    cut = trimmed.rsplit(" ", 1)[0]
    return cut if len(cut) >= max_chars // 2 else trimmed


def _is_discount_only_deal(summary: str | None, conditions_text: str | None) -> bool:
    blob = " ".join(s for s in (summary, conditions_text) if s).strip()
    if not blob:
        return False
    return bool(_DISCOUNT_RE.search(blob)) and not bool(_FULL_WAIVER_RE.search(blob))


def _deal_duration(deal: Deal) -> str | None:
    if deal.duration_text:
        return deal.duration_text.strip()
    if deal.start_year and deal.end_year:
        return f"{deal.start_year} to {deal.end_year}"
    if deal.start_year:
        return f"From {deal.start_year}"
    return None


def _fmt_eur(amount: float) -> str:
    return f"€{round(amount):,}"


@dataclass
class _EvaluatedCandidate:
    item: dict[str, Any]
    oa_type: OaType
    similarity: float
    deal_summary: RecommendDealSummary | None
    apc_display: RecommendApcDisplay | None
    estimated_cost_eur: float | None
    estimated_cost_label: str
    funder_fit: FunderFit | None
    h_index: int | None
    topics: list[str]
    strict_pass: bool
    match_score: float
    relax_priority: int
    relaxed_note: str | None


async def _fetch_active_deals(
    session: AsyncSession,
    institution_id: int,
    issns: list[str],
    cap_reached_map: dict[str, bool],
) -> dict[str, RecommendDealSummary]:
    """Batch-load active institutional deal metadata for deal-covered candidates."""
    if not issns:
        return {}
    rows = (
        await session.execute(
            select(DealJournal.issn_l, Deal, Publisher.name)
            .select_from(Deal)
            .join(DealInstitution, deal_institution_join(institution_id))
            .join(
                DealJournal,
                (DealJournal.deal_id == Deal.id)
                & dj_scope(institution_id)
                & DealJournal.excluded.is_not(True)
                & DealJournal.issn_l.in_(issns),
            )
            .outerjoin(Publisher, Publisher.id == Deal.publisher_id)
            .where(Deal.status == "current")
            .order_by(DealJournal.issn_l.asc(), Deal.id.asc())
        )
    ).all()

    by_issn: dict[str, list[tuple[Deal, str | None]]] = {}
    for issn_l, deal, pub_name in rows:
        if issn_l:
            by_issn.setdefault(issn_l, []).append((deal, pub_name))

    out: dict[str, RecommendDealSummary] = {}
    for issn_l, entries in by_issn.items():
        # Prefer a non-discount, uncapped deal when multiple deals cover one journal.
        def _deal_rank(pair: tuple[Deal, str | None]) -> tuple[int, int, int]:
            d, _ = pair
            disc = 1 if _is_discount_only_deal(d.summary, d.conditions_text) else 0
            capped = 1 if bool(d.cap_text or d.cap_numbers) else 0
            return (disc, capped, d.id)

        deal, pub_name = min(entries, key=_deal_rank)
        cap_reached = cap_reached_map.get(issn_l, False)
        is_capped = bool(deal.cap_text or deal.cap_numbers or cap_reached)
        out[issn_l] = RecommendDealSummary(
            publisher_name=pub_name,
            duration_text=_deal_duration(deal),
            is_capped=is_capped,
            cap_reached=cap_reached,
            cap_text=deal.cap_text.strip() if deal.cap_text else None,
            is_discount_only=_is_discount_only_deal(deal.summary, deal.conditions_text),
            summary=deal.summary.strip() if deal.summary else None,
            openaccess_nl_url=deal.openaccess_nl_url,
        )
    return out


async def _fetch_scimago_h_index(session: AsyncSession, issns: list[str]) -> dict[str, int]:
    """Latest ScimagoJR h-index per ISSN-L, used as fallback when OpenAlex lacks one."""
    if not issns:
        return {}
    ranked = (
        select(
            ScimagojrMetric.issn_l,
            ScimagojrMetric.h_index,
            func.row_number()
            .over(partition_by=ScimagojrMetric.issn_l, order_by=desc(ScimagojrMetric.year))
            .label("rn"),
        )
        .where(ScimagojrMetric.issn_l.in_(issns), ScimagojrMetric.h_index.is_not(None))
        .subquery()
    )
    rows = (
        await session.execute(select(ranked.c.issn_l, ranked.c.h_index).where(ranked.c.rn == 1))
    ).all()
    return {r.issn_l: int(r.h_index) for r in rows if r.h_index is not None}


def _extract_apc_and_cost(
    item: dict[str, Any],
    oa_type: OaType,
    deal_covered: bool,
    deal_summary: RecommendDealSummary | None,
    inst_label: str,
) -> tuple[RecommendApcDisplay | None, float | None, str]:
    """Derive structured APC display, numeric EUR estimate, and plain cost label.

    The estimate is the shown price in EUR (before deal waivers): the
    publisher's list price, or without one the mean amount paid to OpenAPC.
    The label names which of the two it is. A list price in a currency
    without an exchange rate has no EUR estimate and is labelled in its own
    currency.
    """
    apc_source = item.get("apc_source")
    apc_currency = item.get("apc_currency")
    apc_price = item.get("apc_price")
    apc_year = item.get("apc_year")
    apc_low = item.get("apc_low")
    apc_high = item.get("apc_high")
    apc_stats = item.get("apc_stats") or []

    latest_mean: float | None = None
    if apc_stats:
        first_mean = apc_stats[0].get("euro_mean")
        if first_mean is not None:
            latest_mean = float(first_mean)

    apc_display: RecommendApcDisplay | None = None
    if apc_source:
        apc_display = RecommendApcDisplay(
            source=apc_source,
            currency=apc_currency,
            price=float(apc_price) if apc_price is not None else None,
            year=apc_year,
            low=float(apc_low) if apc_low is not None else None,
            high=float(apc_high) if apc_high is not None else None,
            mean=latest_mean,
        )

    is_list_price = apc_source in (ApcSource.OPENALEX, ApcSource.DOAJ)
    # Shown price in EUR (before deal waivers). None: no price known, or a
    # list price in a currency without an exchange rate.
    raw_eur: float | None = None
    if apc_price is not None and (
        apc_source == ApcSource.OPENAPC or (is_list_price and apc_currency == "EUR")
    ):
        raw_eur = float(apc_price)
    # A list price is exact; a mean of paid amounts is an estimate (~).
    prefix = "~" if apc_source == ApcSource.OPENAPC else ""
    what = "list price"
    if apc_source == ApcSource.OPENAPC:
        what = f"mean amount paid, OpenAPC {apc_year}"

    if oa_type == OaType.DIAMOND:
        return apc_display, 0.0, "€0 (Diamond OA)"

    if deal_covered:
        cap_reached = bool(
            item.get("deal_cap_reached") or (deal_summary and deal_summary.cap_reached)
        )
        discount_only = bool(deal_summary and deal_summary.is_discount_only)
        if not cap_reached and not discount_only:
            return apc_display, 0.0, f"€0 (Covered by {inst_label} deal)"
        if cap_reached:
            if raw_eur is not None:
                return (
                    apc_display,
                    raw_eur,
                    f"{prefix}{_fmt_eur(raw_eur)} APC ({what}; deal cap reached)",
                )
            return apc_display, None, f"Deal cap reached ({inst_label} deal)"
        # Discount-only deal.
        if raw_eur is not None:
            return apc_display, raw_eur, f"Discounted APC ({what} {prefix}{_fmt_eur(raw_eur)})"
        return apc_display, None, f"Discounted APC ({inst_label} deal)"

    if raw_eur is not None:
        return apc_display, raw_eur, f"{prefix}{_fmt_eur(raw_eur)} APC ({what})"

    if is_list_price and apc_price is not None and apc_currency:
        original = f"{apc_currency} {round(float(apc_price)):,}"
        return apc_display, None, f"{original} APC (list price, no euro exchange rate)"

    if oa_type == OaType.SUBSCRIPTION:
        green = item.get("green_oa")
        if green in ("submitted", "accepted", "published"):
            return apc_display, None, "Subscription (Green OA route)"
        return apc_display, None, "Subscription (no OA fee)"

    return apc_display, None, "APC unknown"


def _has_green_route(item: dict[str, Any]) -> bool:
    return not bool(item.get("jisc_oa_prohibited")) and bool(
        item.get("jisc_allows_sa_submitted")
        or item.get("jisc_allows_sa_accepted")
        or item.get("jisc_allows_sa_published")
    )


def _evaluate_constraints(
    *,
    req: RecommendRequest,
    item: dict[str, Any],
    oa_type: OaType,
    deal_covered: bool,
    deal_summary: RecommendDealSummary | None,
    estimated_cost_eur: float | None,
    funder_fit: FunderFit | None,
    has_structured_funder: bool,
) -> tuple[bool, int, str | None]:
    """Check funder & budget rules; return (strict_pass, relax_priority, relaxed_note).

    Lower relax_priority = gentler relaxation (shown earlier in alternatives).
    """
    prohibited = bool(item.get("jisc_oa_prohibited"))
    cap_reached = bool(item.get("deal_cap_reached") or (deal_summary and deal_summary.cap_reached))
    discount_only = bool(deal_summary and deal_summary.is_discount_only)
    free_deal = deal_covered and not cap_reached and not discount_only
    green_ok = _has_green_route(item)

    notes: list[str] = []
    priority = 0

    # 1) Funder rule
    funder_pass = True
    if has_structured_funder and funder_fit is not None:
        if funder_fit.status == "compliant":
            funder_pass = True
        elif funder_fit.status == "check":
            funder_pass = False
            priority = max(priority, 2)
            notes.append("Requires verifying Green OA deposit & embargo terms with your funder")
        else:
            funder_pass = False
            priority = max(priority, 4)
            if prohibited:
                notes.append("Publisher prohibits open-access self-archiving")
            else:
                notes.append("Does not meet your funder's structured OA policy")
    elif prohibited:
        funder_pass = False
        priority = max(priority, 5)
        notes.append("Publisher prohibits open-access self-archiving")

    # 2) Budget rule
    budget_pass = True
    if req.budget_mode == "none":
        if oa_type == OaType.DIAMOND or free_deal:
            budget_pass = True
        else:
            budget_pass = False
            if deal_covered and cap_reached:
                priority = max(priority, 1)
                notes.append("Institutional deal cap has been reached for the current year")
            elif deal_covered and discount_only:
                priority = max(priority, 2)
                notes.append("Institutional deal provides a partial discount rather than €0 OA")
            elif green_ok:
                priority = max(priority, 1)
                notes.append(
                    "Green OA / Taverne self-archiving route only (no €0 immediate publisher OA)"
                )
            elif estimated_cost_eur is not None and estimated_cost_eur > 0:
                priority = max(priority, 3)
                notes.append(
                    f"Charges an APC (~{_fmt_eur(estimated_cost_eur)}) above your €0 budget"
                )
            else:
                priority = max(priority, 3)
                notes.append("No confirmed €0 Diamond OA or institutional deal coverage")
    elif req.budget_mode == "capped":
        cap = req.max_apc_eur if req.max_apc_eur is not None else 0
        if (
            oa_type == OaType.DIAMOND
            or free_deal
            or (
                oa_type in (OaType.GOLD, OaType.GENERIC)
                and estimated_cost_eur is not None
                and estimated_cost_eur <= cap
            )
        ):
            budget_pass = True
        else:
            budget_pass = False
            if deal_covered and cap_reached:
                priority = max(priority, 1)
                notes.append(
                    "The institutional deal cap has been reached, so standard APCs may apply"
                )
            elif estimated_cost_eur is not None and estimated_cost_eur > cap:
                priority = max(priority, 2)
                notes.append(
                    f"Estimated APC ({_fmt_eur(estimated_cost_eur)}) exceeds your "
                    f"{_fmt_eur(cap)} cap"
                )
            elif green_ok:
                priority = max(priority, 2)
                notes.append("Green OA / Taverne route only (no immediate OA within your APC cap)")
            else:
                priority = max(priority, 3)
                notes.append("APC amount is unknown or outside your budget cap")
    elif req.budget_mode == "funder_pays":
        if (
            oa_type in (OaType.DIAMOND, OaType.GOLD, OaType.GENERIC)
            or deal_covered
            or (oa_type == OaType.HYBRID and estimated_cost_eur is not None)
        ):
            budget_pass = True
        else:
            budget_pass = False
            if green_ok:
                priority = max(priority, 1)
                notes.append("Subscription journal with Green OA route (no direct publisher OA)")
            else:
                priority = max(priority, 3)
                notes.append("Subscription journal without a direct open-access option")
    else:  # "any"
        budget_pass = True

    strict_pass = funder_pass and budget_pass
    relaxed_note = None if strict_pass else "; ".join(notes)
    return strict_pass, priority, relaxed_note


def _score_candidate(
    *,
    req: RecommendRequest,
    similarity: float,
    oa_type: OaType,
    deal_covered: bool,
    deal_summary: RecommendDealSummary | None,
    estimated_cost_eur: float | None,
    funder_fit: FunderFit | None,
    works: int,
    quartile: str | None,
) -> float:
    """Deterministic transparent ranking score built on top of semantic similarity."""
    score = similarity

    cap_reached = bool(deal_summary and deal_summary.cap_reached)
    deal_capped = bool(deal_summary and deal_summary.is_capped)
    within_cap = req.budget_mode != "capped" or (
        estimated_cost_eur is not None
        and estimated_cost_eur <= (req.max_apc_eur if req.max_apc_eur is not None else 0)
    )

    if oa_type == OaType.DIAMOND:
        score += 0.12
    elif deal_covered:
        if cap_reached:
            score += 0.03
        elif deal_capped:
            score += 0.075
        else:
            score += 0.10
    elif oa_type == OaType.GOLD and within_cap:
        score += 0.04

    if funder_fit is not None and funder_fit.status == "compliant":
        score += 0.06

    if req.prefer_institution_history and works > 0:
        score += min(0.045, 0.015 * math.log1p(works))

    if req.prefer_established:
        if quartile == "Q1":
            score += 0.03
        elif quartile == "Q2":
            score += 0.015

    return round(score, 4)


def _build_reasons_and_summary(
    *,
    cand: _EvaluatedCandidate,
    inst_label: str,
    funder_name: str | None,
    funder_structured: bool,
) -> tuple[str, list[RecommendReason]]:
    """Produce crisp plain-language argumentation and structured reason items."""
    item = cand.item
    reasons: list[RecommendReason] = []
    pct = round(cand.similarity * 100)
    topics = cand.topics

    # 1) Topical similarity
    topic_tone = "positive" if cand.similarity >= 0.70 else "neutral"
    topic_label = (
        f"Close topic match ({pct}%)" if cand.similarity >= 0.72 else f"Topic match ({pct}%)"
    )
    if topics:
        topic_detail = f"Covers {', '.join(topics)}."
    else:
        topic_detail = "Matches the topic of your title and abstract."
    reasons.append(
        RecommendReason(kind="topic", tone=topic_tone, label=topic_label, detail=topic_detail)
    )

    # 2) OA model / institutional deal / cost
    oa_phrase: str
    if cand.oa_type == OaType.DIAMOND:
        reasons.append(
            RecommendReason(
                kind="oa",
                tone="positive",
                label="Diamond open access (€0)",
                detail="Free to read and free to publish, with no APC charged to authors.",
            )
        )
        oa_phrase = "€0 diamond open access publishing"
    elif item.get("deal_covered") and cand.deal_summary:
        ds = cand.deal_summary
        pub_part = f" ({ds.publisher_name})" if ds.publisher_name else ""
        dur_part = f", {ds.duration_text}" if ds.duration_text else ""
        if ds.cap_reached:
            reasons.append(
                RecommendReason(
                    kind="deal",
                    tone="warning",
                    label=f"{inst_label} deal cap reached",
                    detail=(
                        f"Covered by an active {inst_label} agreement{pub_part}{dur_part}, "
                        "but the annual cap is reported reached."
                    ),
                )
            )
            oa_phrase = f"an active {inst_label} deal whose annual cap is reported reached"
        elif ds.is_discount_only:
            reasons.append(
                RecommendReason(
                    kind="deal",
                    tone="warning",
                    label=f"{inst_label} discount deal",
                    detail=(
                        f"An active {inst_label} agreement{pub_part}{dur_part} gives an APC "
                        "discount rather than full €0 coverage."
                    ),
                )
            )
            oa_phrase = f"a {inst_label} APC discount agreement"
        elif ds.is_capped:
            cap_note = f"Note: {ds.cap_text}" if ds.cap_text else "An annual cap applies."
            reasons.append(
                RecommendReason(
                    kind="deal",
                    tone="positive",
                    label=f"Covered by {inst_label} open access deal",
                    detail=(
                        f"€0 open access for eligible corresponding authors{pub_part}{dur_part}."
                    ),
                )
            )
            reasons.append(
                RecommendReason(
                    kind="deal_cap",
                    tone="warning",
                    label="Annual deal cap applies",
                    detail=cap_note.strip(),
                )
            )
            oa_phrase = f"€0 open access under a {inst_label} deal with an annual cap"
        else:
            reasons.append(
                RecommendReason(
                    kind="deal",
                    tone="positive",
                    label=f"Covered by {inst_label} open access deal",
                    detail=(
                        f"€0 open access for eligible corresponding authors{pub_part}{dur_part}."
                    ),
                )
            )
            oa_phrase = f"€0 open access under an active {inst_label} deal"
    elif cand.oa_type == OaType.GOLD:
        if cand.estimated_cost_eur is not None:
            reasons.append(
                RecommendReason(
                    kind="cost",
                    tone="positive" if cand.strict_pass else "warning",
                    label=f"Gold open access ({cand.estimated_cost_label})",
                    detail="All articles in this journal are published open access immediately.",
                )
            )
            oa_phrase = f"gold open access ({cand.estimated_cost_label})"
        elif (
            cand.apc_display is not None
            and cand.apc_display.price is not None
            and cand.apc_display.currency
        ):
            reasons.append(
                RecommendReason(
                    kind="cost",
                    tone="neutral",
                    label=f"Gold open access ({cand.estimated_cost_label})",
                    detail="All articles in this journal are published open access immediately.",
                )
            )
            oa_phrase = f"gold open access ({cand.estimated_cost_label})"
        else:
            reasons.append(
                RecommendReason(
                    kind="cost",
                    tone="neutral",
                    label="Gold open access (APC unknown)",
                    detail=(
                        "This is a gold open access journal. "
                        "Check the current APC on the journal page."
                    ),
                )
            )
            oa_phrase = "gold open access with an unconfirmed APC"
    else:
        green = item.get("green_oa")
        embargo = item.get("jisc_embargo_accepted_months")
        if green in ("submitted", "accepted", "published"):
            embargo_note = (
                f" with a {embargo}-month embargo on the accepted manuscript"
                if embargo is not None and embargo > 0
                else ""
            )
            reasons.append(
                RecommendReason(
                    kind="green_oa",
                    tone="neutral",
                    label=f"Green open access ({green} version)",
                    detail=(
                        "Permits repository self-archiving according to Jisc Open Policy Finder"
                        f"{embargo_note}."
                    ),
                )
            )
            oa_phrase = f"a green open access route for the {green} version"
        else:
            reasons.append(
                RecommendReason(
                    kind="oa",
                    tone="warning",
                    label=f"{cand.oa_type.value.capitalize()} journal",
                    detail=(
                        "No active institutional deal or confirmed €0 open access "
                        "route is on record."
                    ),
                )
            )
            oa_phrase = f"{cand.oa_type.value} publishing"

    # 3) Funder policy fit
    funder_phrase: str | None = None
    if funder_name and cand.funder_fit is not None:
        detail_txt = " ".join(cand.funder_fit.reasons) or f"Checked against {funder_name} policy."
        if not funder_structured or cand.funder_fit.status is None:
            reasons.append(
                RecommendReason(
                    kind="funder",
                    tone="neutral",
                    label=f"{funder_name}: check policy manually",
                    detail=detail_txt,
                )
            )
        elif cand.funder_fit.status == "compliant":
            reasons.append(
                RecommendReason(
                    kind="funder",
                    tone="positive",
                    label=f"Meets {funder_name} policy",
                    detail=detail_txt,
                )
            )
            funder_phrase = f"meets {funder_name} open access rules"
        elif cand.funder_fit.status == "check":
            reasons.append(
                RecommendReason(
                    kind="funder",
                    tone="warning",
                    label=f"{funder_name}: check green open access timing",
                    detail=detail_txt,
                )
            )
            funder_phrase = f"requires checking {funder_name} embargo rules"
        else:
            reasons.append(
                RecommendReason(
                    kind="funder",
                    tone="warning",
                    label=f"Does not meet {funder_name} policy",
                    detail=detail_txt,
                )
            )

    # 4) Institution track record
    works = int(item.get("works") or 0)
    inst_phrase: str | None = None
    if works > 0:
        noun = "publication" if works == 1 else "publications"
        reasons.append(
            RecommendReason(
                kind="institution",
                tone="positive",
                label=f"{works:,} {inst_label} {noun}",
                detail=f"Researchers at {inst_label} have published in this journal.",
            )
        )
        inst_phrase = f"{works:,} recent {inst_label} {noun}"

    # 5) Venue indicators (DORA-neutral)
    quartile = item.get("quartile")
    twoyr = item.get("twoyr_mean_citedness")
    if quartile or twoyr is not None:
        parts = []
        if quartile:
            parts.append(f"Scimago {quartile}")
        if twoyr is not None:
            parts.append(f"2-year mean citedness {twoyr:.1f}")
        if cand.h_index is not None:
            parts.append(f"h-index {cand.h_index}")
        reasons.append(
            RecommendReason(
                kind="metrics",
                tone="neutral",
                label=", ".join(parts[:2]),
                detail=(
                    f"Journal indicators ({', '.join(parts)}). Interpret these alongside scope "
                    "and readership."
                ),
            )
        )

    # Compose 1 to 2 sentence plain-language summary
    lead = (
        f"Close topic match ({pct}% similarity) with {oa_phrase}."
        if cand.similarity >= 0.72
        else f"Topic match ({pct}% similarity) with {oa_phrase}."
    )
    if funder_phrase and inst_phrase:
        summary = f"{lead} It {funder_phrase}, and has {inst_phrase}."
    elif funder_phrase:
        summary = f"{lead} It {funder_phrase}."
    elif inst_phrase:
        summary = f"{lead} It has {inst_phrase}."
    else:
        summary = lead

    return summary, reasons


def _build_ranking_factors(
    req: RecommendRequest,
    inst_label: str,
    funder_name: str | None,
    funder_structured: bool,
) -> list[str]:
    factors = [
        "Local bge-small-en-v1.5 topic similarity between your text and journal profiles.",
        "Open access bonuses: diamond open access (+0.12), active institutional deal (+0.10), "
        "capped deal (+0.075), gold open access (+0.04).",
    ]
    if req.budget_mode == "none":
        factors.append(
            "Budget rule: €0 APC only (diamond open access or active institutional deal)."
        )
    elif req.budget_mode == "capped":
        cap = req.max_apc_eur if req.max_apc_eur is not None else 0
        factors.append(f"Budget rule: APC up to {_fmt_eur(cap)}, or €0 diamond or deal.")
    elif req.budget_mode == "funder_pays":
        factors.append("Budget rule: open access options eligible for funder or grant APC payment.")
    else:
        factors.append("Budget rule: all non-prohibited journals, with open access ranked higher.")

    if funder_name:
        if funder_structured:
            factors.append(
                f"Funder check: {funder_name} (Jisc Open Policy Finder structured policy, +0.06)."
            )
        else:
            factors.append(
                f"Funder selected: {funder_name} (text-only policy, check conditions manually)."
            )
    if req.prefer_institution_history:
        factors.append(
            f"Bonus for journals where {inst_label} authors already publish (up to +0.045)."
        )
    if req.prefer_established:
        factors.append("Bonus for Scimago Q1 (+0.03) and Q2 (+0.015) journals.")
    if not req.include_non_journals:
        factors.append("Venue filter: peer-reviewed journals only.")
    else:
        factors.append("Venue filter: includes book series and conference series.")
    factors.append(
        f"Quality filter: journals with OpenAlex works in {active_since()} or later, listed "
        "in Scimago, DOAJ, an institutional deal, or a curated index (CWTS core, national "
        "journal lists, ERIH PLUS, MEDLINE, SciELO)."
    )
    return factors


async def recommend_journals(
    session: AsyncSession,
    institution: Institution,
    req: RecommendRequest,
) -> RecommendResponse:
    """Run the Guided Journal Finder pipeline for one institution."""
    inst_label = institution.short_name or institution.name

    funder_name: str | None = None
    funder_policy: dict[str, Any] | None = None
    has_structured_funder = False
    if req.funder_id is not None:
        funder_row = await session.get(JiscFunder, req.funder_id)
        if funder_row is None:
            raise HTTPException(status_code=404, detail=f"funder {req.funder_id} not found")
        funder_name = funder_row.name or f"Funder {req.funder_id}"
        funder_policy = funder_row.publications_policy
        has_structured_funder = policy_structured(funder_policy)

    query_text = build_query_text(req.title, req.abstract)
    query_vec = await asyncio.to_thread(embeddings.encode_query, query_text)

    dist_expr = Journal.embedding.cosine_distance(query_vec)
    subq = (
        base_query(
            institution_id=institution.id,
            pub_type=None if req.include_non_journals else "journal",
            active=True,
            vouched=True,
        )
        .add_columns(
            dist_expr.label("dist"),
            Journal.topics.label("raw_topics"),
            Journal.summary_stats.label("raw_summary_stats"),
            Journal.jisc_oa_prohibited.label("jisc_oa_prohibited"),
            Journal.jisc_allows_sa_submitted.label("jisc_allows_sa_submitted"),
            Journal.jisc_allows_sa_accepted.label("jisc_allows_sa_accepted"),
            Journal.jisc_allows_sa_published.label("jisc_allows_sa_published"),
            Journal.jisc_embargo_accepted_months.label("jisc_embargo_accepted_months"),
        )
        .where(
            Journal.embedding.is_not(None),
            dist_expr <= RECOMMEND_MAX_DISTANCE,
        )
        .subquery()
    )

    await session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
    await session.execute(text(f"SET LOCAL hnsw.ef_search = {CANDIDATE_POOL_LIMIT}"))
    rows = (
        await session.execute(
            select(subq)
            .order_by(subq.c.dist.asc(), subq.c.issn_l.asc())
            .limit(CANDIDATE_POOL_LIMIT)
        )
    ).all()

    items: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row._mapping)
        data["twoyr_mean_citedness"] = (
            float(data.pop("twoyr")) if data.get("twoyr") is not None else None
        )
        data.pop("rank", None)
        items.append(data)

    if items:
        await attach_apc_display(session, items)

    covered_issns = [i["issn_l"] for i in items if i.get("deal_covered")]
    cap_reached_map = {i["issn_l"]: bool(i.get("deal_cap_reached")) for i in items}
    deals_map = await _fetch_active_deals(session, institution.id, covered_issns, cap_reached_map)

    missing_h_issns = [
        i["issn_l"]
        for i in items
        if not isinstance(i.get("raw_summary_stats"), dict)
        or i["raw_summary_stats"].get("h_index") is None
    ]
    scimago_h = await _fetch_scimago_h_index(session, missing_h_issns)

    evaluated: list[_EvaluatedCandidate] = []
    for item in items:
        issn_l = item["issn_l"]
        oa_raw = item.get("oa_type") or OaType.SUBSCRIPTION
        oa_type = oa_raw if isinstance(oa_raw, OaType) else OaType(str(oa_raw))
        dist = float(item.get("dist") or 0.0)
        similarity = round(max(0.0, min(1.0, 1.0 - dist)), 4)
        deal_covered = bool(item.get("deal_covered"))
        deal_summary = deals_map.get(issn_l) if deal_covered else None

        apc_display, est_eur, est_label = _extract_apc_and_cost(
            item, oa_type, deal_covered, deal_summary, inst_label
        )

        funder_fit: FunderFit | None = None
        if req.funder_id is not None:
            funder_fit = compute_funder_fit(
                funder_policy,
                JournalFacts(
                    oa_type=oa_type.value,
                    prohibited=item.get("jisc_oa_prohibited"),
                    sa_submitted=item.get("jisc_allows_sa_submitted"),
                    sa_accepted=item.get("jisc_allows_sa_accepted"),
                    sa_published=item.get("jisc_allows_sa_published"),
                    deal_covered=deal_covered,
                    publisher_name=item.get("publisher_name"),
                ),
            )

        strict_pass, relax_priority, relaxed_note = _evaluate_constraints(
            req=req,
            item=item,
            oa_type=oa_type,
            deal_covered=deal_covered,
            deal_summary=deal_summary,
            estimated_cost_eur=est_eur,
            funder_fit=funder_fit,
            has_structured_funder=has_structured_funder,
        )

        works = int(item.get("works") or 0)
        quartile = item.get("quartile")
        match_score = _score_candidate(
            req=req,
            similarity=similarity,
            oa_type=oa_type,
            deal_covered=deal_covered,
            deal_summary=deal_summary,
            estimated_cost_eur=est_eur,
            funder_fit=funder_fit,
            works=works,
            quartile=quartile,
        )

        raw_stats = item.get("raw_summary_stats") or {}
        h_raw = raw_stats.get("h_index") if isinstance(raw_stats, dict) else None
        h_index = int(h_raw) if h_raw is not None else scimago_h.get(issn_l)

        raw_topics = item.get("raw_topics") or []
        topics = [
            str(t["display_name"])
            for t in raw_topics
            if isinstance(t, dict) and t.get("display_name")
        ][:3]

        evaluated.append(
            _EvaluatedCandidate(
                item=item,
                oa_type=oa_type,
                similarity=similarity,
                deal_summary=deal_summary,
                apc_display=apc_display,
                estimated_cost_eur=est_eur,
                estimated_cost_label=est_label,
                funder_fit=funder_fit,
                h_index=h_index,
                topics=topics,
                strict_pass=strict_pass,
                match_score=match_score,
                relax_priority=relax_priority,
                relaxed_note=relaxed_note,
            )
        )

    strict_pool = [c for c in evaluated if c.strict_pass]
    strict_pool.sort(key=lambda c: (-c.match_score, -c.similarity, c.item["issn_l"]))

    relaxed = len(strict_pool) < MIN_STRICT_BEFORE_RELAX
    alt_pool: list[_EvaluatedCandidate] = []
    if relaxed:
        alt_pool = [c for c in evaluated if not c.strict_pass]
        alt_pool.sort(
            key=lambda c: (c.relax_priority, -c.match_score, -c.similarity, c.item["issn_l"])
        )
        alt_pool = alt_pool[:MAX_ALTERNATIVES]

    def _to_schema(rank: int, cand: _EvaluatedCandidate) -> RecommendedJournal:
        summary, reasons = _build_reasons_and_summary(
            cand=cand,
            inst_label=inst_label,
            funder_name=funder_name,
            funder_structured=has_structured_funder,
        )
        item = cand.item
        green_raw = item.get("green_oa")
        green_str = green_raw.value if hasattr(green_raw, "value") else green_raw
        return RecommendedJournal(
            rank=rank,
            issn_l=item["issn_l"],
            title=item.get("title"),
            publisher=item.get("publisher_name") or item.get("publisher_canonical"),
            oa_type=cand.oa_type,
            deal_covered=bool(item.get("deal_covered")),
            deal_summary=cand.deal_summary,
            similarity=cand.similarity,
            match_score=cand.match_score,
            estimated_cost_label=cand.estimated_cost_label,
            estimated_cost_eur=cand.estimated_cost_eur,
            apc_display=cand.apc_display,
            funder_fit=(
                FunderFitOut(status=cand.funder_fit.status, reasons=cand.funder_fit.reasons)
                if cand.funder_fit is not None
                else None
            ),
            green_oa=str(green_str) if green_str is not None else None,
            quartile=item.get("quartile"),
            twoyr_mean_citedness=item.get("twoyr_mean_citedness"),
            h_index=cand.h_index,
            works=int(item.get("works") or 0),
            topics=cand.topics,
            summary=summary,
            reasons=reasons,
            relaxed_note=cand.relaxed_note,
        )

    recommendations = [_to_schema(i + 1, c) for i, c in enumerate(strict_pool[: req.limit])]
    alternatives = [_to_schema(i + 1, c) for i, c in enumerate(alt_pool)]

    return RecommendResponse(
        recommendations=recommendations,
        alternatives=alternatives,
        candidate_pool_size=len(evaluated),
        strict_match_count=len(strict_pool),
        relaxed=relaxed,
        funder_name=funder_name,
        funder_policy_structured=has_structured_funder,
        ranking_factors=_build_ranking_factors(req, inst_label, funder_name, has_structured_funder),
    )
