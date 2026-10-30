import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

from .doi import extract_doi
from .transport import DC_NS, DCT_NS, PureOaiError, oai_tag

logger = logging.getLogger(__name__)


def _header_fields(record: ET.Element) -> tuple[str, str, list[str], str | None]:
    """(oai_identifier, datestamp, set_specs, status) from a <record> header."""
    header = record.find(oai_tag("header"))
    if header is None:
        raise PureOaiError("parse", "record without header")
    return (
        (header.findtext(oai_tag("identifier")) or "").strip(),
        (header.findtext(oai_tag("datestamp")) or "").strip(),
        [s for el in header.findall(oai_tag("setSpec")) if el.text and (s := el.text.strip())],
        header.get("status"),
    )


def _flat_dc(record: ET.Element, namespace: str) -> dict[str, Any]:
    """Flat dc/dct dict: scalar value, or list once an element repeats."""
    out: dict[str, Any] = {}
    for el in record.findall(f".//{{{namespace}}}*"):
        value = " ".join(el.itertext()).strip()
        if not value:
            continue
        key = el.tag.rsplit("}", 1)[-1]
        seen = out.get(key)
        if seen is None:
            out[key] = value
        elif isinstance(seen, list):
            seen.append(value)
        else:
            out[key] = [seen, value]
    return out


def _inner_metadata_xml(record: ET.Element) -> str:
    """Inner XML of <metadata> as a string (verbatim-ish re-serialization)."""
    metadata = record.find(oai_tag("metadata"))
    if metadata is None:
        return ""
    return "".join(ET.tostring(child, encoding="unicode") for child in metadata)


def pure_uuid_for(oai_identifier: str) -> str:
    """Pure uuid from the OAI identifier
    (oai:ris.utwente.nl:publications:<uuid> -> <uuid>)."""
    tail = oai_identifier.rsplit(":", 1)[-1]
    return tail.rsplit("/", 1)[-1]


def _cerif_publication_fields(metadata_el: ET.Element | None) -> dict[str, Any]:
    """Targeted CERIF Publication extraction: the fields works needs.

    The full generic CERIF mapper stays in ut-metadata; everything else in
    the record remains available verbatim via payload["metadata_xml"].
    """
    if metadata_el is None:
        return {}
    root = next(iter(metadata_el), None)
    if root is None or root.tag.rsplit("}", 1)[-1] != "Publication":
        return {}

    def local(el: Any) -> str:
        return el.tag.rsplit("}", 1)[-1]

    fields: dict[str, Any] = {}
    for child in root:
        name = local(child)
        text = " ".join(child.itertext()).strip()
        if name == "DOI" and text:
            fields["doi"] = text
        elif name == "ISSN" and text:
            fields.setdefault("issn", text)
        elif name == "Type":
            fields["type"] = text.rsplit(":", 1)[-1]
        elif name == "Access":
            fields["oa_status"] = text
        elif name == "Publishers":
            for pub in child:
                for sub in pub:
                    if local(sub) == "OrgUnit":
                        for n in sub:
                            if local(n) == "Name" and (t := " ".join(n.itertext()).strip()):
                                fields["publisher"] = t
    return fields


def record_payload(record: ET.Element) -> tuple[str, dict[str, Any]]:
    """(source_pk, payload) for a non-deleted record; source_pk = oai_identifier."""
    oai_identifier, datestamp, set_specs, _ = _header_fields(record)
    payload: dict[str, Any] = {
        "oai_identifier": oai_identifier,
        "datestamp": datestamp,
        "set_specs": set_specs,
        "metadata_xml": _inner_metadata_xml(record),
    }
    dc = _flat_dc(record, DC_NS)
    payload["dc"] = dc
    if dct := _flat_dc(record, DCT_NS):
        payload["dc_dct"] = dct
    identifiers = dc.get("identifier")
    identifier_values = (
        identifiers if isinstance(identifiers, list) else ([identifiers] if identifiers else [])
    )
    for value in identifier_values:
        doi = extract_doi(value)
        if doi:
            payload["doi_normalized"] = doi
            break
    return oai_identifier, payload


def _norm_title(title: str) -> str:
    """Case/punctuation-folded title for fuzzy matching."""
    folded = title.casefold()
    return re.sub(r"[^0-9a-z]+", " ", folded).strip()


def _normalize_access(raw: str | None) -> str | None:
    """Compact access-status literal from Pure's vocabularies.

    Eprints (oai_dc rights): info:eu-repo/semantics/openAccess -> openAccess.
    COAR (cerif Access): .../access_right/c_abf2 -> coar:c_abf2.
    """
    if not raw:
        return None
    raw = raw.strip()
    if "info:eu-repo/semantics/" in raw:
        return raw.rsplit("/", 1)[-1] or None
    if "coar/access_right/" in raw:
        code = raw.rsplit("/", 1)[-1]
        return f"coar:{code}" if code else None
    return raw


# Pure/Eprints/COAR access literals -> the closed works.oa_status set
# (harvest.common.OA_STATUSES). Pure openAccess means the fulltext is public
# in the institutional repository, i.e. green; anything not publicly readable
# now maps to closed; unknown literals drop to None (raw stays in payloads).
_OA_MAP = {
    "openaccess": "green",
    "closedaccess": "closed",
    "embargoedaccess": "closed",
    "restrictedaccess": "closed",
    "metadataonly": "closed",
    "coar:c_abf2": "green",  # open access
    "coar:c_16ec": "closed",  # closed access
    "coar:c_f1cf": "closed",  # embargoed access
    "coar:c_998f": "closed",  # restricted access
}


def canonical_access(raw: str | None) -> str | None:
    """Pure access literal -> canonical oa_status; None when unmappable."""
    compact = _normalize_access(raw)
    if compact is None:
        return None
    return _OA_MAP.get(compact.lower().replace(" ", "").replace("-", ""))


def _dc_first(value: Any) -> str | None:
    if isinstance(value, list):
        return str(value[0]).strip() if value else None
    return str(value).strip() if value else None


def year_for_set(set_spec: str) -> int | None:
    """publications:year2023 -> 2023; None otherwise."""
    if set_spec.startswith("publications:year"):
        try:
            return int(set_spec.rsplit("year", 1)[1])
        except ValueError:
            return None
    return None
