"""Scaffold: "cited by Twente staff" + co-citation similar journals.

Two-step W-id batching (OpenAlex has no direct source-level citation
filter): collect a journal's recent work IDs, then count citations to
those IDs in batches of 100. BLOCKED per docs/decisions.md: scaffolding
only, `JB_ENABLE_JOURNAL_CITATIONS` default OFF; no full harvests until
an explicit go.
"""

import logging
from collections.abc import Iterator
from typing import Any

from ..config import get_settings
from ..ingest import IngestSession

logger = logging.getLogger(__name__)

SOURCE = "openalex"
ENTITY_TYPE = "journal_citations"
PER_PAGE = 100
#: Two-step batching size for works-id filters (OpenAlex URL limits).
BATCH_SIZE = 100


def assert_enabled() -> None:
    if not get_settings().enable_journal_citations:
        raise RuntimeError(
            "journal citations are disabled (JB_ENABLE_JOURNAL_CITATIONS=false); "
            "full runs wait for an explicit go"
        )


async def collect_work_ids(
    client: Any,
    source_id: str,
    *,
    max_works: int = 5000,
    ingest: IngestSession | None = None,
) -> list[str]:
    """Step 1: recent work IDs of one journal (cursor-paged, bounded)."""
    work_ids: list[str] = []
    async for item in client.works.iterate(
        page_size=PER_PAGE,
        filters={"primary_location.source.id": source_id},
        select="id",
    ):
        work_id = item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
        if work_id:
            work_ids.append(str(work_id).rsplit("/", 1)[-1])
        if len(work_ids) >= max_works:
            break
    return work_ids


def iter_batches(items: list[str], size: int = BATCH_SIZE) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def count_citing_works(client: Any, work_ids: list[str]) -> int:
    """Step 2: works citing any of the given work IDs, batched counts."""
    total = 0
    for batch in iter_batches(work_ids):
        total += await client.works.count(filters={"cites": "|".join(batch)})
    return total


async def cited_by_institution(client: Any, source_id: str, inst_id: str) -> dict[str, Any]:
    """Citations of one journal's recent works from one institution's staff."""
    assert_enabled()
    work_ids = await collect_work_ids(client, source_id)
    total = 0
    for batch in iter_batches(work_ids):
        total += await client.works.count(
            filters={"cites": "|".join(batch), "institutions.id": inst_id}
        )
    return {"source_id": source_id, "works_collected": len(work_ids), "cited_by_institution": total}
