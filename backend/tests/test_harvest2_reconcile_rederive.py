"""Publisher-pattern coverage re-derives on each reconcile (p2 finding 1).

A deal whose list was derived from the publisher pattern must pick up
journals the publisher adds later; hand-curated lists stay frozen.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from journal_browser.models import (
    Deal,
    DealJournal,
    Institution,
    Journal,
    Publisher,
)


@pytest.fixture
async def maker(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


async def _publisher(session, name: str) -> Publisher:
    p = Publisher(name=name)
    session.add(p)
    await session.flush()
    return p


async def _deal(session, publisher_id: int, **kw) -> Deal:
    d = Deal(
        publisher_id=publisher_id,
        status="current",
        corresponding_authors_only=False,
        provenance=[],
        **kw,
    )
    session.add(d)
    await session.flush()
    return d


async def test_pattern_coverage_gains_new_journals(maker):
    from journal_browser.harvest.reconcile import derive_nl_deal_coverage

    async with maker() as session:
        inst = Institution(
            name="University of Twente",
            ror="https://ror.org/006hf6230",
            code="ut",
            active=True,
        )
        session.add(inst)
        pub = await _publisher(session, "Association for Computing Machinery")
        deal = await _deal(
            session,
            pub.id,
            openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/acm-2021-2030",
            conditions_text=(
                "License and conditions: ... University of Twente ... (duration 2026-2028)"
            ),
        )
        for issn in ("0001-0001", "0002-0002"):
            session.add(
                Journal(
                    issn_l=issn,
                    title=f"J{issn}",
                    publisher_name="Association for Computing Machinery",
                )
            )
        await session.commit()
        deal_id = deal.id

    async with maker() as s2:
        stats = await derive_nl_deal_coverage(s2)
        await s2.commit()
    assert stats["covered"] == 1
    assert stats["pattern_journals"] == 2

    # A new journal of the same publisher exists (e.g. ACM TOIS joining the
    # corpus after the first derivation).
    async with maker() as s3:
        s3.add(
            Journal(
                issn_l="0003-0003",
                title="ACM Transactions on Information Systems",
                publisher_name="Association for Computing Machinery",
            )
        )
        await s3.commit()
        stats2 = await derive_nl_deal_coverage(s3)
        await s3.commit()
    assert stats2["pattern_journals"] == 1
    assert stats2["covered"] == 1
    rows = (
        (await s3.execute(select(DealJournal).where(DealJournal.deal_id == deal_id)))
        .scalars()
        .all()
    )
    assert {r.issn for r in rows} == {"0001-0001", "0002-0002", "0003-0003"}

    # A third run with nothing new adds nothing (idempotent).
    async with maker() as s4:
        stats3 = await derive_nl_deal_coverage(s4)
    assert stats3["pattern_journals"] == 0
    assert stats3["covered"] == 0


async def test_manual_coverage_freezes_pattern_derivation(maker):
    from journal_browser.harvest.reconcile import derive_nl_deal_coverage

    async with maker() as session:
        inst = Institution(
            name="University of Twente",
            ror="https://ror.org/006hf6230",
            code="ut",
            active=True,
        )
        session.add(inst)
        pub = await _publisher(session, "Association for Computing Machinery")
        deal = await _deal(
            session,
            pub.id,
            openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/acm-2021-2030",
            conditions_text=(
                "License and conditions: ... University of Twente ... (duration 2026-2028)"
            ),
        )
        session.add(
            Journal(
                issn_l="0001-0001",
                title="J1",
                publisher_name="Association for Computing Machinery",
            )
        )
        await session.commit()
        deal_id = deal.id

    async with maker() as s2:
        await derive_nl_deal_coverage(s2)
        await s2.commit()

    # ManualOverride precedence: a hand-added coverage row freezes the
    # pattern list; pattern rows never join on top of a curated deal.
    async with maker() as s3:
        s3.add(
            DealJournal(
                deal_id=deal_id,
                issn="0009-0009",
                issn_l="0009-0009",
                journal_name="Hand-picked",
                source="manual",
            )
        )
        await s3.commit()
        s3.add(
            Journal(
                issn_l="0004-0004",
                title="J4",
                publisher_name="Association for Computing Machinery",
            )
        )
        await s3.commit()
        stats = await derive_nl_deal_coverage(s3)
        await s3.commit()
    assert stats["pattern_journals"] == 0
    assert stats["covered"] == 0
    rows = (
        (await s3.execute(select(DealJournal).where(DealJournal.deal_id == deal_id)))
        .scalars()
        .all()
    )
    assert {r.issn for r in rows} == {"0001-0001", "0009-0009"}
