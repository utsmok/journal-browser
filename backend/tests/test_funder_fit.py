"""Unit tests for the funder-fit tier engine (services/funder_fit.py)."""

import pytest

from journal_browser.services.funder_fit import (
    FunderFit,
    JournalFacts,
    compute_funder_fit,
    policy_structured,
)

STRUCTURED = {"archiving_policy": {"when": {"when": "within_12_months"}, "where": {}}}
IMMEDIATE = {"archiving_policy": {"when": {"when": "at_earliest_opportunity"}}}


def facts(**kw) -> JournalFacts:
    base = {
        "oa_type": "subscription",
        "prohibited": False,
        "sa_submitted": False,
        "sa_accepted": False,
        "sa_published": False,
        "deal_covered": False,
        "publisher_name": "Elsevier",
    }
    return JournalFacts(**{**base, **kw})


def test_text_only_policy_has_no_tier():
    fit = compute_funder_fit(None, facts())
    assert fit == FunderFit(None, ["Funder policy is text-only; check manually"])
    assert not policy_structured({"title_only": True})


def test_prohibited_beats_everything():
    # Even a gold DOAJ journal under a structured policy stays "no".
    fit = compute_funder_fit(STRUCTURED, facts(prohibited=True, oa_type="gold", deal_covered=True))
    assert fit.status == "no"
    assert fit.reasons == ["Publisher prohibits OA deposit"]


def test_gold_and_diamond_compliant():
    for oa in ("gold", "diamond"):
        assert compute_funder_fit(STRUCTURED, facts(oa_type=oa)).status == "compliant"


def test_generic_oa_type_falls_through():
    # generic = unknown oa_type; must not count as fully OA.
    assert compute_funder_fit(STRUCTURED, facts(oa_type="generic", sa_published=True)).status == (
        "check"
    )


def test_deal_compliant_names_publisher():
    fit = compute_funder_fit(STRUCTURED, facts(deal_covered=True))
    assert fit.status == "compliant"
    assert fit.reasons == ["Covered by a transformative agreement (Elsevier)"]
    assert compute_funder_fit(
        STRUCTURED, facts(deal_covered=True, publisher_name=None)
    ).reasons == ["Covered by a transformative agreement (publisher)"]


@pytest.mark.parametrize("which", ["sa_submitted", "sa_accepted", "sa_published"])
def test_green_route_check(which):
    assert compute_funder_fit(STRUCTURED, facts(**{which: True})).status == "check"


def test_green_check_appends_immediate_deposit():
    fit = compute_funder_fit(IMMEDIATE, facts(sa_submitted=True))
    assert fit.status == "check"
    assert fit.reasons == [
        "Green route available; publisher embargo is unstated, verify the funder's deposit timing",
        "Funder requires immediate deposit",
    ]


def test_no_route_no():
    assert compute_funder_fit(STRUCTURED, facts()) == FunderFit(
        "no", ["No OA route or agreement found for this journal"]
    )


def test_deal_branch_requires_structured_policy():
    # An unstructured (text-only) funder never reaches the deal tier.
    fit = compute_funder_fit({}, facts(deal_covered=True))
    assert fit.status is None
