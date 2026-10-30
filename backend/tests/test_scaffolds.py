"""Tests for the blocked scaffolds: citation batching + Jisc gating."""

import pytest

from journal_browser.config import reset_settings_cache
from journal_browser.harvest import journal_citations as jc


def _ingest_record_into_batches(work_id: str) -> dict:
    return {"id": f"https://openalex.org/{work_id}"}


class FakeWorks:
    """Minimal stand-in for aletheca's works client."""

    def __init__(self, work_ids: list[str], counts: dict[str, int]):
        self._work_ids = work_ids
        self._counts = counts

    async def iterate(self, page_size: int, filters: dict, select: str):
        for work_id in self._work_ids:
            yield _ingest_record_into_batches(work_id)

    async def count(self, filters: dict) -> int:
        return self._counts.get(filters.get("cites", ""), 0)


@pytest.mark.parametrize(
    ("n", "want"),
    [(0, 0), (1, 1), (99, 1), (100, 1), (101, 2), (250, 3)],
)
def test_batching_sizes(n, want):
    batches = list(jc.iter_batches([f"W{i}" for i in range(n)]))
    assert len(batches) == want
    assert all(len(b) <= jc.BATCH_SIZE for b in batches)
    assert [w for b in batches for w in b] == [f"W{i}" for i in range(n)]


async def test_count_citing_works_sums_batches():
    # 250 ids in 3 batches; counts keyed by the pipe-joined filter value.
    ids = [f"W{i}" for i in range(250)]
    counts = {frozenset(b): len(b) * 2 for b in jc.iter_batches(ids)}

    class BatchedCounts:
        async def count(self, filters: dict) -> int:
            return counts.get(frozenset(filters["cites"].split("|")), 0)

    total = await jc.count_citing_works(type("C", (), {"works": BatchedCounts()})(), ids)
    assert total == 500


async def test_collect_work_ids_caps_at_max():
    works = FakeWorks([f"W{i}" for i in range(50)], {})
    ids = await jc.collect_work_ids(type("C", (), {"works": works})(), "S123", max_works=10)
    assert len(ids) == 10
    assert ids[0] == "W0"


async def test_cited_by_institution_refuses_when_disabled(monkeypatch):
    monkeypatch.setenv("JB_ENABLE_JOURNAL_CITATIONS", "false")
    reset_settings_cache()
    with pytest.raises(RuntimeError, match="disabled"):
        await jc.cited_by_institution(None, "S123", "I94624287")
    reset_settings_cache()
