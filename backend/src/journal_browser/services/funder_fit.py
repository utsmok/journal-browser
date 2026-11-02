"""Funder-OA-policy fit for a journal: pure tier engine + SQL twin.

The tier engine (compute_funder_fit) is the source of truth for status and
reasons. fit_case() mirrors the same rule order as a SQL CASE for facet
counts, where evaluating the whole corpus in Python would defeat the shared
base pass. Change them together or not at all."""

from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import case, or_
from sqlalchemy.sql.elements import ColumnElement

#: Rule 4: the funder's deposit timing demand, keyed on
#: publications_policy.archiving_policy.when.when.
IMMEDIATE = "at_earliest_opportunity"

#: Funder policy tiers; None = funder policy is text-only, no tier exists.
FitStatus = Literal["compliant", "check", "no"]


@dataclass
class JournalFacts:
    """The per-journal columns the rules read; one row of the search base."""

    oa_type: str
    prohibited: bool | None
    sa_submitted: bool | None
    sa_accepted: bool | None
    sa_published: bool | None
    deal_covered: bool
    publisher_name: str | None = None


@dataclass
class FunderFit:
    status: FitStatus | None
    reasons: list[str] = field(default_factory=list)


def policy_structured(publications_policy: dict[str, Any] | None) -> bool:
    """True when the OPF payload carries the structured archiving_policy
    block (201/202 funders); text-only funders get no tier at all."""
    return bool((publications_policy or {}).get("archiving_policy"))


def compute_funder_fit(
    publications_policy: dict[str, Any] | None, facts: JournalFacts
) -> FunderFit:
    """Rule tiers, first match wins (spec order):

    1. publisher prohibits OA deposit -> no
    2. gold/diamond journal -> compliant
    3. transformative deal (funder policy structured only) -> compliant
    4. any free green route -> check (+ immediate-deposit note)
    5. otherwise -> no
    """
    if not policy_structured(publications_policy):
        return FunderFit(None, ["Funder policy is text-only; check manually"])
    if facts.prohibited:
        return FunderFit("no", ["Publisher prohibits OA deposit"])
    if facts.oa_type in ("gold", "diamond"):
        return FunderFit("compliant", ["Fully OA journal (DOAJ-registered)"])
    if facts.deal_covered:
        name = facts.publisher_name or "publisher"
        return FunderFit("compliant", [f"Covered by a transformative agreement ({name})"])
    if facts.sa_submitted or facts.sa_accepted or facts.sa_published:
        reasons = [
            "Green route available; publisher embargo is unstated,"
            " verify the funder's deposit timing"
        ]
        when = ((publications_policy or {}).get("archiving_policy") or {}).get("when") or {}
        if when.get("when") == IMMEDIATE:
            reasons.append("Funder requires immediate deposit")
        return FunderFit("check", reasons)
    return FunderFit("no", ["No OA route or agreement found for this journal"])


def fit_case(
    oa_type: ColumnElement[str],
    deal_covered: ColumnElement[bool],
    prohibited: ColumnElement[bool | None],
    sa_submitted: ColumnElement[bool | None],
    sa_accepted: ColumnElement[bool | None],
    sa_published: ColumnElement[bool | None],
) -> ColumnElement[str]:
    """SQL twin of compute_funder_fit's status tiers. Only valid for a
    structured funder (the deal branch requires it); the text-only path
    never reaches SQL. Keep in rule order with compute_funder_fit."""
    return case(
        (prohibited.is_(True), "no"),
        (oa_type.in_(("gold", "diamond")), "compliant"),
        (deal_covered.is_(True), "compliant"),
        (or_(sa_submitted.is_(True), sa_accepted.is_(True), sa_published.is_(True)), "check"),
        else_="no",
    )
