"""Reconcile openaccess.nl deals with JCT agreements + curation report.

Usage: uv run python jobs/reconcile.py
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import get_active_institutions
from journal_browser.harvest.denorm import refresh_deal_flags
from journal_browser.harvest.reconcile import (
    enforce_unique_agreement_data,
    reconcile_deals,
    render_curation_report,
)


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        stats = await reconcile_deals(session)
        actions = await enforce_unique_agreement_data(session)
        # Linkage/merges above can change per-institution coverage; keep
        # every hosted institution's search flags consistent.
        for inst in await get_active_institutions(session):
            await refresh_deal_flags(session, inst.id)
        await session.commit()
        report = await render_curation_report(session, actions)
    await engine.dispose()
    print(json.dumps(stats))
    if actions:
        print(json.dumps({"duplicate_data_guard": actions}, indent=1))
    print(f"curation report: {report}")


if __name__ == "__main__":
    asyncio.run(main())
