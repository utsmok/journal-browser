"""Identifier, title and source vocabulary normalization shared by harvest,
routers and services.

Pure value and SQL-expression helpers; this module imports neither the
harvest nor the services package, so either side can use it without a
cycle.
"""

import re
from typing import Any

from sqlalchemy import func, literal_column

_ROR_RE = re.compile(r"ror\.org/(0[0-9a-z]{8})", re.IGNORECASE)


def normalize_doi(doi: str | None) -> str | None:
    """Lower-cased bare DOI form for cross-source dedupe ('', None -> None)."""
    if not doi:
        return None
    value = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    return value or None


def normalize_ror(*values: Any) -> str | None:
    """Bare lowercase ROR id from any candidate string, else None."""
    for v in values:
        if v and (m := _ROR_RE.search(str(v))):
            return m.group(1).lower()
    return None


#: Requirement levels of a Jisc OPF policy, strictest first. "none" is the
#: readers' code for a policy that states no requirement.
REQUIREMENT_ORDER = ("requires", "encourages", "no_policy_for", "does_not_mention", "none")

#: Jisc OPF spells one level "does_no_mention" (its funder payloads of
#: 2026-11); the stored and served spelling is "does_not_mention".
_REQUIREMENT_SPELLINGS = {"does_no_mention": "does_not_mention"}


def normalize_requirement(value: Any) -> str | None:
    """Canonical Jisc OPF requirement level: stripped, lower-cased, the
    Jisc misspelling mapped. None for a missing or blank value."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return _REQUIREMENT_SPELLINGS.get(cleaned, cleaned) or None


def normalize_policy_requirements(block: Any) -> Any:
    """Policy block with every `requirement` value in canonical spelling.
    Returns a new dict or list and leaves the input as is."""
    if isinstance(block, dict):
        return {
            key: normalize_requirement(value)
            if key == "requirement" and isinstance(value, str)
            else normalize_policy_requirements(value)
            for key, value in block.items()
        }
    if isinstance(block, list):
        return [normalize_policy_requirements(value) for value in block]
    return block


def bare_openalex_id(openalex_id: Any) -> Any:
    """An OpenAlex id without its https://openalex.org/ prefix; stored ids
    come in both forms."""
    # Inline literals, not bind parameters: the same expression then groups.
    return func.regexp_replace(
        openalex_id, literal_column("'^https://openalex.org/'"), literal_column("''")
    )


def norm_title(title: str) -> str:
    """Case/punctuation-folded title for fuzzy matching."""
    folded = title.casefold()
    return re.sub(r"[^0-9a-z]+", " ", folded).strip()


_ISSN_RE = re.compile(r"^(\d{4})-?(\d{3}[\dX])$")


def normalize_issn_l(value: str) -> str | None:
    """Canonical ISSN form ``XXXX-XXXX`` from a bare or hyphenated ISSN, else
    None. Case, hyphens and surrounding spaces never matter."""
    m = _ISSN_RE.match(value.strip().replace(" ", "").upper())
    return f"{m.group(1)}-{m.group(2)}" if m else None
