"""Reconcile openaccess.nl deals with JCT agreements + curation report.

Usage: uv run python jobs/reconcile.py [--institution CODE]

--institution scopes the run to that institution's layer: participation
derivation + its coverage flags, without the global deal merging.
"""

import argparse
import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import (
    get_active_institutions,
    resolve_institution,
)
from journal_browser.harvest.denorm import refresh_deal_flags
from journal_browser.harvest.reconcile import (
    derive_nl_deal_coverage,
    enforce_unique_agreement_data,
    reconcile_deals,
    render_curation_report,
)


async def main(institution: str | None) -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        if institution is not None:
            # Onboarding path (bootstrap --institution CODE): derive this
            # deal register's participation and refresh coverage flags.
            inst = await resolve_institution(session, institution)
            stats = await derive_nl_deal_coverage(session)
            await refresh_deal_flags(session, inst.id)
            await session.commit()
            print(json.dumps(stats))
            await engine.dispose()
            return
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--institution",
        default=None,
        help="institution code: participation + coverage flags only",
    )
    args = parser.parse_args()
    asyncio.run(main(args.institution))
