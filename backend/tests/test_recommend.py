"""Tests for the Guided Journal Finder recommendation endpoint."""

import logging
import math

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.harvest.denorm import refresh_apcs
from journal_browser.models import (
    Deal,
    DealInstitution,
    DealJournal,
    Institution,
    JiscFunder,
    JournalApcAggregate,
    JournalFlags,
    Publisher,
    ScimagojrMetric,
)
from journal_browser.services.recommend import build_query_text

DIM = 384


def _unit_vec(angle_deg: float = 0.0) -> list[float]:
    """2D unit vector embedded in 384 dims; angle_deg from axis 0 sets cosine distance."""
    rad = math.radians(angle_deg)
    vec = [0.0] * DIM
    vec[0] = math.cos(rad)
    vec[1] = math.sin(rad)
    return vec


@pytest.fixture
async def recommend_fixture(client, db_engine, monkeypatch):
    """Seed a diverse set of embedded journals, deals, and funders."""
    monkeypatch.setattr(
        "journal_browser.services.embeddings.encode_query",
        lambda _q: _unit_vec(0.0),
    )

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        inst = Institution(
            code="ut",
            name="University of Twente",
            short_name="UT",
            ror="https://ror.org/006hf6230",
            active=True,
        )
        session.add(inst)
        await session.flush()

        pub_elsevier = Publisher(name="Elsevier")
        pub_capped = Publisher(name="Capped Publisher")
        session.add_all([pub_elsevier, pub_capped])
        await session.flush()

        # Structured funder (e.g. NWO) + text-only funder
        funder_nwo = JiscFunder(
            id=101,
            name="Dutch Research Council (NWO)",
            country="NL",
            publications_policy={
                "archiving_policy": {
                    "when": {"when": "at_earliest_opportunity"},
                }
            },
        )
        funder_text = JiscFunder(
            id=102,
            name="Text Only Foundation",
            country="NL",
            publications_policy={"notes": "See website"},
        )
        session.add_all([funder_nwo, funder_text])

        # Active uncapped deal + capped deal
        deal_free = Deal(
            publisher_id=pub_elsevier.id,
            status="current",
            start_year=2024,
            end_year=2026,
            duration_text="2024–2026",
            summary="100% open access publishing at no extra cost.",
            openaccess_nl_url="https://openaccess.nl/deals/elsevier",
        )
        deal_capped = Deal(
            publisher_id=pub_capped.id,
            status="current",
            start_year=2025,
            end_year=2026,
            duration_text="2025–2026",
            cap_text="Annual national cap of 500 articles.",
            summary="Full OA covered up to the annual cap.",
        )
        session.add_all([deal_free, deal_capped])
        await session.flush()

        session.add_all(
            [
                DealInstitution(
                    deal_id=deal_free.id, institution_id=inst.id, participation="consortium"
                ),
                DealInstitution(
                    deal_id=deal_capped.id, institution_id=inst.id, participation="consortium"
                ),
            ]
        )

        # Journals with controlled cosine angles from _unit_vec(0):
        # cos(10°) ≈ 0.9848 (dist 0.015), cos(15°) ≈ 0.9659 (dist 0.034),
        # cos(20°) ≈ 0.9397 (dist 0.060), cos(80°) ≈ 0.1736 (dist 0.826 -> filtered out)
        journals = [
            # 1. Diamond OA journal (very close, €0)
            journal_factory(
                "1000-0001",
                title="Open Microfluidics",
                publisher_name="Diamond Press",
                is_oa=True,
                is_in_doaj=True,
                doaj_in_doaj=True,
                doaj_has_apc=False,
                latest_quartile="Q2",
                summary_stats={"two_yr_mean_citedness": 3.4, "h_index": 42},
                topics=[
                    {"display_name": "Microfluidics"},
                    {"display_name": "Droplet Dynamics"},
                ],
                embedding=_unit_vec(15.0),
            ),
            # 2. Active uncapped deal journal (hybrid, covered by UT deal)
            journal_factory(
                "1000-0002",
                title="Journal of Fluid Membranes",
                publisher_name="Elsevier",
                is_oa=False,
                latest_quartile="Q1",
                summary_stats={"two_yr_mean_citedness": 6.2},
                topics=[{"display_name": "Membrane Technology"}],
                embedding=_unit_vec(16.0),
            ),
            # 3. Active capped deal journal (not reached yet). On no curated
            # list: the deal alone keeps it recommendable.
            journal_factory(
                "1000-0003",
                title="Capped Deal Sensors",
                publisher_name="Capped Publisher",
                is_oa=False,
                latest_quartile="Q1",
                listed_in=[],
                embedding=_unit_vec(16.0),
            ),
            # 4. Gold OA within €2,000 cap (€1,500)
            journal_factory(
                "1000-0004",
                title="Affordable Gold Fluids",
                publisher_name="MDPI",
                is_oa=True,
                is_in_doaj=True,
                doaj_in_doaj=True,
                doaj_has_apc=True,
                apc_prices=[{"currency": "EUR", "price": 1500}],
                latest_quartile="Q2",
                embedding=_unit_vec(12.0),
            ),
            # 5. Expensive Gold OA (€3,800)
            journal_factory(
                "1000-0005",
                title="Premium Gold Fluids",
                publisher_name="Nature Portfolio",
                is_oa=True,
                is_in_doaj=True,
                doaj_in_doaj=True,
                doaj_has_apc=True,
                apc_prices=[{"currency": "EUR", "price": 3800}],
                latest_quartile="Q1",
                embedding=_unit_vec(10.0),
            ),
            # 6. Subscription with Green OA route (funder check)
            journal_factory(
                "1000-0006",
                title="Green Route Fluids",
                publisher_name="Classic Press",
                is_oa=False,
                jisc_in_opf=True,
                jisc_oa_prohibited=False,
                jisc_allows_sa_accepted=True,
                jisc_embargo_accepted_months=12,
                embedding=_unit_vec(14.0),
            ),
            # 7. Subscription with OA prohibited
            journal_factory(
                "1000-0007",
                title="Prohibited Closed Fluids",
                publisher_name="Strict Press",
                is_oa=False,
                jisc_in_opf=True,
                jisc_oa_prohibited=True,
                embedding=_unit_vec(11.0),
            ),
            # 8. Non-journal book series (LNCS)
            journal_factory(
                "1000-0008",
                title="Lecture Notes in Fluid Computing",
                publisher_name="Springer",
                type="book series",
                is_oa=True,
                doaj_in_doaj=True,
                doaj_has_apc=False,
                embedding=_unit_vec(8.0),
            ),
            # 9. Far unrelated journal (dist > 0.45 -> must be discarded)
            journal_factory(
                "1000-0009",
                title="Medieval Poetry Review",
                publisher_name="Arts Press",
                is_oa=True,
                doaj_in_doaj=True,
                doaj_has_apc=False,
                embedding=_unit_vec(80.0),
            ),
            # 10. Ceased journal: nearest vector, but no works since 2021.
            journal_factory(
                "1000-0010",
                title="Defunct Microfluidics Letters",
                publisher_name="Gone Press",
                last_active_year=2021,
                embedding=_unit_vec(1.0),
            ),
            # 11. Active, but only on a weak list and nowhere else.
            journal_factory(
                "1000-0011",
                title="International Journal of Multidisciplinary Fluids",
                publisher_name="Mill Press",
                listed_in=["sinta-s5"],
                embedding=_unit_vec(2.0),
            ),
            # 12. Active, never listed (NULL: no OpenAlex listing data).
            journal_factory(
                "1000-0012",
                title="Global Fluids Review",
                publisher_name="Mill Press",
                listed_in=None,
                embedding=_unit_vec(3.0),
            ),
            # 13. Gold OA with a €4,460 list price. OpenAPC saw its 2025
            # articles paid under a deal (€0) after paid ones in 2024: the
            # budget goes by the list price.
            journal_factory(
                "1000-0013",
                title="Deal-Paid Gold Membranes",
                publisher_name="Elsevier",
                is_oa=True,
                apc_prices=[{"currency": "EUR", "price": 4460}],
                embedding=_unit_vec(13.0),
            ),
            # 14. Gold OA without a list price; OpenAPC paid articles only.
            journal_factory(
                "1000-0014",
                title="Paid-Only Gold Membranes",
                publisher_name="Paid Press",
                is_oa=True,
                embedding=_unit_vec(14.0),
            ),
        ]
        session.add_all(journals)
        await session.flush()

        session.add_all(
            [
                DealJournal(
                    deal_id=deal_free.id, issn="1000-0002", issn_l="1000-0002", source="jct"
                ),
                DealJournal(
                    deal_id=deal_capped.id, issn="1000-0003", issn_l="1000-0003", source="jct"
                ),
                ScimagojrMetric(issn_l="1000-0002", year=2025, best_quartile="Q1", h_index=88),
            ]
        )
        session.add_all(
            [
                JournalApcAggregate(
                    issn_l="1000-0013", period=2025, article_count=2, paid_count=0, zero_count=2
                ),
                JournalApcAggregate(
                    issn_l="1000-0013",
                    period=2024,
                    article_count=3,
                    paid_count=1,
                    zero_count=2,
                    euro_min=1500,
                    euro_max=1500,
                    euro_mean=1500,
                ),
                JournalApcAggregate(
                    issn_l="1000-0014",
                    period=2024,
                    article_count=4,
                    paid_count=4,
                    zero_count=0,
                    euro_min=1000,
                    euro_max=2000,
                    euro_mean=1500,
                ),
            ]
        )

        # Materialize journal_flags for UT
        flags = [
            JournalFlags(
                institution_id=inst.id,
                issn_l="1000-0001",
                works_count=2,
                works_window_plus=20,
                deal_covered=False,
            ),
            JournalFlags(
                institution_id=inst.id,
                issn_l="1000-0002",
                works_count=18,
                works_window_plus=50,
                deal_covered=True,
            ),
            JournalFlags(
                institution_id=inst.id,
                issn_l="1000-0003",
                works_count=0,
                works_window_plus=30,
                deal_covered=True,
            ),
            JournalFlags(
                institution_id=inst.id,
                issn_l="1000-0004",
                works_count=5,
                works_window_plus=40,
                deal_covered=False,
            ),
            JournalFlags(
                institution_id=inst.id,
                issn_l="1000-0005",
                works_count=10,
                works_window_plus=60,
                deal_covered=False,
            ),
            JournalFlags(
                institution_id=inst.id,
                issn_l="1000-0006",
                works_count=1,
                works_window_plus=25,
                deal_covered=False,
            ),
            JournalFlags(
                institution_id=inst.id,
                issn_l="1000-0007",
                works_count=0,
                works_window_plus=25,
                deal_covered=False,
            ),
            JournalFlags(
                institution_id=inst.id,
                issn_l="1000-0008",
                works_count=4,
                works_window_plus=10,
                deal_covered=False,
            ),
            JournalFlags(
                institution_id=inst.id,
                issn_l="1000-0009",
                works_count=0,
                works_window_plus=15,
                deal_covered=False,
            ),
            *(
                JournalFlags(institution_id=inst.id, issn_l=issn, works_window_plus=500)
                for issn in ("1000-0010", "1000-0011", "1000-0012", "1000-0013", "1000-0014")
            ),
        ]
        session.add_all(flags)
        # The price columns are denormalized, as after a harvest.
        await refresh_apcs(session)
        await session.commit()

    return client


