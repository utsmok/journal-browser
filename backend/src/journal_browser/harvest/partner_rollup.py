"""Search-text extraction and conservative parent/successor roll-ups for
partner_institutions.

Roll-up rules (conservative by design):
1. Inactive or withdrawn ROR records with a single active ROR successor
   present in partner_institutions roll up into that successor.
2. Same-city sub-units / hospital locations / embedded facilities belonging
   to a single publishing organisation roll up into that parent when:
   - The parent exists in partner_institutions and is active (excludes
     abstract governing boards like the ETH Board).
   - Both share country_code and a non-null city.
   - The parent is not a federated university system or multi-institute
     research society (e.g. University of London, UC System, Max Planck
     Society, Helmholtz Association, CNRS, Leibniz, CAS, NWO-I).
   - And one of:
     a. Child is a facility under a same-city education or healthcare parent
        (e.g. Donders Institute -> Radboud University Nijmegen,
        Zernike Institute -> University of Groningen).
     b. Child and parent are both healthcare and the child's name contains
        the parent's name (e.g. Amsterdam UMC Location UvA -> Amsterdam UMC,
        Erasmus MC Cancer Institute -> Erasmus MC).
     c. Child's name explicitly marks it as an internal faculty/department/
        school/clinic of the parent (never merging distinct universities
        like UCL or Queen Mary University of London into University of London).

Chains are collapsed to their final active root, and cycles are broken.
"""

import re
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..identifiers import normalize_ror
from ..models import PartnerInstitution

#: Parent-name terms indicating a federated system, society, ministry or
#: umbrella consortium rather than one organisation/campus.
_UMBRELLA_RE = re.compile(
    r"\b(system|association|society|board|network|consortium|ministry|ministère|"
    r"council|agency|federation|alliance|league|academy of sciences|health system|"
    r"research centres|research centers|mass general brigham)\b",
    re.IGNORECASE,
)

#: Child-name prefixes that clearly mark an internal sub-unit of an education
#: or healthcare institution rather than an independent university.
_SUBUNIT_PREFIX_RE = re.compile(
    r"^(faculty|school|department|college|graduate school|division|clinic|"
    r"medical center|medical centre|centre hospitalier|university hospital) (of|for|at) ",
    re.IGNORECASE,
)

#: Curated short acronyms that ROR records occasionally omit for Dutch/key
#: partners (e.g. ROR lists "Rijksuniversiteit Groningen" without "RUG").
_EXTRA_ACRONYMS: dict[str, tuple[str, ...]] = {
    "012p63287": ("rug",),
    "02e2c7k09": ("tud", "tu delft"),
    "02c2kyt77": ("tue", "tu/e"),
    "04qw24q55": ("wur",),
    "006hf6230": ("ut", "utwente"),
    "04pp8hn57": ("uu",),
    "04dkp9463": ("uva",),
    "008xxew50": ("vu", "vu amsterdam"),
    "027bh9e22": ("ul",),
    "016xsfp80": ("ru",),
    "02jz4aj89": ("um",),
    "03cv38k47": ("umcg",),
    "05wg1m734": ("radboudumc",),
    "0575yy874": ("umcu", "umc utrecht"),
    "05xvt9f17": ("lumc",),
    "05grdyy37": ("aumc", "amsterdam umc"),
    "018906e22": ("emc", "erasmus mc"),
    "033xvax87": ("mst",),
    "04grrp271": ("zgt",),
    "01dmjt679": ("rrd",),
    "01bnjb948": ("tno",),
    "01ggx4157": ("cern",),
}


