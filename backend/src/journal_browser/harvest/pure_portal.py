"""Pure research-portal org tree (research.utwente.nl): the non-OAI
hierarchy source.

The Pure OAI orgunits snapshot misses parent edges for some units (the
flat-org gap: Stochastic Operations Research, Discrete Mathematics and
Mathematical Programming, Databases, ... — their chains never reach a
faculty, so their people resolve no faculty and are only rostered via
the weak-affiliation rung). The public portal's organisations index RSS
carries every research unit with its parent organisation link and a type
classification in one paginated feed.

Harvest contract:
- fill parent edges only for orgs that have none (OAI edges are never
  overridden);
- upgrade org_type only for UT-side orgs (no parent row, or already
  closure-connected to the root) — partner orgs keep their own types;
- keep institutes pinned to the root (owner ruling: MESA+ Institute,
  TechMed Centre, Digital Society Institute are separate from faculties,
  whatever a future portal layout or OAI snapshot says);
- skip closed units that only name a successor (their faculty is a
  historical guess);
- never demote an institute type (the ruling is ours, the portal's
  wording may change).

Verbatim feed payloads land in source_records (source 'pure-portal',
entity_type 'organisations') keyed by portal slug, so any applied edge
stays reconstructable.
"""

import asyncio
import html
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ..ingest import IngestSession
from ..models import Institution, PureOrg, PureOrgParent
from .org_closure import MAX_DEPTH, load_org_tree

#: Portal organisations index, RSS rendering, paginated (?page=N).
ORGANISATIONS_URL = "https://research.utwente.nl/en/organisations/"

#: Portal classification → pure_orgs.org_type; unknown → None (no write).
CLASSIFICATION_TYPES = {
    "university": "university",
    "faculty": "faculty",
    "department": "department",
    "school": "department",
    "institute": "institute",
    "research center": "research_centre",
    "research centre": "research_centre",
    "research institute": "researchinstitute",
}


def name_key(name: str | None) -> str:
    """Match key for portal ↔ pure_orgs display names: fold diacritics,
    unify '&'/'+', drop everything alphanumeric-insensitive. Portal and
    OAI display names agree up to these normalizations."""
    folded = (name or "").casefold().replace("&", " and ").replace("+", " plus ")
    decomposed = unicodedata.normalize("NFKD", folded)
    return re.sub(r"[^a-z0-9]+", "", "".join(c for c in decomposed if not unicodedata.combining(c)))


def classification_to_type(classification: str | None) -> str | None:
    """pure_orgs.org_type for a portal classification label; None unknown."""
    return CLASSIFICATION_TYPES.get((classification or "").strip().casefold())


@dataclass
class PortalUnit:
    """One parsed portal organisations-feed entry (or a curated edge
    assertion, marked)."""

    name: str
    slug: str
    parent_slug: str | None = None
    parent_name: str | None = None
    classification: str | None = None
    successor_slug: str | None = None
    successor_name: str | None = None
    # Owner-approved edge not present in the portal (e.g. the legacy
    # standalone units SOR / DMMP carry no parent anywhere). Recorded in
    # the source_records payload so a curated edge stays distinguishable
    # from a portal-verbatim one.
    curated: bool = False

    def payload(self) -> dict:
        """Verbatim feed content for source_records."""
        return {
            "name": self.name,
            "portal_slug": self.slug,
            "parent_slug": self.parent_slug,
            "parent_name": self.parent_name,
            "classification": self.classification,
            "successor_slug": self.successor_slug,
            "successor_name": self.successor_name,
            "curated": self.curated,
        }


def curated_unit(org_name: str, parent_name: str) -> PortalUnit:
    """A curated parent assertion for the apply pipeline: runs through the
    same gap-fill-only, institute-pin, cycle-guard contract."""
    return PortalUnit(
        name=org_name,
        slug=f"curated/{name_key(org_name)}",
        parent_name=parent_name,
        curated=True,
    )


def _slug_of(url: str) -> str | None:
    match = re.search(r"/en/organisations/([^/]+)/?$", url or "")
    return match.group(1) if match else None


def _block(html_text: str, css_class: str) -> str | None:
    match = re.search(rf'<p class="{css_class}">(.*?)</p>', html_text, flags=re.DOTALL)
    return match.group(1) if match else None


def _link(block_html: str) -> tuple[str | None, str | None]:
    href = re.search(r'href="([^"]+)"', block_html)
    name = re.search(r"<span>(.*?)</span>", block_html, flags=re.DOTALL)
    return (
        _slug_of(href.group(1)) if href else None,
        html.unescape(name.group(1)).strip() if name else None,
    )


def parse_portal_feed(data: bytes | str) -> list[PortalUnit]:
    """Parse one page of the organisations index RSS into units."""
    root = ET.fromstring(data)
    units: list[PortalUnit] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = item.findtext("description") or ""
        if not title or not link:
            continue
        slug = _slug_of(link)
        if slug is None:
            continue
        parent_slug = parent_name = None
        relations = _block(description, "relations")
        if relations:
            parent_slug, parent_name = _link(relations)
        successor_slug = successor_name = None
        takenover = _block(description, "takenover")
        if takenover:
            successor_slug, successor_name = _link(takenover)
        classification = None
        type_match = re.search(r'class="type_classification">([^<]+)<', description)
        if type_match:
            classification = html.unescape(type_match.group(1)).strip()
        units.append(
            PortalUnit(
                name=html.unescape(title).strip(),
                slug=slug,
                parent_slug=parent_slug,
                parent_name=parent_name,
                classification=classification,
                successor_slug=successor_slug,
                successor_name=successor_name,
            )
        )
    return units


