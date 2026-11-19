"""Pure re-harvest keeps the OpenAlex canon OA color (p2 finding 4).

The OpenAlex canon sync is the authoritative oa_status writer for
DOI-matched works; a Pure upsert of a re-seen record must not downgrade
it, and Pure rights only fill works OpenAlex does not know.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from journal_browser.harvest.pure.store import upsert_work
from journal_browser.models import HarvestRun, Institution, OpenalexWork, Work


@pytest.fixture
async def maker(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


def _ea(name: str) -> str:
    """Eprints rights literal the store maps (closedAccess -> closed)."""
    return f"info:eu-repo/semantics/{name}"


def _payload(uuid: str, doi: str | None, rights: str) -> dict:
    return {
        "oai_identifier": f"oai:ris.utwente.nl:publications:{uuid}",
        "dc": {"title": ["A work"], "rights": [rights], "type": ["article"]},
        "doi_normalized": doi,
        "cerif": {},
    }


async def _seed(session) -> int:
    inst = Institution(
        name="University of Twente",
        ror="https://ror.org/006hf6230",
        code="ut",
        active=True,
    )
    session.add(inst)
    session.add(
        HarvestRun(
            source="pure",
            entity_type="work",
            status="completed",
            config_fingerprint="x",
            stats={},
        )
    )
    await session.flush()
    return inst.id


async def _work_color(maker, iid: int) -> str | None:
    """Read the stored color from a fresh session (no identity map)."""
    async with maker() as session:
        work = (await session.execute(select(Work).where(Work.institution_id == iid))).scalar_one()
        return work.oa_status


async def test_reharvest_keeps_canon_oa_color(maker):
    async with maker() as session:
        iid = await _seed(session)
        await upsert_work(
            session,
            _payload("u1", "10.1000/abc", _ea("closedAccess")),
            institution_id=iid,
            year=2024,
            run_id=1,
        )
        await session.commit()
    assert await _work_color(maker, iid) == "closed"

    # The canon sync upgrades the color and OpenAlex carries it.
    async with maker() as session:
        work = (await session.execute(select(Work).where(Work.institution_id == iid))).scalar_one()
        work.oa_status = "gold"
        session.add(
            OpenalexWork(
                institution_id=iid,
                w_id="W1",
                doi_normalized="10.1000/abc",
                oa_status="gold",
            )
        )
        await session.commit()

    # A Pure re-harvest of the same record must not downgrade it.
    async with maker() as session:
        await upsert_work(
            session,
            _payload("u1", "10.1000/abc", _ea("closedAccess")),
            institution_id=iid,
            year=2024,
            run_id=1,
        )
        await session.commit()
    assert await _work_color(maker, iid) == "gold"


async def test_pure_fills_color_without_openalex_row(maker):
    async with maker() as session:
        iid = await _seed(session)
        await upsert_work(
            session,
            _payload("u2", "10.1000/def", _ea("closedAccess")),
            institution_id=iid,
            year=2024,
            run_id=1,
        )
        await session.commit()
    assert await _work_color(maker, iid) == "closed"

    # No OpenAlex row for this DOI: Pure rights remain authoritative and an
    # upgraded rights value lands on the re-seen record.
    async with maker() as session:
        await upsert_work(
            session,
            _payload("u2", "10.1000/def", _ea("openAccess")),
            institution_id=iid,
            year=2024,
            run_id=1,
        )
        await session.commit()
    assert await _work_color(maker, iid) == "green"