def test_build_query_text_truncates_cleanly():
    long_abstract = "microfluidics " * 300
    result = build_query_text("Droplet Dynamics", long_abstract, max_chars=200)
    assert result.startswith("Droplet Dynamics\n\n")
    assert len(result) <= 200


@requires_db
async def test_recommend_validates_short_input_and_unknown_funder(recommend_fixture):
    client = recommend_fixture

    # Combined text shorter than 15 chars -> 422
    res_short = await client.post(
        "/api/v1/ut/journals/recommend",
        json={"title": "Short", "abstract": "tiny"},
    )
    assert res_short.status_code == 422

    # Unknown funder -> 404
    res_404 = await client.post(
        "/api/v1/ut/journals/recommend",
        json={
            "title": "Microfluidic droplet generation in lab-on-a-chip devices",
            "funder_id": 999999,
        },
    )
    assert res_404.status_code == 404


@requires_db
async def test_recommend_budget_none_prefers_diamond_and_deals(recommend_fixture):
    client = recommend_fixture
    res = await client.post(
        "/api/v1/ut/journals/recommend",
        json={
            "title": "Microfluidic droplet dynamics in polymeric channels",
            "abstract": "We study interfacial tension and droplet breakup regimes.",
            "budget_mode": "none",
            "prefer_institution_history": False,
        },
    )
    assert res.status_code == 200
    body = res.json()

    # Only Diamond + active uncapped/capped deals pass €0 budget (3 matches -> not relaxed)
    issns = [r["issn_l"] for r in body["recommendations"]]
    assert set(issns) == {"1000-0001", "1000-0002", "1000-0003"}
    assert "1000-0009" not in issns  # unrelated vector discarded
    assert "1000-0008" not in issns  # non-journal excluded by default
    assert body["relaxed"] is False
    assert body["alternatives"] == []
    assert body["strict_match_count"] == 3

    # Diamond (+0.12) beats uncapped deal (+0.10) beats capped deal (+0.075)
    assert issns == ["1000-0001", "1000-0002", "1000-0003"]

    first = body["recommendations"][0]
    assert first["rank"] == 1
    assert first["estimated_cost_eur"] == 0.0
    assert "Diamond" in first["estimated_cost_label"]
    assert first["h_index"] == 42
    assert first["topics"] == ["Microfluidics", "Droplet Dynamics"]
    assert first["summary"]
    assert len(first["reasons"]) >= 2

    # ScimagoJR h-index fallback + deal summary on second item
    second = body["recommendations"][1]
    assert second["deal_covered"] is True
    assert second["deal_summary"]["publisher_name"] == "Elsevier"
    assert second["deal_summary"]["is_capped"] is False
    assert second["h_index"] == 88

    # Capped deal carries a warning reason
    third = body["recommendations"][2]
    assert third["deal_summary"]["is_capped"] is True
    assert any(r["tone"] == "warning" for r in third["reasons"])


