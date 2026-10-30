"""CERIF (oai_cerif_openaire) entity parsing — ported from ut-metadata's
pure_cerif.py (syntheca shapes kept).

Elements are matched by localname, never by one fixed namespace URI: the
live endpoint serves the OpenAIRE CERIF 1.2 profile with relative @id
values ("openaire_cris_persons/<uuid>"), older captures use eurocris CERIF
1.6 namespaces. Only the entities the standalone author path needs are
ported (person, orgunit, publication contributors); the full generic
mapper stays in ut-metadata.
"""

import xml.etree.ElementTree as ET
from typing import Any


def localname(el: ET.Element) -> str:
    """Tag without the namespace URI."""
    return el.tag.rsplit("}", 1)[-1]


def ref_uuid(ref: str | None) -> str | None:
    """'openaire_cris_orgunits/<uuid>' -> <uuid> (CERIF 1.2 relative @id);
    bare uuids pass through."""
    if not ref:
        return None
    return ref.rsplit("/", 1)[-1] or None


def _children(el: ET.Element, name: str) -> list[ET.Element]:
    """Direct children with this localname."""
    return [c for c in el if localname(c) == name]


def _child(el: ET.Element | None, name: str) -> ET.Element | None:
    """First direct child with this localname; None-safe on the parent."""
    if el is None:
        return None
    return next((c for c in el if localname(c) == name), None)


def _text(el: ET.Element | None, name: str | None = None) -> str | None:
    """Whitespace-normalized text of el (or of its first `name` child)."""
    target = _child(el, name) if name else el
    if target is None:
        return None
    value = " ".join(target.itertext()).strip()
    return value or None


def _id(el: ET.Element | None) -> str | None:
    """Relative @id (e.g. openaire_cris_persons/<uuid>), live CERIF 1.2 form."""
    return el.get("id") if el is not None else None


def _affiliations(el: ET.Element) -> list[dict[str, Any]]:
    """Affiliation/OrgUnit refs under a person or contributor element."""
    out: list[dict[str, Any]] = []
    for affil in _children(el, "Affiliation"):
        org = _child(affil, "OrgUnit")
        if org is None:
            continue
        out.append(
            {
                "affiliation_id": _id(org),
                "affiliation_name": _text(org, "Name"),
            }
        )
    return out


def _typed_identifiers(el: ET.Element) -> list[dict[str, str | None]]:
    """Repeated <Identifier type="...">value</Identifier> elements."""
    out: list[dict[str, str | None]] = []
    for ident in _children(el, "Identifier"):
        value = _text(ident)
        id_type = ident.get("type")
        if value is None and id_type is None:
            continue
        out.append({"value": value, "type": id_type})
    return out


def parse_cerif_person(el: ET.Element) -> dict[str, Any]:
    """Person: names, identifiers, orgunit refs."""
    family, first = _person_name(_child(el, "PersonName"))
    return {
        "id": _id(el),
        "family_names": family,
        "first_names": first,
        "orcid": _text(el, "ORCID"),
        "scopus_author_id": _text(el, "ScopusAuthorID"),
        "researcher_id": _text(el, "ResearcherID"),
        "affiliations": _affiliations(el),
    }


def parse_cerif_orgunit(el: ET.Element) -> dict[str, Any]:
    """OrgUnit: name, type, identifiers, parent ref."""
    identifiers = _typed_identifiers(el)
    parent = _child(_child(el, "PartOf"), "OrgUnit")
    return {
        "id": _id(el),
        "type": _text(el, "Type"),
        "identifiers": identifiers,
        "name": _text(el, "Name"),
        "acronym": _text(el, "Acronym"),
        "part_of_org_id": _id(parent),
        "part_of_name": _text(parent, "Name"),
    }


def _person_name(person: ET.Element | None) -> tuple[str | None, str | None]:
    return _text(person, "FamilyNames"), _text(person, "FirstNames")


def publication_contributors(el: ET.Element, role: str = "Author") -> list[dict[str, Any]]:
    """Authors/Editors: person + affiliations, primary affiliation flattened.

    Live CERIF 1.2 nests <Author> under an <Authors> wrapper; older
    captures place the role elements directly on the publication.
    """
    wrapper = _child(el, f"{role}s")
    scope = wrapper if wrapper is not None else el
    out: list[dict[str, Any]] = []
    for item in _children(scope, role):
        person = _child(item, "Person")
        if person is None:
            continue
        family, first = _person_name(_child(person, "PersonName"))
        affiliations = _affiliations(item)
        primary = affiliations[0] if affiliations else {}
        out.append(
            {
                "person_id": _id(person),
                "family_names": family,
                "first_names": first,
                "affiliation_id": primary.get("affiliation_id"),
                "affiliation_name": primary.get("affiliation_name"),
                "affiliations": affiliations,
            }
        )
    return out
