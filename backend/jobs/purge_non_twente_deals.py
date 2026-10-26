"""Delete every deal without a home deal_institutions link.

The register is exactly the owner-verified Twente deals (owner decision
2026-10-23); other rows came from the retired JCT/openaccess.nl harvesters
and are re-derivable from the landing zone if ever needed. Idempotent.

Usage: uv run python jobs/purge_non_twente_deals.py
"""

import asyncio

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.denorm import refresh_deal_flags
from journal_browser.models import Deal, DealInstitution, DealJournal, Institution


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        home_id = await session.scalar(
            select(Institution.id).where(Institution.is_default.is_(True))
        )
        if home_id is None:
            raise SystemExit("no default institution; refusing to purge")
        home_rows = await session.execute(
            select(DealInstitution.deal_id).where(DealInstitution.institution_id == home_id)
        )
        keep = {d for (d,) in home_rows}
        if not keep:
            raise SystemExit("no home-linked deals found; refusing to purge everything")
        all_ids = set((await session.execute(select(Deal.id))).scalars())
        doomed = all_ids - keep
        for deal_id in sorted(doomed):
            await session.execute(delete(DealJournal).where(DealJournal.deal_id == deal_id))
            await session.execute(delete(DealInstitution).where(DealInstitution.deal_id == deal_id))
            await session.execute(delete(Deal).where(Deal.id == deal_id))
        await refresh_deal_flags(session, home_id)
        await session.commit()
    await engine.dispose()
    print(f"kept={len(keep)} purged={len(doomed)}")


if __name__ == "__main__":
    asyncio.run(main())
