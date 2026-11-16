"""Backfill OpenAlex work-parts data into openalex_works, one GET per DOI.

Works harvested before OpenAlex Graph v12 (2026-11-15) carry no
parent_works in their stored payloads. Every unchecked DOI gets a
single-entity GET (free under OpenAlex credit pricing) that fills
parent_works/is_part and stamps parts_checked_at, so re-runs skip
checked rows. 404 misses count as checked (standalone); transient fetch
errors leave their rows unchecked for the next run.

Usage: uv run python jobs/backfill_parts.py
Usage: uv run python jobs/backfill_parts.py --institution rug
Usage: uv run python jobs/backfill_parts.py --limit 100
"""

import asyncio
import json
import logging
from typing import Any

from aletheca import AlethecaClient
from sqlalchemy import bindparam, func, select
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from journal_browser.config import get_settings
from journal_browser.harvest.common import resolve_institution
from journal_browser.harvest.enrich import FETCH_CHUNK, fetch_works_by_doi
from journal_browser.models import OpenalexWork

logger = logging.getLogger(__name__)

# parent_works entries kept per work (contract cap).
MAX_PARENTS = 10

# One executemany UPDATE per fetched chunk: fetched parent data for
# matched DOIs, empty standalone facts for 404 misses — both stamped
# checked. Core table form: through an ORM session, an entity update
# with a parameter list would demand per-row primary keys. The IS NULL
# guard keeps concurrent runs from double-marking.
_WORKS = OpenalexWork.__table__
MARK_CHECKED = (
    sa_update(_WORKS)
    .where(
        _WORKS.c.institution_id == bindparam("inst_id"),
        _WORKS.c.doi_normalized == bindparam("doi"),
        _WORKS.c.parts_checked_at.is_(None),
    )
    .values(
        parent_works=bindparam("parents", type_=JSONB),
        is_part=bindparam("is_part"),
        parts_checked_at=func.now(),
    )
)


def _compact_parents(work: Any) -> list[dict[str, Any]]:
    """Contract shape [{id: bare W-id, name: display name, rel: relationship}]
    from one aletheca Work's parent_works (ids may be full URLs)."""
    out: list[dict[str, Any]] = []
    for pw in (getattr(work, "parent_works", None) or [])[:MAX_PARENTS]:
        pid = getattr(pw, "id", None)
        out.append(
            {
                "id": str(pid).rsplit("/", 1)[-1] if pid else None,
                "name": (getattr(pw, "display_name", None) or "").strip() or None,
                "rel": getattr(pw, "relationship", None),
            }
        )
    return out


async def backfill_parts(
    session: AsyncSession, institution_id: int | None, limit: int | None
) -> dict[str, int]:
    """Check every unchecked DOI row against live OpenAlex (idempotent via
    parts_checked_at); rows match on (institution_id, doi_normalized)."""
    query = (
        select(OpenalexWork.institution_id, OpenalexWork.doi_normalized)
        .where(
            OpenalexWork.doi_normalized.is_not(None),
            OpenalexWork.parts_checked_at.is_(None),
        )
        .distinct()
    )
    if institution_id is not None:
        query = query.where(OpenalexWork.institution_id == institution_id)
    if limit is not None:
        query = query.limit(limit)
    pending = list((await session.execute(query)).all())
    stats = {"selected": len(pending), "fetched": 0, "matched": 0, "checked": 0}
    if not pending:
        return stats

    # One GET per unique DOI: every institution holding the DOI gets the
    # same upstream record, so no repeated lookups across institutions.
    institutions_by_doi: dict[str, set[int]] = {}
    for iid, doi in pending:
        institutions_by_doi.setdefault(doi, set()).add(iid)

    client_kwargs: dict[str, Any] = {}
    if api_key := get_settings().openalex_api_key:
        client_kwargs["api_key"] = api_key
    async with AlethecaClient(**client_kwargs) as client:
        dois = sorted(institutions_by_doi)
        for at in range(0, len(dois), FETCH_CHUNK):
            chunk = dois[at : at + FETCH_CHUNK]
            found, errored, first_error = await fetch_works_by_doi(client, chunk, stats)
            if errored:
                logger.warning(
                    "parts backfill: %d/%d DOI lookups failed this chunk (first: %r); "
                    "affected rows stay unchecked for the next run",
                    len(errored),
                    len(chunk),
                    first_error,
                )
            updates = []
            for doi in chunk:
                if doi in errored:
                    continue
                work = found.get(doi)
                parents = _compact_parents(work) if work is not None else []
                stats["fetched"] += 1
                stats["checked"] += len(institutions_by_doi[doi])
                if work is not None:
                    stats["matched"] += len(institutions_by_doi[doi])
                for iid in sorted(institutions_by_doi[doi]):
                    updates.append(
                        {
                            "inst_id": iid,
                            "doi": doi,
                            "parents": parents,
                            "is_part": bool(parents),
                        }
                    )
            if updates:
                await session.execute(MARK_CHECKED, updates)
                await session.commit()
    return stats


async def main(session: AsyncSession, institution_id: int | None, limit: int | None) -> None:
    print(json.dumps(await backfill_parts(session, institution_id, limit), indent=1))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution", default=None, help="institution code (default: all)")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    async def run() -> None:
        engine = create_async_engine(get_settings().database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            inst = (
                await resolve_institution(session, args.institution) if args.institution else None
            )
            await main(session, inst.id if inst else None, args.limit)
        await engine.dispose()

    asyncio.run(run())
