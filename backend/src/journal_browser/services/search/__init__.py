"""Journal search: Postgres FTS + facets + keyset pagination."""

from ...config import get_settings as get_settings
from .classify import OA_TYPES, _oa_type, oa_type_value
from .core import search_journals
from .currency import _year_rate
from .cursors import encode_cursor, parse_cursor
from .facets import facet_counts
from .query import (
    APC_SHOWN,
    WORKS_CUTOFF,
    _like,
    _norm_issn,
    _order,
    attach_apc_display,
    base_query,
)
from .similar import semantic_search, similar_journals

__all__ = [
    "APC_SHOWN",
    "OA_TYPES",
    "WORKS_CUTOFF",
    "_like",
    "_norm_issn",
    "_oa_type",
    "_order",
    "_year_rate",
    "attach_apc_display",
    "base_query",
    "encode_cursor",
    "facet_counts",
    "oa_type_value",
    "parse_cursor",
    "search_journals",
    "semantic_search",
    "similar_journals",
]
