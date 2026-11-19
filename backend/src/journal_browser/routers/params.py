"""Shared request-parameter parsing: one multi-select convention and one
deal-filter vocabulary for the serving routers.

Multi-select separator: comma is the convention; the pipe form stays
accepted because the frontend's existing builders emit pipe-joined
values (frontend/lib/api.ts joins with "|"). Selects whose values can
themselves contain commas (org-unit and publisher names) must use
split_pipe: a comma split would cut those names apart."""

import re
from typing import Annotated, Literal

from fastapi import Query
from pydantic import BeforeValidator

from ..vocab import OaType

_SPLIT_RE = re.compile(r"[,|]")


def _split_raw(raw: str | list[str] | None, pattern: re.Pattern[str]) -> list[str] | None:
    # FastAPI hands list-typed params the assembled list of query values;
    # the frontend sends one joined key, repeated keys also work.
    if raw is None:
        return None
    if isinstance(raw, list):
        raw = "|".join(str(v) for v in raw)
    parts = [p for p in pattern.split(raw) if p]
    return parts or None


def split_multi(raw: str | list[str] | None) -> list[str] | None:
    """Comma- or pipe-joined multi-select."""
    return _split_raw(raw, _SPLIT_RE)


def split_pipe(raw: str | list[str] | None) -> list[str] | None:
    """Pipe-joined multi-select for values that can contain commas."""
    return _split_raw(raw, re.compile(r"\|"))


def _deal_alias(value: str) -> str:
    # Legacy vocabulary: the publisher page used to send "none".
    return {"none": "not_covered"}.get(value, value)


DealFilter = Annotated[
    Literal["any", "covered", "not_covered"] | None,
    BeforeValidator(_deal_alias),
    Query(description="Deal coverage filter (legacy value none = not_covered)"),
]

OaTypeFilter = Annotated[list[OaType] | None, BeforeValidator(split_multi), Query(max_length=60)]

SearchIn = Annotated[
    Literal["all", "title", "publisher", "topic"],
    Query(description="Field the free-text query matches against"),
]
JournalSort = Annotated[
    Literal[
        "relevance",
        "title",
        "publisher",
        "institution_works",
        "quartile",
        "topic",
        "apc",
        "2yr_mean_citedness",
    ],
    Query(description="Result sort key"),
]
QuartileFilter = Annotated[
    list[Literal["Q1", "Q2", "Q3", "Q4"]] | None,
    BeforeValidator(split_multi),
    Query(max_length=20),
]
PartsFilter = Annotated[
    list[Literal["standalone", "chapter", "part"]] | None,
    BeforeValidator(split_multi),
    Query(max_length=30),
]
