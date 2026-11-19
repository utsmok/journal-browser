"""Bulk-review work_identity rows from the command line.

Applies one decision (confirmed or missing) to every row matching the
selection filters, through the same audited apply_decision the admin API
uses, and prints a JSON summary. Deploy-time use: auto-confirm the safe
band (confidence >= 0.99 and a normalised title of 25+ chars):

uv run python jobs/oneoff/bulk_work_identity.py --decisions confirmed \
    --reviewer deploy --min-confidence 0.99 --min-title-len 25

Preview counts without writing anything:

uv run python jobs/oneoff/bulk_work_identity.py --decisions missing \
    --reviewer deploy --max-confidence 0.9 --dry-run
"""

import argparse
import asyncio
import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import resolve_institution
from journal_browser.models import Work, WorkIdentity
from journal_browser.routers.admin.work_identity_admin import (
    WORK_IDENTITY_STATUSES,
    apply_decision,
)


async def main(session, inst_id: int, args: argparse.Namespace) -> dict:
    query = select(WorkIdentity).where(WorkIdentity.institution_id == inst_id)
    if args.status_filter:
        query = query.where(WorkIdentity.status == args.status_filter)
    if args.source:
        query = query.where(WorkIdentity.source == args.source)
    if args.min_confidence is not None:
        query = query.where(WorkIdentity.confidence >= args.min_confidence)
    if args.max_confidence is not None:
        query = query.where(WorkIdentity.confidence <= args.max_confidence)
    if args.min_title_len is not None:
        query = query.join(
            Work,
            (Work.institution_id == WorkIdentity.institution_id)
            & (Work.pure_uuid == WorkIdentity.work_id),
        ).where(func.length(Work.norm_title) >= args.min_title_len)
    query = query.order_by(WorkIdentity.id)
    if args.limit is not None:
        query = query.limit(args.limit)
    rows = (await session.execute(query)).scalars().all()

    summary: dict = {
        "institution_id": inst_id,
        "selected": len(rows),
        "confirmed": 0,
        "missing": 0,
        "reopened": 0,
        "unchanged": 0,
        "errors": [],
        "dry_run": args.dry_run,
    }
    for row in rows:
        if args.dry_run:
            # --decisions only allows confirmed/missing, so a row already
            # in the target status is the only 'unchanged' case.
            summary["unchanged" if row.status == args.decisions else args.decisions] += 1
            continue
        try:
            outcome = await apply_decision(
                session,
                institution_id=row.institution_id,
                source=row.source,
                source_pk=row.source_pk,
                status=args.decisions,
                note=None,
                reviewer=args.reviewer,
            )
        except ValueError as exc:
            summary["errors"].append({"source_pk": row.source_pk, "error": str(exc)})
            continue
        summary[outcome] += 1
    if not args.dry_run:
        await session.commit()
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution", default=None, help="institution code (default: env home)")
    parser.add_argument("--source", default=None, help="only rows from this source, e.g. openalex")
    parser.add_argument(
        "--status-filter",
        default="candidate",
        choices=list(WORK_IDENTITY_STATUSES),
        help="only rows currently in this status (default: candidate)",
    )
    parser.add_argument("--min-confidence", type=float, default=None)
    parser.add_argument("--max-confidence", type=float, default=None)
    parser.add_argument(
        "--min-title-len",
        type=int,
        default=None,
        help="minimum length of the work's normalised title",
    )
    parser.add_argument(
        "--decisions",
        required=True,
        choices=["confirmed", "missing"],
        help="status to apply to every selected row",
    )
    parser.add_argument("--reviewer", required=True, help="name recorded in the audit log")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--dry-run", action="store_true", help="tally what would change, write nothing"
    )
    args = parser.parse_args()

    async def run() -> None:
        engine = create_async_engine(get_settings().database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            inst = await resolve_institution(session, args.institution)
            print(json.dumps(await main(session, inst.id, args), indent=1, default=str))
        await engine.dispose()

    asyncio.run(run())