async def walk_portal_orgs(
    fetch_page,  # async (page: int) -> bytes
    *,
    max_pages: int = 120,
    page_delay: float = 2.0,
) -> list[PortalUnit]:
    """Walk the paginated organisations feed until an empty page; dedupe
    by portal slug (stable across pages, but never trust it fully). The
    portal's WAF 403-bans bursty clients (observed live), so keep the
    pacing polite."""
    units_by_slug: dict[str, PortalUnit] = {}
    for page in range(1, max_pages + 1):
        page_units = parse_portal_feed(await fetch_page(page))
        for unit in page_units:
            units_by_slug.setdefault(unit.slug, unit)
        if not page_units:
            break
        if page < max_pages:
            await asyncio.sleep(page_delay)
    return list(units_by_slug.values())


async def apply_portal_tree(
    session: AsyncSession,
    institution: Institution,
    units: list[PortalUnit],
    ingest: IngestSession,
    *,
    store_payloads: bool = True,
) -> dict[str, int]:
    """Apply the portal tree to pure_orgs/pure_org_parents per the module
    contract; returns per-step stats. Payloads land in source_records."""
    tree = await load_org_tree(session, institution)
    by_key: dict[str, list[str]] = {}
    for uuid, org in tree.orgs.items():
        by_key.setdefault(name_key(org.name), []).append(uuid)

    root = tree.root
    parented = set(tree.parents)
    stats = {
        "portal_units": len(units),
        "matched": 0,
        "unmatched": 0,
        "ambiguous_name": 0,
        "already_parented": 0,
        "edges_added": 0,
        "institute_pinned": 0,
        "successor_skipped": 0,
        "no_parent_in_portal": 0,
        "parent_unmatched": 0,
        "types_updated": 0,
        "types_skipped_institute": 0,
    }

    new_edges: list[PureOrgParent] = []
    type_updates: list[tuple[str, str]] = []
    payloads: list[tuple[str, dict]] = []
    for unit in units:
        if store_payloads:
            payloads.append((unit.slug, unit.payload()))
        uuids = by_key.get(name_key(unit.name), [])
        if len(uuids) > 1:
            stats["ambiguous_name"] += 1
            continue
        if not uuids:
            stats["unmatched"] += 1
            continue
        uuid = uuids[0]
        org = tree.orgs[uuid]
        stats["matched"] += 1

        # Parent edge: fill the gap, never override an OAI edge.
        if uuid in parented:
            stats["already_parented"] += 1
        elif unit.successor_slug:
            stats["successor_skipped"] += 1
        elif unit.parent_name is None:
            stats["no_parent_in_portal"] += 1
        else:
            parent_uuids = by_key.get(name_key(unit.parent_name), [])
            if len(parent_uuids) != 1:
                stats["parent_unmatched"] += 1
            elif (org.org_type or "") == "institute" and parent_uuids[0] != root:
                stats["institute_pinned"] += 1
            else:
                new_edges.append(
                    PureOrgParent(
                        institution_id=institution.id,
                        org_uuid=uuid,
                        parent_uuid=parent_uuids[0],
                        parent_name=unit.parent_name,
                    )
                )
                stats["edges_added"] += 1

        # org_type upgrade: UT-side orgs only (flat, or already connected
        # to the root); never demote an institute.
        portal_type = classification_to_type(unit.classification)
        connected = root is not None and root in tree.closure.get(uuid, [])
        if portal_type and org.org_type != portal_type and (connected or uuid not in parented):
            if (org.org_type or "") == "institute":
                stats["types_skipped_institute"] += 1
            else:
                type_updates.append((uuid, portal_type))
                stats["types_updated"] += 1

    # Cycle guard: walking up from the proposed parent (over existing
    # parents plus edges accepted so far) must never reach the child.
    parent_of = dict(tree.parents)
    safe_edges: list[PureOrgParent] = []
    for edge in new_edges:
        cyclic = False
        current = parent_of.get(edge.parent_uuid)
        steps = 0
        while current is not None and steps <= MAX_DEPTH:
            if current == edge.org_uuid:
                cyclic = True
                break
            current = parent_of.get(current)
            steps += 1
        if cyclic:
            stats["edges_added"] -= 1
            stats["cycle_skipped"] = stats.get("cycle_skipped", 0) + 1
            continue
        parent_of[edge.org_uuid] = edge.parent_uuid
        safe_edges.append(edge)

    if safe_edges:
        session.add_all(safe_edges)
    for uuid, portal_type in type_updates:
        await session.execute(
            update(PureOrg)
            .where(PureOrg.institution_id == institution.id, PureOrg.uuid == uuid)
            .values(org_type=portal_type)
        )
    if payloads and store_payloads:
        await ingest.ingest_records(payloads)
    return stats
