"""Identifier and title normalization shared by harvest and services.

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
