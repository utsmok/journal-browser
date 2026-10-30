"""One-shot import: ut-metadata canonical works -> this deployment's works.

Reads the external canonical-works Postgres (institution.external_works_dsn,
falling back to the global JB_UT_METADATA_DSN) and upserts every canonical
work that maps to a Pure uuid (pure_item_population) into the local `works`
table — the full corpus without re-harvesting Pure. Canonical works without
a Pure uuid (OpenAlex-inferred additions) cannot key `works` and stay out;
they still surface on journal pages through the live ut-metadata merge.

Per run it also refreshes pure_canon stats + journal_flags and widens the
institution's data window down to the oldest stored work. Idempotent:
re-running refreshes fields and bookkeeping, never duplicates.

Usage: uv run --no-dev python jobs/import_utmetadata_works.py [--institution ut]
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import resolve_institution
from journal_browser.harvest.denorm import refresh_institution_stats
from journal_browser.harvest.institution_stats import write_pure_canon_stats
from journal_browser.harvest.pure import _norm_title
from journal_browser.ingest import IngestSession
from journal_browser.models import Institution, Journal, Work
from journal_browser.services.ut_metadata import _get_engine, normalize_doi

BATCH = 1000

# Same join shape as the live per-journal merge (services/ut_metadata.py):
# work_venues.source_s_id resolves through source_identity to the canonical
# venue, whose issn_l is the OpenAlex ISSN-L.
CANON_WORKS_SQL = """
SELECT pop.uuid AS pure_uuid,
       w.id AS work_id,
       coalesce(m.title, m.canonical_display_name, w.display_name) AS title,
       coalesce(m.publication_year, w.publication_year) AS year,
       coalesce(m.work_type, w.work_type) AS work_type,
       coalesce(m.doi, w.doi) AS doi,
       m.oa_status, m.publisher
