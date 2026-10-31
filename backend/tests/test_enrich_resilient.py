"""Regression: one rejected DOI in a batch DOI-lookup used to fail the
whole enrichment run (live enrich died on a 49-DOI Crossref filter)."""

import httpx
import pytest
from bibliofabric.exceptions import APIError, RateLimitError

from journal_browser.harvest.enrich import _batch_by_doi_resilient


def _api_error(status: int) -> APIError:
    return APIError(
        f"API request failed with status {status}",
        response=httpx.Response(status_code=status, request=httpx.Request("GET", "https://x.test")),
    )


async def test_rejected_batch_bisects_and_isolates_the_bad_doi():
    calls: list[list[str]] = []

    async def fetch(chunk):
        calls.append(list(chunk))
        if any(doi == "10.0.3.239/bad" for doi in chunk):
            raise _api_error(400)
        return {doi: {"doi": doi} for doi in chunk}

    stats: dict[str, int] = {}
    found = await _batch_by_doi_resilient(
        fetch, ["10.1/a", "10.1/b", "10.0.3.239/bad", "10.1/c"], stats
    )

    assert set(found) == {"10.1/a", "10.1/b", "10.1/c"}
    assert stats["dois_rejected"] == 1
    # The bisection must end at the single bad DOI.
    assert ["10.0.3.239/bad"] in calls


async def test_single_rejected_doi_is_counted_and_skipped():
    async def fetch(chunk):
        raise _api_error(400)

    stats: dict[str, int] = {}
    assert await _batch_by_doi_resilient(fetch, ["10.1/x"], stats) == {}
    assert stats["dois_rejected"] == 1


async def test_server_errors_raise_through():
    async def fetch(chunk):
        raise _api_error(500)

    with pytest.raises(APIError):
        await _batch_by_doi_resilient(fetch, ["10.1/a", "10.1/b"], {})


async def test_rate_limit_raises_through_without_bisection():
    async def fetch(chunk):
        raise RateLimitError("slow down")

    with pytest.raises(RateLimitError):
        await _batch_by_doi_resilient(fetch, ["10.1/a", "10.1/b"], {})
