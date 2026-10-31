"""Pure portal persons listings (research.utwente.nl): the non-OAI
person→org binding source.

The portal caps each org's persons RSS feed at 50 entries, but the HTML
persons listings paginate fully; they were relay-harvested through the
owner's browser into JSON files (data/portal-persons/), one listing per
faculty or institute org, each person with slug, display name, org
relations (slug, name, role), and the staff-type text.

Bind contract (mirrors the org-tree walk):
- gap-fill evidence only: bindings live in pure_person_orgs and reach
  the derive pipeline through dedicated portal arms — native CERIF
  resolution, the roster, and ROR confirmation are never overridden;
- persons match pure_persons by normalized display name (diacritics
  folded, credential suffixes after a comma dropped, token order free);
  ambiguous names (Pure name twins) are skipped unless the ORCID
  disambiguation file names their portal slug;
- orgs match pure_orgs by the org-tree walk's name_key, then a curated
  alias map (--org-alias), then a prefix-stripped fallback (the OAI
  tree names some departments bare where the portal prefixes them, e.g.
  "Geosciences" vs "Department of Geosciences"); each level must be
  unambiguous — duplicate-name twins are skipped;
- verbatim listing payloads land in source_records (source
  'pure-portal', entity_type 'persons') keyed by listing slug;
- the table is wholly portal-derived: apply full-replaces it per
  institution, so re-running a rebuilt dataset is idempotent.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ingest import IngestSession
from ..models import Institution, PurePerson, PurePersonOrg
from .org_closure import load_org_tree
from .pure_portal import name_key

logger = logging.getLogger(__name__)

#: Leading unit-kind phrases the OAI tree sometimes drops from display
#: names (and the portal keeps) — stripped for the fallback match.
_ORG_PREFIXES = (
    "department of ",
    "faculty of ",
    "institute of ",
    "school of ",
    "centre for ",
    "center for ",
)


def person_name_key(name: str | None) -> str:
    """Match key for portal ↔ pure_persons display names: fold diacritics,
    drop credential suffixes after a comma ("Geert A. Folkertsma, CEng"
    and "Jan de Jong, PDEng" would otherwise never match), tokenize.
    Matchers also try the reversed token order — Pure and the portal
    disagree on first/last ordering occasionally."""
    folded = unicodedata.normalize("NFKD", name or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c)).casefold()
    if "," in folded:
        folded = folded.split(",", 1)[0]
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", folded)).strip()


def person_name_keys(name: str | None) -> tuple[str, str]:
    """Both match keys for a name: as-is and reversed token order."""
    tokens = person_name_key(name).split()
    return " ".join(tokens), " ".join(reversed(tokens))


def org_bare_key(name: str | None) -> str:
    """name_key with any leading unit-kind phrase dropped, so the
    portal's "Department of Geosciences" and the OAI-treed bare
    "Geosciences" land on the same fallback key."""
    stripped = (name or "").strip()
    folded = stripped.casefold()
    for prefix in _ORG_PREFIXES:
        if folded.startswith(prefix):
            return name_key(stripped[len(prefix) :])
    return name_key(name)


def match_org_name(
    org_name: str,
    org_aliases: dict[str, str],
    org_candidates: dict[str, list[str]],
    org_candidates_bare: dict[str, list[str]],
) -> list[str]:
    """Org uuids for one portal relation name: curated alias → exact
    name_key → prefix-stripped fallback. An ambiguous exact level stays
    ambiguous (no fallback dodge); only the empty fallback level falls
    through."""
    pure_name = org_aliases.get(org_name, org_name)
    uuids = org_candidates.get(name_key(pure_name), [])
    if uuids:
        return uuids
    return org_candidates_bare.get(org_bare_key(pure_name), [])


@dataclass
class PortalListing:
    """One harvested listing file (a faculty or institute org)."""

    org_slug: str
    label: str
    unit_kind: str
    listing_url: str | None
    payload: dict[str, Any]


def parse_listing(payload: dict[str, Any]) -> PortalListing:
    """Validate one listing JSON into a PortalListing."""
    org_slug = payload.get("org_slug")
    persons = payload.get("persons")
    if not org_slug or not isinstance(persons, list):
        raise ValueError("listing JSON needs org_slug and a persons list")
    return PortalListing(
        org_slug=org_slug,
        label=payload.get("faculty") or org_slug,
        unit_kind=payload.get("unit_kind") or "faculty",
        listing_url=payload.get("listing_url"),
        payload=payload,
    )


async def apply_person_bindings(
    session: AsyncSession,
    institution: Institution,
    listings: list[PortalListing],
    ingest: IngestSession,
    *,
    orcid_by_slug: dict[str, str] | None = None,
    org_aliases: dict[str, str] | None = None,
    store_payloads: bool = True,
) -> dict[str, int]:
    """Match the listings against pure_persons/pure_orgs and full-replace
    pure_person_orgs per the module contract; returns per-step stats.
    Listing payloads land in source_records."""
    orcid_by_slug = orcid_by_slug or {}
    org_aliases = org_aliases or {}

    # pure_persons candidates: both token orders → {uuid: orcid}.
    candidates: dict[str, dict[str, str | None]] = {}
    for row in (
        await session.execute(select(PurePerson).where(PurePerson.institution_id == institution.id))
    ).scalars():
        for key in person_name_keys(row.name):
            if key:
                candidates.setdefault(key, {})[row.uuid] = row.orcid

    # pure_orgs candidates: the org-tree walk's name_key → uuids, plus
    # the prefix-stripped fallback index.
    tree = await load_org_tree(session, institution)
    org_candidates: dict[str, list[str]] = {}
    org_candidates_bare: dict[str, list[str]] = {}
    for uuid, org in tree.orgs.items():
        org_candidates.setdefault(name_key(org.name), []).append(uuid)
        org_candidates_bare.setdefault(org_bare_key(org.name), []).append(uuid)

    stats = {
        "listings": len(listings),
        "person_records": 0,
        "persons_matched": 0,
        "orcid_resolved": 0,
        "persons_ambiguous": 0,
        "persons_unmatched": 0,
        "relations_seen": 0,
        "org_name_missing": 0,
        "org_ambiguous": 0,
        "org_unmatched": 0,
        "edges": 0,
    }

    # (person_uuid, org_uuid) → binding: later listings overwrite the
    # role text and accumulate listing kinds.
    edges: dict[tuple[str, str], PurePersonOrg] = {}
    matched_persons: set[str] = set()

    for listing in listings:
        for person in listing.payload["persons"]:
            stats["person_records"] += 1
            slug = person.get("slug") or ""
            name = person.get("name") or ""
            primary, reversed_key = person_name_keys(name)
            pool = candidates.get(primary) or candidates.get(reversed_key) or {}
            person_uuid: str | None = None
            if len(pool) > 1:
                orcid = orcid_by_slug.get(slug)
                if orcid:
                    person_uuid = next((u for u, o in pool.items() if o == orcid), None)
                    if person_uuid is not None and person_uuid not in matched_persons:
                        stats["orcid_resolved"] += 1
                if person_uuid is None:
                    stats["persons_ambiguous"] += 1
                    logger.info("pure-portal persons: ambiguous name %r (%s)", name, slug)
                    continue
            elif len(pool) == 1:
                person_uuid = next(iter(pool))
            else:
                stats["persons_unmatched"] += 1
                logger.info("pure-portal persons: unmatched %r (%s)", name, slug)
                continue
            matched_persons.add(person_uuid)
            for relation in person.get("orgs") or []:
                stats["relations_seen"] += 1
                org_name = (relation.get("name") or "").strip()
                if not org_name:
                    stats["org_name_missing"] += 1
                    continue
                org_uuids = match_org_name(
                    org_name, org_aliases, org_candidates, org_candidates_bare
                )
                if len(org_uuids) > 1:
                    stats["org_ambiguous"] += 1
                    continue
                if not org_uuids:
                    stats["org_unmatched"] += 1
                    logger.info("pure-portal persons: unmatched org %r", org_name)
                    continue
                org_uuid = org_uuids[0]
                role = relation.get("role")
                edge = edges.get((person_uuid, org_uuid))
                if edge is None:
                    edges[(person_uuid, org_uuid)] = PurePersonOrg(
                        institution_id=institution.id,
                        person_uuid=person_uuid,
                        org_uuid=org_uuid,
                        role=role,
                        portal_person_slug=slug,
                        portal_org_slug=relation.get("slug") or "",
                        listing_kinds=[listing.unit_kind],
                    )
                else:
                    if role:
                        edge.role = role
                    if listing.unit_kind not in edge.listing_kinds:
                        edge.listing_kinds.append(listing.unit_kind)
    stats["persons_matched"] = len(matched_persons)
    stats["edges"] = len(edges)

    # Full-replace: the table is wholly portal-derived.
    await session.execute(
        delete(PurePersonOrg).where(PurePersonOrg.institution_id == institution.id)
    )
    if edges:
        session.add_all(edges.values())
    if store_payloads:
        await ingest.ingest_records([(listing.org_slug, listing.payload) for listing in listings])
    return stats