def build_search_fields(
    *,
    ror: str,
    name: str | None,
    city: str | None = None,
    payload: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    """Return (search_text, acronyms) for a partner_institutions row."""
    parts: list[str] = []
    seen_parts: set[str] = set()
    acronyms: list[str] = []
    seen_acronyms: set[str] = set()

    def add_part(value: Any) -> None:
        text = str(value or "").strip()
        if not text:
            return
        low = text.lower()
        if low not in seen_parts:
            seen_parts.add(low)
            parts.append(low)

    def add_acronym(value: Any) -> None:
        text = str(value or "").strip().lower()
        if text and text not in seen_acronyms:
            seen_acronyms.add(text)
            acronyms.append(text)

    add_part(name)
    add_part(city)
    add_part(ror)

    if isinstance(payload, dict):
        for entry in payload.get("names") or []:
            val = (entry.get("value") or "").strip()
            if not val:
                continue
            add_part(val)
            types = set(entry.get("types") or [])
            if "acronym" in types or ("alias" in types and len(val) <= 16):
                add_acronym(val)

    for extra in _EXTRA_ACRONYMS.get(ror.lower(), ()):
        add_part(extra)
        add_acronym(extra)

    return " | ".join(parts), acronyms


def _single_successor(payload: dict[str, Any] | None) -> str | None:
    """Return the bare ROR of an inactive record's sole successor, if any."""
    if not isinstance(payload, dict):
        return None
    successors = [
        ror
        for rel in payload.get("relationships") or []
        if (rel.get("type") or "").lower() == "successor"
        and (ror := normalize_ror(rel.get("id"))) is not None
    ]
    unique = list(dict.fromkeys(successors))
    return unique[0] if len(unique) == 1 else None


def _should_rollup_to_parent(child: dict[str, Any], parent: dict[str, Any]) -> bool:
    """True when `child` is clearly a same-location sub-unit of `parent`."""
    if parent["status"] in ("inactive", "withdrawn"):
        return False
    c_cc = (child["country_code"] or "").upper()
    p_cc = (parent["country_code"] or "").upper()
    c_city = (child["city"] or "").strip().lower()
    p_city = (parent["city"] or "").strip().lower()
    if not c_cc or c_cc != p_cc or not c_city or c_city != p_city:
        return False

    c_name = (child["name"] or "").strip()
    p_name = (parent["name"] or "").strip()
    if not c_name or not p_name:
        return False
    if _UMBRELLA_RE.search(p_name):
        return False

    c_type = (child["org_type"] or "").lower()
    p_type = (parent["org_type"] or "").lower()
    if p_type in ("government", "nonprofit", "funder", "other", ""):
        return False

    c_low, p_low = c_name.lower(), p_name.lower()

    # Embedded research facility at a same-city university or hospital.
    if c_type == "facility" and p_type in ("education", "healthcare"):
        return True

    # Hospital site/wing carrying the hospital's own name (Amsterdam UMC
    # locations, Erasmus MC Cancer Institute / Sophia Children's Hospital).
    if c_type == "healthcare" and p_type == "healthcare" and p_low in c_low:
        return True

    # Explicit faculty/school/department/clinic of a university or hospital.
    return bool(p_type in ("education", "healthcare") and _SUBUNIT_PREFIX_RE.match(c_name))


def compute_rollup_map(records: list[dict[str, Any]]) -> dict[str, str | None]:
    """Compute {ror: rollup_ror | None} across all stored partner rows."""
    by_ror = {r["ror"]: r for r in records}
    direct: dict[str, str] = {}

    for ror, rec in by_ror.items():
        # Rule 1: inactive/withdrawn -> sole successor (when present in canon).
        if rec["status"] in ("inactive", "withdrawn"):
            succ = _single_successor(rec.get("payload"))
            if succ and succ != ror and succ in by_ror:
                direct[ror] = succ
                continue

        # Rule 2: same-city sub-unit/location -> parent (when present in canon).
        parent_ror = rec.get("parent_ror")
        if (
            parent_ror
            and parent_ror != ror
            and parent_ror in by_ror
            and _should_rollup_to_parent(rec, by_ror[parent_ror])
        ):
            direct[ror] = parent_ror

    # Resolve multi-hop chains (e.g. inactive child -> active child -> parent)
    # and break any cycle safely.
    resolved: dict[str, str | None] = {}
    for ror in by_ror:
        cur = ror
        seen = {cur}
        while cur in direct:
            nxt = direct[cur]
            if nxt in seen:
                break
            seen.add(nxt)
            cur = nxt
        resolved[ror] = None if cur == ror else cur
    return resolved


async def refresh_partner_rollups(session: AsyncSession) -> dict[str, int]:
    """Recompute partner_institutions.rollup_ror and backfill missing
    search_text/acronyms for every stored partner."""
    rows = (
        await session.execute(
            select(
                PartnerInstitution.ror,
                PartnerInstitution.name,
                PartnerInstitution.org_type,
                PartnerInstitution.country_code,
                PartnerInstitution.city,
                PartnerInstitution.parent_ror,
                PartnerInstitution.status,
                PartnerInstitution.payload,
                PartnerInstitution.rollup_ror,
                PartnerInstitution.search_text,
            )
        )
    ).all()
    records = [
        {
            "ror": r.ror,
            "name": r.name,
            "org_type": r.org_type,
            "country_code": r.country_code,
            "city": r.city,
            "parent_ror": r.parent_ror,
            "status": r.status,
            "payload": r.payload,
        }
        for r in rows
    ]
    rollup_map = compute_rollup_map(records)

    updated_rollups = 0
    updated_search = 0
    for r in rows:
        target = rollup_map.get(r.ror)
        values: dict[str, Any] = {}
        if target != r.rollup_ror:
            values["rollup_ror"] = target
            updated_rollups += 1
        if not r.search_text:
            st, acr = build_search_fields(ror=r.ror, name=r.name, city=r.city, payload=r.payload)
            values["search_text"] = st
            values["acronyms"] = acr or None
            updated_search += 1
        if values:
            await session.execute(
                update(PartnerInstitution).where(PartnerInstitution.ror == r.ror).values(**values)
            )
    return {
        "total": len(rows),
        "rolled_up": sum(1 for v in rollup_map.values() if v is not None),
        "updated_rollups": updated_rollups,
        "updated_search": updated_search,
    }
