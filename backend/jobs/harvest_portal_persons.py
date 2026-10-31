"""Bind the relay-harvested portal persons listings to pure_persons/
pure_orgs (journal_browser.harvest.pure_portal_persons).

Reads the harvest JSON files (one listing per faculty/institute org,
written through the omp browser relay — the portal caps its persons RSS
at 50 entries and WAF-blocks direct fetches), matches persons and orgs
by normalized display name (an ORCID disambiguation file, fetched from
the portal twin profiles, resolves Pure name twins), full-replaces
pure_person_orgs, and stores the verbatim listings in source_records.

--dry-run matches and reports without writing (DB reads only). Org
relations that neither the exact match, the alias map, nor the
prefix-stripped fallback resolve land in stats[org_unmatched].

uv run python jobs/harvest_portal_persons.py [--institution ut]
    [--dir data/portal-persons] [--orcid-file PATH]
    [--org-alias "BMS-LAB=BMS - Laboratory" ...] [--dry-run]
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from journal_browser.config import get_settings
from journal_browser.harvest.common import resolve_institution, run_harvest
from journal_browser.harvest.pure_portal_persons import (
    PortalListing,
    apply_person_bindings,
    parse_listing,
)
from journal_browser.ingest import IngestSession


def load_listings(directory: Path) -> list[PortalListing]:
    """Every listing JSON in the directory (summaries and the ORCID
    disambiguation file excluded)."""
    listings: list[PortalListing] = []
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith(("summary", "orcid-disambiguation")):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "persons" not in payload:
            continue
        try:
            listings.append(parse_listing(payload))
        except ValueError as error:
            raise SystemExit(f"{path.name}: {error}") from error
    return listings


def load_orcid_map(path: Path) -> dict[str, str]:
    """portal person slug → ORCID, from the disambiguation file."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        row["slug"]: row["orcid"]
        for row in data.get("results", [])
        if row.get("slug") and row.get("orcid")
    }


async def run(
    session,
    institution,
    *,
    directory: Path,
    orcid_file: Path,
    org_aliases: dict[str, str],
    dry_run: bool,
) -> bool:
    # Capture before the dry-run rollback expires the ORM object.
    code = institution.code
    listings = load_listings(directory)
    if not listings:
        print(f"pure-portal persons[{code}]: no listing files in {directory}; nothing to do")
        return True
    orcid_by_slug = load_orcid_map(orcid_file)
    stats: dict = {
        "dir": str(directory),
        "orcid_entries": len(orcid_by_slug),
        "org_aliases": len(org_aliases),
    }
    if dry_run:
        stats.update(
            await apply_person_bindings(
                session,
                institution,
                listings,
                IngestSession(session),
                orcid_by_slug=orcid_by_slug,
                org_aliases=org_aliases,
                store_payloads=False,
            )
        )
        await session.rollback()
    else:
        stats.update(
            await run_harvest(
                "pure-portal",
                "persons",
                f"inst:{code}",
                {
                    "dir": str(directory),
                    "listings": len(listings),
                    "orcid_entries": len(orcid_by_slug),
                    "org_aliases": len(org_aliases),
                },
                lambda ingest: apply_person_bindings(
                    session,
                    institution,
                    listings,
                    ingest,
                    orcid_by_slug=orcid_by_slug,
                    org_aliases=org_aliases,
                ),
                session,
                institution_id=institution.id,
            )
        )
    print(f"pure-portal persons[{code}]: {json.dumps(stats)}")
    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution", default=None, help="institution code (default: env)")
    parser.add_argument(
        "--dir",
        default="data/portal-persons",
        help="directory of harvested listing JSON files (default: data/portal-persons)",
    )
    parser.add_argument(
        "--orcid-file",
        default=None,
        help="ORCID disambiguation JSON (default: <dir>/orcid-disambiguation.json)",
    )
    parser.add_argument(
        "--org-alias",
        action="append",
        default=[],
        metavar="PORTAL NAME=PURE NAME",
        help="curated org-name alias for relations the exact and "
        "prefix-stripped matches miss (repeatable)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="match + report stats without writing (DB reads only)",
    )
    args = parser.parse_args()

    def parse_alias(raw: str) -> tuple[str, str]:
        portal, sep, pure = raw.partition("=")
        if not sep or not portal.strip() or not pure.strip():
            raise SystemExit(f"invalid --org-alias {raw!r}: 'Portal Name=Pure Name' expected")
        return portal.strip(), pure.strip()

    org_aliases = dict(parse_alias(raw) for raw in args.org_alias)

    async def main() -> None:
        directory = Path(args.dir)
        orcid_file = (
            Path(args.orcid_file) if args.orcid_file else (directory / "orcid-disambiguation.json")
        )
        engine = create_async_engine(get_settings().database_url)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            institution = await resolve_institution(session, args.institution)
            await run(
                session,
                institution,
                directory=directory,
                orcid_file=orcid_file,
                org_aliases=org_aliases,
                dry_run=args.dry_run,
            )
        await engine.dispose()

    asyncio.run(main())