@requires_db
async def test_recommend_budget_capped_and_funder_fit(recommend_fixture):
    client = recommend_fixture
    res = await client.post(
        "/api/v1/ut/journals/recommend",
        json={
            "title": "High-throughput membrane filtration for wastewater reuse",
            "funder_id": 101,
            "budget_mode": "capped",
            "max_apc_eur": 2000,
            "prefer_institution_history": True,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["funder_name"] == "Dutch Research Council (NWO)"
    assert body["funder_policy_structured"] is True

    issns = [r["issn_l"] for r in body["recommendations"]]
    # Affordable Gold (€1,500) now passes alongside Diamond and deals; €3,800 Gold stays out
    assert "1000-0004" in issns
    assert "1000-0005" not in issns
    assert "1000-0006" not in issns  # Green-only is funder "check"
    assert "1000-0007" not in issns  # Prohibited is funder "no"
    for rec in body["recommendations"]:
        assert rec["funder_fit"]["status"] == "compliant"


@requires_db
async def test_recommend_budget_uses_the_list_price_over_paid_amounts(recommend_fixture):
    client = recommend_fixture
    request = {
        "title": "High-throughput membrane filtration for wastewater reuse",
        "budget_mode": "capped",
        "prefer_institution_history": True,
        "limit": 20,
    }
    res = await client.post("/api/v1/ut/journals/recommend", json={**request, "max_apc_eur": 2000})
    assert res.status_code == 200
    by_issn = {r["issn_l"]: r for r in res.json()["recommendations"]}

    # A €4,460 list price stays over a €2,000 cap, although the journal's
    # newest OpenAPC articles were paid under a deal and older ones at
    # €1,500.
    assert "1000-0013" not in by_issn
    # Without a list price the mean amount paid decides, and the label
    # says so. A known list price is labelled as one.
    paid = by_issn["1000-0014"]
    assert paid["estimated_cost_eur"] == 1500.0
    assert paid["estimated_cost_label"] == "~€1,500 APC (mean amount paid, OpenAPC 2024)"
    assert (paid["apc_display"]["source"], paid["apc_display"]["year"]) == ("openapc", 2024)
    listed = by_issn["1000-0004"]
    assert listed["estimated_cost_label"] == "€1,500 APC (list price)"
    assert listed["apc_display"]["source"] == "openalex"

    # Over its list price, the deal-paid journal passes too.
    res = await client.post("/api/v1/ut/journals/recommend", json={**request, "max_apc_eur": 5000})
    by_issn = {r["issn_l"]: r for r in res.json()["recommendations"]}
    assert by_issn["1000-0013"]["estimated_cost_label"] == "€4,460 APC (list price)"


@requires_db
async def test_recommend_relaxation_returns_alternatives_with_notes(recommend_fixture, db_engine):
    """When fewer than 3 strict matches exist, relaxed alternatives are returned."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        # Mark the two deal journals as cap-reached so only Diamond passes €0 strictly
        for issn in ("1000-0002", "1000-0003"):
            flag = await session.get(JournalFlags, (1, issn))
            assert flag is not None
            flag.deal_cap_reached = True
        await session.commit()

    client = recommend_fixture
    res = await client.post(
        "/api/v1/ut/journals/recommend",
        json={
            "title": "Microfluidic droplet breakup in lab-on-chip systems",
            "budget_mode": "none",
            "funder_id": 101,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["strict_match_count"] == 1
    assert body["relaxed"] is True
    assert [r["issn_l"] for r in body["recommendations"]] == ["1000-0001"]
    assert len(body["alternatives"]) >= 2
    for alt in body["alternatives"]:
        assert alt["relaxed_note"]


@requires_db
async def test_recommend_include_non_journals_and_established_boost(recommend_fixture):
    client = recommend_fixture
    res = await client.post(
        "/api/v1/ut/journals/recommend",
        json={
            "title": "Microfluidic computing architectures and algorithms",
            "budget_mode": "none",
            "include_non_journals": True,
            "prefer_established": True,
        },
    )
    assert res.status_code == 200
    body = res.json()
    issns = [r["issn_l"] for r in body["recommendations"]]
    assert "1000-0008" in issns
    assert any("Scimago Q1" in f for f in body["ranking_factors"])


@requires_db
async def test_recommend_skips_inactive_and_unlisted_journals(recommend_fixture):
    """The three nearest vectors are inactive or unlisted: none is offered,
    not even when every budget passes."""
    res = await recommend_fixture.post(
        "/api/v1/ut/journals/recommend",
        json={"title": "Microfluidic droplet dynamics", "budget_mode": "any"},
    )
    assert res.status_code == 200
    body = res.json()
    offered = {r["issn_l"] for r in body["recommendations"] + body["alternatives"]}
    assert offered, "the eligible journals still match"
    assert offered.isdisjoint({"1000-0010", "1000-0011", "1000-0012"})
    assert any(f.startswith("Quality filter") for f in body["ranking_factors"])

    # The journal-detail similar lists apply the same rule.
    similar = (await recommend_fixture.get("/api/v1/ut/journals/1000-0001/similar")).json()
    listed = {i["issn_l"] for items in similar.values() for i in items}
    assert "1000-0004" in listed
    assert listed.isdisjoint({"1000-0010", "1000-0011", "1000-0012"})


@requires_db
async def test_recommend_never_logs_manuscript_text(recommend_fixture, caplog):
    secret_phrase = "CONFIDENTIAL_UNPUBLISHED_MANUSCRIPT_XYZ_9876"
    with caplog.at_level(logging.DEBUG):
        res = await recommend_fixture.post(
            "/api/v1/ut/journals/recommend",
            json={
                "title": secret_phrase,
                "abstract": f"Detailed secret findings: {secret_phrase}.",
            },
        )
    assert res.status_code == 200
    assert secret_phrase not in caplog.text
