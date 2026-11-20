"""Restore the owner-curation provenance entries wiped by the 2026-11-19
JCT ingest (the ingest itself is fixed in 84af7a2: it merges per source).

The 2026-10-22 owner curation (5271f17, jobs/apply_curation_2026_10_22.py)
stamped one provenance pointer onto all 16 Twente deals. The pre-fix JCT
ingest replaced deals.provenance wholesale and dropped that pointer from 11
of them. The deals that kept the entry (1, 1715) show the exact bytes to
restore. Deal 48's openaccess.nl entry was wiped too, but the openaccess.nl
harvest re-created it fresher on 2026-11-20; the merge below never touches a
source that already has an entry, so that newer entry is left alone.

Idempotent: a deal that already has any owner_curation provenance entry is
never duplicated or overwritten.

Live write approved by the owner for exactly this restoration:
    docker exec journal-browser-backend-1 uv run --no-dev \
        python scripts/restore_deal_curation.py
"""

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.models import Deal

# The uniform pointer 5271f17 appended to every Twente deal, byte-identical
# to the entries that survived on deals 1 and 1715.
RESTORED_ENTRY: dict[str, Any] = {
    "source": "owner_curation",
    "date": "2026-10-22",
    "doc": "docs/research/openaccess-nl-current-deals-2026-10-22.json",
}

# Deal ids whose owner_curation pointer the 2026-11-19T22:45 UTC JCT run wiped.
DEAL_IDS = [2, 11, 21, 39, 42, 43, 48, 53, 57, 66, 363]


def merge_curation_provenance(
    existing: list[Any] | None,
    restored: dict[str, Any] = RESTORED_ENTRY,
) -> tuple[list[Any], bool]:
    """Return (provenance, changed): append `restored` only when no entry of
    the same source exists yet. A same-source entry is never duplicated or
    overwritten, so any owner curation newer than this restoration wins by
    simply being present."""
    entries = list(existing or [])
    for entry in entries:
        if isinstance(entry, dict) and entry.get("source") == restored["source"]:
            return entries, False
    return [*entries, dict(restored)], True


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    restored = 0
    async with maker() as session:
        for deal_id in DEAL_IDS:
            deal = await session.get(Deal, deal_id)
            if deal is None:
                print(f"deal {deal_id}: missing, skipped")
                continue
            provenance, did = merge_curation_provenance(deal.provenance)
            if did:
                deal.provenance = provenance
                restored += 1
            print(f"deal {deal_id}: {'restored' if did else 'owner_curation already present'}")
        await session.commit()
    await engine.dispose()
    print(f"{restored}/{len(DEAL_IDS)} deals restored")


if __name__ == "__main__":
    asyncio.run(main())
