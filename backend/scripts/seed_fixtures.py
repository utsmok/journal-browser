"""Seed a small fixture dataset into the QA database.

Idempotent: every insert checks for an existing row first, so re-running is a
no-op. Schema must already exist (run `alembic upgrade head` first). For CI.

Usage (from backend/):
  JB_DATABASE_URL=postgresql+asyncpg://journal:journal@127.0.0.1:5433/journalbrowser_qa \
  uv run python scripts/seed_fixtures.py

The `embedding` vectors are synthetic 384-dim unit vectors. They make
journal-to-journal similarity meaningful (fixture-to-fixture cosine), but
they do NOT encode topics for the real query-embedding model, so semantic
search rankings against them are not assertable -- see
.factory/skills/qa-backend/SKILL.md flow 6.
"""

import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

DB_URL = os.environ["JB_DATABASE_URL"]


def vec(*head: float) -> list[float]:
    """384-dim unit-ish vector: values in `head` followed by zeros."""
    v = list(head) + [0.0] * (384 - len(head))
    norm = sum(x * x for x in head) ** 0.5
    return [x / norm for x in v] if norm else v


JOURNALS = [
    {
        "issn_l": "1111-1111",
        "title": "Journal of Applied Hydrology",
        "publisher_canonical": "Elsevier",
        "type": "journal",
        "is_oa": True,
        "is_in_doaj": True,
        "doaj_in_doaj": True,
        "doaj_has_apc": True,
        "doaj_apc_max": 2500.0,
        "doaj_apc_currency": "EUR",
        "latest_quartile": "Q1",
        "latest_apc_euro": 2500.0,
        "works_2020_plus": 42,
        "works_count": 900,
        "in_scimago": True,
        "search_text": "Journal of Applied Hydrology",
        "embedding": vec(1.0, 0.05, 0.02),
    },
    {
        "issn_l": "2222-2222",
        "title": "Hydroinformatics Letters",
        "publisher_canonical": "Springer Nature",
        "type": "journal",
        "is_oa": True,
        "is_in_doaj": True,
        "doaj_in_doaj": True,
        "doaj_has_apc": False,
        "latest_quartile": "Q2",
        "works_2020_plus": 17,
        "works_count": 210,
        "in_scimago": True,
        "search_text": "Hydroinformatics Letters",
        "embedding": vec(0.9, 0.35, 0.05),
    },
    {
        "issn_l": "3333-3333",
        "title": "Quarterly Review of Scholarly Publishing",
        "publisher_canonical": "Taylor & Francis",
        "type": "journal",
        "is_oa": False,
        "is_in_doaj": False,
        "doaj_in_doaj": False,
        "doaj_has_apc": False,
        "latest_quartile": "Q2",
        "works_2020_plus": 9,
        "works_count": 130,
        "search_text": "Quarterly Review of Scholarly Publishing",
        "embedding": vec(0.02, 0.05, 1.0),
    },
    {
        "issn_l": "4444-4444",
        "title": "Transactions on Water Modelling",
        "publisher_canonical": "Wiley",
        "type": "journal",
        "is_oa": True,
        "is_in_doaj": False,
        "doaj_in_doaj": None,
        "doaj_has_apc": None,
        "latest_apc_euro": 1800.0,
        "latest_quartile": "Q3",
        "works_2020_plus": 6,
        "works_count": 88,
        "search_text": "Transactions on Water Modelling",
        "embedding": vec(0.85, 0.4, 0.1),
    },
]


async def main() -> None:
    from journal_browser.harvest.common import ensure_home_institution
    from journal_browser.models.app_data import Feedback
    from journal_browser.models.deals import Deal, DealInstitution, DealJournal
    from journal_browser.models.journals import Journal, JournalFlags

    engine = create_async_engine(DB_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        inst = await ensure_home_institution(session)
        await session.commit()
        print(f"institution: {inst.code} ({inst.name}) id={inst.id}")

        for spec in JOURNALS:
            if await session.scalar(select(Journal).where(Journal.issn_l == spec["issn_l"])):
                continue
            session.add(Journal(**spec))
            await session.flush()
            covered = spec["issn_l"] == "1111-1111"
            session.add(
                JournalFlags(
                    institution_id=inst.id,
                    issn_l=spec["issn_l"],
                    works_count=3 if covered else 0,
                    deal_covered=covered,
                    works_window_plus=spec["works_2020_plus"],
                )
            )
            print(f"journal added: {spec['issn_l']} {spec['title']}")
        await session.commit()

        if not await session.scalar(select(Deal).where(Deal.esac_id == "qa-fixture-deal")):
            deal = Deal(
                esac_id="qa-fixture-deal",
                consortium="QA Fixture Consortium",
                status="current",
                start_year=2024,
                end_year=2027,
                duration_text="2024-2027",
                summary="Fixture deal for QA runs.",
                cap_text="Unlimited corresponding-author OA in hybrid journals.",
            )
            session.add(deal)
            await session.flush()
            session.add(
                DealJournal(
                    deal_id=deal.id,
                    issn="1111-1111",
                    issn_l="1111-1111",
                    journal_name="Journal of Applied Hydrology",
                    source="manual",
                )
            )
            session.add(
                DealInstitution(deal_id=deal.id, institution_id=inst.id, participation="named")
            )
            print(f"deal added: {deal.esac_id} id={deal.id}")
        await session.commit()

        n_feedback = len((await session.execute(select(Feedback))).scalars().all())
        print(f"feedback items present: {n_feedback} (QA POSTs create its own)")

    await engine.dispose()
    print("seed complete")


if __name__ == "__main__":
    asyncio.run(main())
