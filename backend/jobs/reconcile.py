"""Reconcile openaccess.nl deals with JCT agreements + curation report.

Usage: uv run python jobs/reconcile.py
"""

import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
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
        report = await render_curation_report(session, actions)
    await engine.dispose()
    print(json.dumps(stats))
    if actions:
        print(json.dumps({"duplicate_data_guard": actions}, indent=1))
    print(f"curation report: {report}")


if __name__ == "__main__":
    asyncio.run(main())
