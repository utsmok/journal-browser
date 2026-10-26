"""Reconcile matching/merge unit tests (existing Postgres fixtures)."""

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from journal_browser.harvest.reconcile import (
    _code_of,
    durations_overlap,
    reconcile_deals,
    render_curation_report,
)
from journal_browser.models import (
    Deal,
    DealInstitution,
    DealJournal,
    Institution,
    Journal,
    ManualOverride,
    Publisher,
)


@pytest.fixture
async def maker(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


async def _publisher(session, name: str, slug: str | None = None) -> Publisher:
    p = Publisher(name=name, openaccess_nl_slug=slug)
    session.add(p)
    await session.flush()
    return p


async def _deal(session, publisher_id: int, **kw) -> Deal:
    d = Deal(
        publisher_id=publisher_id,
        status=kw.pop("status", "current"),
        corresponding_authors_only=kw.pop("corresponding_authors_only", False),
        provenance=[],
        **kw,
    )
    session.add(d)
    await session.flush()
    return d


def test_code_of():
    assert _code_of("kar2026caul") == "kar"
    assert _code_of("elsevier2025surf") == "elsevier"
    assert _code_of(None) is None
    assert _code_of("") is None


def test_durations_overlap():
    a = Deal(publisher_id=1, status="current", corresponding_authors_only=False, provenance=[])
    a.start_year, a.end_year = 2025, 2027
    b = Deal(publisher_id=2, status="current", corresponding_authors_only=False, provenance=[])
    b.start_year, b.end_year = 2024, 2026
    assert durations_overlap(a, b)
    b.start_year, b.end_year = 2028, 2030
    assert not durations_overlap(a, b)


async def test_merge_moves_journals_and_flags_unmatched(maker):
    async with maker() as session:
        pub_o = await _publisher(session, "Karger", slug="karger")
        pub_j = await _publisher(session, "KAR")
        inst = Institution(
            name="University of Twente",
            ror="https://ror.org/006hf6230",
            code="ut",
            active=True,
        )
        session.add(inst)
        await session.flush()
        oanl = await _deal(
            session,
            pub_o.id,
            openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/karger-2025-2027",
        )
        oanl.start_year, oanl.end_year = 2025, 2027
        jct = await _deal(
            session,
            pub_j.id,
            esac_id="kar2026caul",
            jct_data_url="https://jct.example/kar.csv",
            last_reviewed=date(2026, 1, 1),
        )
        jct.start_year, jct.end_year = 2026, 2027
        session.add(DealInstitution(deal_id=jct.id, institution_id=inst.id))
        session.add(
            DealJournal(deal_id=jct.id, issn="0250-6807", journal_name="Gerontology", source="jct")
        )
        await session.commit()
        oanl_id = oanl.id

    async with maker() as s2:
        stats = await reconcile_deals(s2)
    assert stats["matched"] == 1
    assert stats["unmatched_oanl"] == 0

    async with maker() as s3:
        d = await s3.get(Deal, oanl_id)
        assert d.esac_id == "kar2026caul"
        assert d.jct_data_url.endswith("kar.csv")
        journals = (await s3.execute(select(DealJournal))).scalars().all()
        assert len(journals) == 1 and journals[0].deal_id == oanl_id
        # The JCT shadow row is gone; one canonical deal remains.
        assert len((await s3.execute(select(Deal))).scalars().all()) == 1


async def test_unmatched_oanl_flagged_but_override_protected(maker):
    async with maker() as session:
        pub = await _publisher(session, "ACM", slug="acm")
        deal = await _deal(
            session,
            pub.id,
            openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/acm-2026-2028",
        )
        deal.start_year, deal.end_year = 2026, 2028
        session.add(
            ManualOverride(
                table_name="deals",
                row_key=str(deal.id),
                field="needs_curation",
                value=False,
                rationale="checked: local ACM deal",
            )
        )
        await session.commit()
        deal_id = deal.id

    async with maker() as s2:
        stats = await reconcile_deals(s2)
    assert stats["matched"] == 0

    async with maker() as s3:
        d = await s3.get(Deal, deal_id)
        # The override protects the curated value; reconcile must not re-flag.
        assert d.needs_curation is False
        assert d.needs_curation_reason is None


async def test_reconcile_is_idempotent(maker):
    async with maker() as session:
        pub_o = await _publisher(session, "Elsevier", slug="elsevier")
        oanl = await _deal(
            session,
            pub_o.id,
            openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/elsevier-2025-2027",
        )
        oanl.start_year, oanl.end_year = 2025, 2027
        oanl.esac_id = "elsevier2025surf"  # merged in a previous run
        await session.commit()

    keys = ("matched", "unmatched_jct", "unmatched_oanl")
    async with maker() as s2:
        first = await reconcile_deals(s2)
    async with maker() as s3:
        second = await reconcile_deals(s3)
    assert {k: first[k] for k in keys} == {k: second[k] for k in keys}

    async with maker() as s4:
        rows = (await s4.execute(select(Deal))).scalars().all()
        assert len(rows) == 1


async def test_prefers_twente_bearing_agreement(maker):
    async with maker() as session:
        pub_o = await _publisher(session, "Elsevier", slug="elsevier")
        pub_j = await _publisher(session, "ELS")
        inst = Institution(
            name="University of Twente",
            ror="https://ror.org/006hf6230",
            code="ut",
            active=True,
        )
        session.add(inst)
        await session.flush()
        oanl = await _deal(
            session,
            pub_o.id,
            openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/elsevier-2025-2027",
        )
        oanl.start_year, oanl.end_year = 2025, 2027
        # Two overlapping agreements: a foreign consortium and a Twente-bearing one.
        foreign = await _deal(session, pub_j.id, esac_id="els2026caul")
        foreign.start_year, foreign.end_year = 2025, 2027
        twente = await _deal(session, pub_j.id, esac_id="els2025ukb")
        twente.start_year, twente.end_year = 2025, 2026
        session.add(DealInstitution(deal_id=twente.id, institution_id=inst.id))
        await session.commit()
        oanl_id = oanl.id

    async with maker() as s2:
        stats = await reconcile_deals(s2)
    assert stats["matched"] == 1

    async with maker() as s3:
        d = await s3.get(Deal, oanl_id)
        assert d.esac_id == "els2025ukb"  # the Twente-bearing agreement won
        others = (
            (await s3.execute(select(Deal.esac_id).where(Deal.openaccess_nl_url.is_(None))))
            .scalars()
            .all()
        )
        assert "els2026caul" in others  # foreign agreement kept for provenance


async def test_dutch_consortium_tiebreak(maker):
    async with maker() as session:
        pub_o = await _publisher(session, "Wiley", slug="wiley")
        pub_j = await _publisher(session, "WILEY")
        oanl = await _deal(
            session,
            pub_o.id,
            openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/wiley-2024-2026",
        )
        oanl.start_year, oanl.end_year = 2024, 2026
        # UKB joint deal WITHOUT enumerated members vs a foreign consortium.
        ukb = await _deal(session, pub_j.id, esac_id="wiley2024ukb")
        ukb.start_year, ukb.end_year = 2024, 2026
        foreign = await _deal(session, pub_j.id, esac_id="wiley2024konsortium")
        foreign.start_year, foreign.end_year = 2024, 2026
        await session.commit()
        oanl_id = oanl.id

    async with maker() as s2:
        await reconcile_deals(s2)

    async with maker() as s3:
        d = await s3.get(Deal, oanl_id)
        assert d.esac_id == "wiley2024ukb"


async def test_consortium_merge_without_members_flagged(maker):
    async with maker() as session:
        pub_o = await _publisher(session, "Karger", slug="karger")
        pub_j = await _publisher(session, "KAR")
        oanl = await _deal(
            session, pub_o.id,
            openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/karger-2025-2027",
        )
        oanl.start_year, oanl.end_year = 2025, 2027
        surf = await _deal(session, pub_j.id, esac_id="kar2025surf")
        surf.start_year, surf.end_year = 2025, 2027
        await session.commit()
        oanl_id = oanl.id

    async with maker() as s2:
        stats = await reconcile_deals(s2)
    assert stats["matched"] == 1
    assert stats["consortium_needs_review"] == 1

    async with maker() as s3:
        d = await s3.get(Deal, oanl_id)
        assert d.needs_curation is True
        assert "verify University of Twente participation" in d.needs_curation_reason


async def test_curation_report_lists_unmatched(maker):
    async with maker() as session:
        pub = await _publisher(session, "ACM", slug="acm")
        deal = await _deal(
            session,
            pub.id,
            openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/acm-2026-2028",
        )
        deal.start_year, deal.end_year = 2026, 2028
        jct = await _deal(session, pub.id, esac_id="xyz2020nowhere")
        jct.start_year, jct.end_year = 2020, 2024
        await session.commit()

    async with maker() as s2:
        await reconcile_deals(s2)
        path = await render_curation_report(s2)
    text = path.read_text()
    assert "no matching JCT agreement" in text
    assert "not affiliated with University of Twente" in text  # unmatched JCT row
    path.unlink()


async def test_duplicate_data_guard_purges_cross_publisher(maker):
    """A cross-publisher sheet twin loses its rows; same-publisher twins stay."""
    from journal_browser.harvest.reconcile import enforce_unique_agreement_data
    from journal_browser.models import IssnMap, Journal

    async with maker() as session:
        pub_els = await _publisher(session, "Elsevier")
        pub_eme = await _publisher(session, "Emerald")
        els = await _deal(session, pub_els.id, esac_id="els2025ukb")
        eme = await _deal(session, pub_eme.id, esac_id="eme2025ukb")
        els2 = await _deal(session, pub_els.id, esac_id="els2024vanderbilt")
        for d in (els, eme, els2):
            d.start_year, d.end_year = 2025, 2027
        inst = Institution(
            name="University of Twente",
            ror="https://ror.org/006hf6230",
            code="ut",
            active=True,
        )
        session.add(inst)
        await session.flush()
        session.add(DealInstitution(deal_id=eme.id, institution_id=inst.id))
        issns = [f"{i:04d}-0000" for i in range(60)]
        for target in (els, eme, els2):
            for i, issn in enumerate(issns):
                session.add(
                    DealJournal(
                        deal_id=target.id, issn=issn, journal_name=f"J{i}",
                        source="jct",
                    )
                )
        j = Journal(
            issn_l="0000-0000", title="Elsevier Journal",
            publisher_name="Elsevier",
        )
        session.add(j)
        for issn in issns[:5]:
            session.add(IssnMap(issn=issn, issn_l="0000-0000", source="jct"))
        await session.commit()

    async with maker() as s2:
        actions = await enforce_unique_agreement_data(s2)
    losers = {a["loser"] for a in actions}
    assert losers == {"eme2025ukb"}

    async with maker() as s3:
        for esac, expected in (
            ("els2025ukb", 60), ("els2024vanderbilt", 60), ("eme2025ukb", 0)
        ):
            deal = (await s3.execute(
                select(Deal).where(Deal.esac_id == esac)
            )).scalar_one()
            n = len((await s3.execute(
                select(DealJournal).where(DealJournal.deal_id == deal.id)
            )).all())
            assert n == expected, esac
        flagged = (await s3.execute(
            select(Deal).where(Deal.esac_id == "eme2025ukb")
        )).scalar_one()
        assert flagged.needs_curation is True
        assert "els2025ukb" in flagged.needs_curation_reason or "els2024" in (
            flagged.needs_curation_reason or ""
        )
        # Participation survives a wrong sheet: consortium membership is real.
        links = (await s3.execute(
            select(DealInstitution).where(DealInstitution.deal_id == flagged.id)
        )).scalars().all()
        assert len(links) == 1


async def test_derive_nl_deal_coverage_links_and_covers(maker):
    """openaccess.nl-only deals: participation parsed from conditions text,
    journals from the publisher corpus; non-participating deals untouched."""
    from journal_browser.harvest.reconcile import derive_nl_deal_coverage

    async with maker() as session:
        inst = Institution(
            name="University of Twente",
            ror="https://ror.org/006hf6230",
            code="ut",
            active=True,
        )
        session.add(inst)
        pub_acm = await _publisher(session, "ACM")
        pub_dgb = await _publisher(session, "De Gruyter Brill")
        pub_ign = await _publisher(session, "Unknown Press")
        pub_acs = await _publisher(session, "American Chemical Society (ACS)")
        acm = await _deal(
            session, pub_acm.id,
            openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/acm-2021-2030",
            conditions_text=(
                "License and conditions: ... University of Twente ... (duration 2026-2028)"
            ),
        )
        dgb = await _deal(
            session, pub_dgb.id,
            openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/de-gruyter-brill-2026-2028",
            conditions_text=(
                "Eligible institutions are: University of Amsterdam, VU University Amsterdam"
            ),
        )
        ign = await _deal(
            session, pub_ign.id,
            openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/unknown-2026",
            conditions_text="License and conditions: University of Twente participates",
        )
        acs = await _deal(
            session, pub_acs.id,
            openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/american-chemical-society-acs-2026-2028",
            conditions_text=(
                "The corresponding author must be associated with a participating "
                "Dutch university or organization."
            ),
        )
        for d in (acm, dgb, ign, acs):
            d.start_year, d.end_year = 2026, 2028
        for i, (issn, pname) in enumerate(
            [("0001-0001", "Association for Computing Machinery"),
             ("0002-0002", "Association for Computing Machinery"),
             ("0003-0003", "De Gruyter"),
             ("0004-0004", "American Chemical Society")]
        ):
            session.add(Journal(issn_l=issn, title=f"J{i}", publisher_name=pname))
        await session.commit()
        acm_id, dgb_id, acs_id = acm.id, dgb.id, acs.id

    async with maker() as s2:
        stats = await derive_nl_deal_coverage(s2)
        await s2.commit()
    # named: ACM + Unknown; consortium (no enumeration): ACS; De Gruyter out
    assert stats["linked"] == 3
    assert stats["covered"] == 2  # ACM + ACS resolve; Unknown Press has no corpus

    async with maker() as s3:
        linked = set((await s3.execute(select(DealInstitution.deal_id))).scalars())
        assert acm_id in linked and acs_id in linked and dgb_id not in linked
        rows = (await s3.execute(
            select(DealJournal).where(DealJournal.deal_id == acm_id)
        )).scalars().all()
        assert {r.issn for r in rows} == {"0001-0001", "0002-0002"}
        acs_rows = (await s3.execute(
            select(DealJournal).where(DealJournal.deal_id == acs_id)
        )).scalars().all()
        assert {r.issn for r in acs_rows} == {"0004-0004"}
        assert all(r.source == "publisher-pattern" for r in rows + acs_rows)
        # idempotent: a second derive adds nothing
        stats2 = await derive_nl_deal_coverage(s3)
        await s3.commit()
        assert stats2["pattern_journals"] == 0
