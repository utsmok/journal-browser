"""Backfill OpenAlex work-parts data into openalex_works, one GET per DOI.

Works harvested before OpenAlex Graph v12 (2026-11-15) carry no
parent_works in their stored payloads. Every unchecked DOI gets a
single-entity GET ($0 on OpenAlex, measured 2026-11-20) that fills
parent_works/is_part and stamps parts_checked_at, so re-runs skip
checked rows. 404 misses count as checked (standalone); transient fetch
errors leave their rows unchecked for the next run.

After the DOI pass, every distinct parent W-id in the store's
parent_works arrays is registered in openalex_work_parents (title, doi,
type) with one $0 single-entity GET, paced like the DOI pass. 404
parents are skipped (no row); other failures are logged, skipped, and
retried by the next run.

Usage: uv run python jobs/backfill_parts.py
Usage: uv run python jobs/backfill_parts.py --institution rug
Usage: uv run python jobs/backfill_parts.py --limit 100
"""

import asyncio
import json
import logging
import warnings
from typing import Any

from aletheca import AlethecaClient
from sqlalchemy import bindparam, func, select, text
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SAWarning
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from journal_browser.config import get_settings
from journal_browser.harvest.common import (
    normalize_doi,
    openalex_budget_ok,
    paced_single_gets,
    resolve_institution,
)
from journal_browser.harvest.enrich import (
    FETCH_CHUNK,
    GET_MIN_INTERVAL_S,
    fetch_works_by_doi,
)
from journal_browser.models import OpenalexWork, OpenalexWorkParent

logger = logging.getLogger(__name__)

# parent_works entries kept per work (contract cap).
MAX_PARENTS = 10

# Registry rows per upsert statement (asyncpg caps statements at 32,767
# binds; a row has 5 columns).
UPSERT_CHUNK = 2_000

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
    """Contract shape [{id: bare W-id, name: display name, rel: link type}]
    from one aletheca Work's parent_works (ids may be full URLs).
    RelatedWork.link_type parses both the current field name and the
    pre-2026-12-07 relationship name."""
    out: list[dict[str, Any]] = []
    for pw in (getattr(work, "parent_works", None) or [])[:MAX_PARENTS]:
        pid = getattr(pw, "id", None)
        out.append(
            {
                "id": str(pid).rsplit("/", 1)[-1] if pid else None,
                "name": (getattr(pw, "display_name", None) or "").strip() or None,
                "rel": getattr(pw, "link_type", None),
            }
        )
    return out


async def backfill_dois(
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
        if doi is not None:
            institutions_by_doi.setdefault(doi, set()).add(iid)

    client_kwargs: dict[str, Any] = {}
    if api_key := get_settings().openalex_api_key:
        client_kwargs["api_key"] = api_key
    async with AlethecaClient(**client_kwargs) as client:
        dois = sorted(institutions_by_doi)
        for at in range(0, len(dois), FETCH_CHUNK):
            chunk = dois[at : at + FETCH_CHUNK]
            if not await openalex_budget_ok("backfill_parts", stats):
                break
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


async def backfill_parents(session: AsyncSession, institution_id: int | None) -> dict[str, int]:
    """Register every store parent not yet in openalex_work_parents.

    Pending set: distinct (institution, parent W-id) pairs unnested from
    openalex_works.parent_works of the selected institutions, minus
    pairs already registered — so re-runs store nothing. One GET per
    parent W-id: every institution referencing it gets the same upstream
    record. 404 parents store no row (and re-attempt next run — single
    GETs are free); failed lookups log and retry next run, and the pass
    still stores the parents that did come back.
    """
    parents_tv = (
        func.jsonb_array_elements(OpenalexWork.parent_works)
        .table_valued("value", name="parent")
        .render_derived()
    )
    parent_id = parents_tv.c.value.op("->>")("id")
    # The set-returning function in FROM is implicitly lateral in
    # Postgres; SQLAlchemy mistakes it for a cartesian product.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*cartesian product.*", category=SAWarning)
        query = (
            select(OpenalexWork.institution_id, parent_id.label("parent_w_id"))
            .select_from(OpenalexWork, parents_tv)
            .where(parent_id.is_not(None))
            .distinct()
        )
        if institution_id is not None:
            query = query.where(OpenalexWork.institution_id == institution_id)
        referenced = set((await session.execute(query)).all())
    stored: set[tuple[int, str]] = set()
    if referenced:
        stored = set(
            (
                await session.execute(
                    select(
                        OpenalexWorkParent.institution_id,
                        OpenalexWorkParent.parent_w_id,
                    ).where(OpenalexWorkParent.institution_id.in_({i for i, _ in referenced}))
                )
            ).all()
        )
    pending = referenced - stored
    stats = {
        "parents_selected": len(pending),
        "parents_fetched": 0,
        "parents_stored": 0,
        "parents_failed": 0,
    }
    if not pending:
        return stats
    if not await openalex_budget_ok("backfill_parts_parents", stats):
        return stats

    # One GET per parent W-id: every institution holding the parent gets
    # the same upstream record, so no repeated lookups across
    # institutions.
    institutions_by_parent: dict[str, set[int]] = {}
    for iid, pid in pending:
        institutions_by_parent.setdefault(pid, set()).add(iid)

    client_kwargs: dict[str, Any] = {}
    if api_key := get_settings().openalex_api_key:
        client_kwargs["api_key"] = api_key
    async with AlethecaClient(**client_kwargs) as client:
        payloads, failed = await paced_single_gets(
            client.works.get,
            sorted(institutions_by_parent),
            min_interval_s=GET_MIN_INTERVAL_S,
        )
    if failed:
        stats["parents_failed"] = len(failed)
        logger.warning(
            "parts backfill: %d/%d parent lookups failed (first: %r); "
            "skipped, the next run retries them",
            len(failed),
            len(institutions_by_parent),
            next(iter(failed.values())),
        )
    rows = []
    for pid, work in payloads.items():
        if work is None:
            continue  # failed (retried next run) or 404 (no such parent)
        stats["parents_fetched"] += 1
        values = {
            "doi_normalized": normalize_doi(getattr(work, "doi", None)),
            "title": (getattr(work, "display_name", None) or "").strip() or None,
            "work_type": getattr(work, "type", None),
        }
        for iid in sorted(institutions_by_parent[pid]):
            rows.append({"institution_id": iid, "parent_w_id": pid, **values})
            stats["parents_stored"] += 1
    for at in range(0, len(rows), UPSERT_CHUNK):
        stmt = pg_insert(OpenalexWorkParent.__table__).values(rows[at : at + UPSERT_CHUNK])
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    OpenalexWorkParent.institution_id,
                    OpenalexWorkParent.parent_w_id,
                ],
                set_={
                    "doi_normalized": stmt.excluded.doi_normalized,
                    "title": stmt.excluded.title,
                    "work_type": stmt.excluded.work_type,
                    "updated_at": text("now()"),
                },
            )
        )
    if rows:
        await session.commit()
    return stats


async def backfill_parts(
    session: AsyncSession, institution_id: int | None, limit: int | None
) -> dict[str, int]:
    """One run: the per-DOI parts backfill, then the parent registry pass
    (always — it no-ops when every parent is registered)."""
    stats = await backfill_dois(session, institution_id, limit)
    stats.update(await backfill_parents(session, institution_id))
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
