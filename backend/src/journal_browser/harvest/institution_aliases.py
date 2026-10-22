"""Seeded institution-name alias matching for the home institution.

Decision 6: v1 is single-institution (University of Twente, ROR 006hf6230).
Upstream sources spell the name inconsistently (JCT `institutions_name`,
OpenAPC, ESAC narratives), so callers canonicalize via :func:`match_institution`.
Unknown names are never silently dropped — route them through
:func:`log_unknown_institution` so a reviewer can extend the seed map.
"""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

CANONICAL_NAME = "University of Twente"

#: Seed map, display form -> all lowercase key forms that should resolve to it.
_VARIANTS: dict[str, set[str]] = {
    CANONICAL_NAME: {"university of twente", "universiteit twente"},
    "Twente University": {"twente university"},
    "Utwente": {"utwente", "universitytwente"},
    "UT": {"ut"},
}


def _normalize(name: str) -> str:
    """Lowercase, strip accents, drop punctuation/whitespace entirely."""
    text = unicodedata.normalize("NFKD", name).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


_ALIASES: dict[str, str] = {
    _normalize(key): variant for variant, keys in _VARIANTS.items() for key in keys
}


def match_institution(name: str) -> tuple[str | None, str | None]:
    """Resolve an institution display name against the seeded alias map.

    Returns ``(canonical_name, matched_variant)`` on a hit — ``matched_variant``
    is the seed form that matched, for provenance. Returns ``(None, raw)`` for
    unknown names; pair with :func:`log_unknown_institution`, never drop silently.
    """
    variant = _ALIASES.get(_normalize(name))
    if variant is None:
        return None, name
    return CANONICAL_NAME, variant


def log_unknown_institution(name: str, context: str = "") -> None:
    """Log an unmatched institution name so the seed map can be reviewed/extended."""
    suffix = f" ({context})" if context else ""
    logger.warning("unknown institution name %r%s — add to institution_aliases", name, suffix)
