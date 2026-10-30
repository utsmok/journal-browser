"""Pure org-tree closure: the affiliation rule (ported org_tree semantics).

An affiliation resolves to the institution only through the org-tree
closure — "resolves to some org" is not affiliation (ut-metadata's owner
ruling: partner universities also carry pure_uuid-stamped org rows;
resolving to any org proves nothing).

The root is resolved per institution, not per ROR: live CERIF OrgUnit
records carry Scopus affiliation ids, not ROR identifiers (ut-metadata's
org.ror needs the OpenAlex org match; standalone works without it). The
ladder: root candidate matching the institution's name/short name, else
the single 'university'-typed root, else the single root; None (empty
roster, degraded stats) when ambiguous.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Institution, PureOrg, PureOrgParent

#: same depth cap as ut-metadata's org_tree closure view
MAX_DEPTH = 30


def _name_key(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


@dataclass
class OrgTree:
    """The institution's org tree with closure chains.

    closure[uuid] = [uuid, parent, grandparent, ... root] (self first);
    connected = uuids whose chain reaches the resolved root."""

    orgs: dict[str, PureOrg]
    parents: dict[str, str]
    closure: dict[str, list[str]]
    root: str | None
    connected: set[str] = field(default_factory=set)

    def resolves(self, org_uuids: list[str] | None) -> bool:
        """True when any of the org uuids closes on the institution root."""
        return any(uuid in self.connected for uuid in org_uuids or [])


def build_closure(orgs: dict[str, PureOrg], parents: dict[str, str]) -> dict[str, list[str]]:
    """Ancestor chain per org (self first), depth-capped; cycles truncate."""
    closure: dict[str, list[str]] = {}
    for uuid in orgs:
        chain: list[str] = []
        current: str | None = uuid
        while current is not None and current not in chain and len(chain) <= MAX_DEPTH:
            chain.append(current)
            current = parents.get(current)
        closure[uuid] = chain
    return closure


def resolve_root(
    orgs: dict[str, PureOrg],
    parents: dict[str, str],
    institution: Institution,
) -> str | None:
    """The institution's root org uuid (see module docstring ladder)."""
    roots = sorted(uuid for uuid in orgs if uuid not in parents)
    if not roots:
        return None
    inst_names = {_name_key(institution.name), _name_key(institution.short_name)}
    inst_names.discard("")
    for uuid in roots:
        if _name_key(orgs[uuid].name) in inst_names:
            return uuid
    universities = [uuid for uuid in roots if (orgs[uuid].org_type or "") == "university"]
    if len(universities) == 1:
        return universities[0]
    if len(roots) == 1:
        return roots[0]
    return None


def org_ror(identifiers: list[Any] | None) -> str | None:
    """Bare ROR from a CERIF identifier list ([{value, type}])."""
    for ident in identifiers or []:
        if not isinstance(ident, dict):
            continue
        if "ror" in str(ident.get("type") or "").lower():
            value = str(ident.get("value") or "").strip()
            ror = re.sub(r"^https?://ror\.org/", "", value, flags=re.IGNORECASE)
            if ror:
                return ror.lower()
    return None


async def load_org_tree(session: AsyncSession, institution: Institution) -> OrgTree:
    """Load + close the institution's org tree."""
    orgs = {
        row.uuid: row
        for row in (
            await session.execute(select(PureOrg).where(PureOrg.institution_id == institution.id))
        ).scalars()
    }
    parents = {
        row.org_uuid: row.parent_uuid
        for row in (
            await session.execute(
                select(PureOrgParent).where(PureOrgParent.institution_id == institution.id)
            )
        ).scalars()
    }
    closure = build_closure(orgs, parents)
    root = resolve_root(orgs, parents, institution)
    connected = {uuid for uuid, chain in closure.items() if root is not None and root in chain}
    return OrgTree(orgs=orgs, parents=parents, closure=closure, root=root, connected=connected)
