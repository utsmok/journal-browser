"""Journal search: Postgres FTS + facets + keyset pagination."""

from ...config import get_settings as get_settings
from .batch import journals_by_issn
from .classify import OA_TYPES, oa_type_case, oa_type_value
from .core import search_journals
from .currency import year_rate
from .cursors import encode_cursor, parse_cursor
from .facets import facet_counts
from .query import (
    APC_SHOWN,
    WORKS_CUTOFF,
    attach_apc_display,
    base_query,
    escape_like,
    normalize_issn,
    sort_order,
)
from .similar import semantic_search, similar_journals

__all__ = [
    "APC_SHOWN",
    "OA_TYPES",
    "WORKS_CUTOFF",
    "attach_apc_display",
    "base_query",
    "encode_cursor",
    "escape_like",
    "facet_counts",
    "journals_by_issn",
    "normalize_issn",
    "oa_type_case",
    "oa_type_value",
    "parse_cursor",
    "search_journals",
    "semantic_search",
    "similar_journals",
    "sort_order",
    "year_rate",
]