FROM pure_item_population pop
JOIN work w ON w.id = pop.canonical_id
LEFT JOIN merged_work_attrs m ON m.canonical_id = w.id
"""
VENUES_SQL = """
SELECT wv.work_id, lower(v.issn_l) AS issn_l
FROM venue v
JOIN source_identity si ON si.canonical_id = v.id AND si.entity_type = 'venues'
JOIN work_venues wv ON wv.source_s_id = lower(si.source_pk)
ORDER BY wv.work_id, v.issn_l
"""


def resolve_dsn(institution: Institution) -> str | None:
    """Per-institution DSN first, global ut-metadata setting as fallback."""
    return institution.external_works_dsn or get_settings().ut_metadata_dsn or None


async def main(code: str) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        institution = await resolve_institution(session, code)
        dsn = resolve_dsn(institution)
        if not dsn:
            raise SystemExit(f"no ut-metadata DSN for {institution.code}; set it first")
        ingest = IngestSession(session)
        await ingest.start_run(
            "ut-metadata",
            "work",
            f"inst:{institution.code}",
            {"source": "ut-metadata import"},
            institution_id=institution.id,
        )
        stats = await import_works(session, institution, dsn, ingest.run_id)
        final = await ingest.finish_run("completed", stats)
        await ingest.commit()

        # Oldest stored work becomes the new window start (never raises it).
        min_year = (
            await session.execute(
                select(func.min(Work.year)).where(
                    Work.institution_id == institution.id, Work.retired_at.is_(None)
                )
            )
        ).scalar()
        if min_year is not None and min_year < institution.data_window_start:
            final["window_start"] = [institution.data_window_start, min_year]
            institution.data_window_start = min_year
        final["pure_canon_rows"] = await write_pure_canon_stats(session, institution)
        await refresh_institution_stats(session, institution)
        await session.commit()
    await engine.dispose()
    print(json.dumps(final))


async def import_works(
    session: AsyncSession, institution: Institution, dsn: str, run_id: int
) -> dict:
    iid = institution.id
    async with _get_engine(dsn).connect() as ext:
        canon = (await ext.exec_driver_sql(CANON_WORKS_SQL)).mappings().all()
        # work_id -> first (alphabetically) venue issn_l per canonical work.
        venues: dict[int, str] = {}
        for work_id, issn_l in await ext.exec_driver_sql(VENUES_SQL):
            venues.setdefault(work_id, issn_l)

    # Journal link target: upper-cased issn_l -> the stored journals form.
    journals_by_upper = {
        issn_l.upper(): issn_l for (issn_l,) in (await session.execute(select(Journal.issn_l)))
    }
    # DOIs already claimed locally (the stored 2020+ corpus keeps priority).
    claimed: dict[str, str] = {
        doi: uuid
        for doi, uuid in (
            await session.execute(
                select(Work.doi_normalized, Work.pure_uuid).where(Work.institution_id == iid)
            )
        )
        if doi
    }
    known_uuids = set(
        await session.scalars(select(Work.pure_uuid).where(Work.institution_id == iid))
    )

    stats: dict = {
        "external_uuids": len(canon),
        "skipped_no_year": 0,
        "doi_conflicts": 0,
        "journal_resolved": 0,
        "journal_missing": 0,
    }
    rows: list[dict] = []
    for rec in sorted(canon, key=lambda r: r["pure_uuid"]):
        year = rec["year"]
        title = rec["title"]
        if year is None or not title:
            stats["skipped_no_year"] += 1
            continue
        doi = normalize_doi(rec["doi"])
        if doi and claimed.get(doi, rec["pure_uuid"]) != rec["pure_uuid"]:
            # Twin pure uuid (or a stale DOI): store without DOI, like the
            # Pure harvester's duplicate-DOI rule.
            doi = None
            stats["doi_conflicts"] += 1
        elif doi:
            claimed[doi] = rec["pure_uuid"]
        issn_l = None
        if venue_issn := venues.get(rec["work_id"]):
            if venue_issn.upper() in journals_by_upper:
                issn_l = journals_by_upper[venue_issn.upper()]
                stats["journal_resolved"] += 1
            else:
                stats["journal_missing"] += 1
        rows.append(
            {
                "institution_id": iid,
                "pure_uuid": rec["pure_uuid"],
                "doi_normalized": doi,
                "title": title,
                "norm_title": _norm_title(title),
                "year": year,
                "work_type": rec["work_type"],
                "publisher": rec["publisher"],
                "oa_status": rec["oa_status"],
                "journal_issn_l": issn_l,
                "first_seen_run": run_id,
                "last_seen_run": run_id,
            }
        )

    inserted = updated = 0
    for start in range(0, len(rows), BATCH):
        batch = rows[start : start + BATCH]
        stmt = pg_insert(Work).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Work.institution_id, Work.pure_uuid],
            set_={
                # DOI/publisher/OA/journal: import fills, never clobbers.
                "doi_normalized": func.coalesce(stmt.excluded.doi_normalized, Work.doi_normalized),
                "title": stmt.excluded.title,
                "norm_title": stmt.excluded.norm_title,
                "year": stmt.excluded.year,
                "work_type": stmt.excluded.work_type,
                "publisher": func.coalesce(stmt.excluded.publisher, Work.publisher),
                "oa_status": func.coalesce(stmt.excluded.oa_status, Work.oa_status),
                "journal_issn_l": func.coalesce(Work.journal_issn_l, stmt.excluded.journal_issn_l),
                "last_seen_run": run_id,
                "retired_at": None,
                "updated_at": datetime.now(UTC),
            },
        )
        await session.execute(stmt)
        inserted += sum(1 for r in batch if r["pure_uuid"] not in known_uuids)
        updated += sum(1 for r in batch if r["pure_uuid"] in known_uuids)
    stats["inserted"] = inserted
    stats["updated"] = updated
    stats["rows"] = len(rows)
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution", default="ut", help="institution code")
    args = parser.parse_args()
    asyncio.run(main(args.institution))
