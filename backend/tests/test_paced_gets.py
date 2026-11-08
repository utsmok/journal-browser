"""paced_single_gets: free singleton lookups with start-slot pacing."""

import time

import pytest

from journal_browser.harvest.common import paced_single_gets


class _Fake404(Exception):
    def __init__(self):
        self.response = type("R", (), {"status_code": 404})()


class _Fake500(Exception):
    def __init__(self):
        self.response = type("R", (), {"status_code": 500})()


async def test_spacing_between_starts():
    starts: list[float] = []

    async def get(iid: str):
        starts.append(time.monotonic())
        return {"id": iid}

    out, failed = await paced_single_gets(get, ["a", "b", "c"], min_interval_s=0.03)
    assert failed == {}
    assert out == {"a": {"id": "a"}, "b": {"id": "b"}, "c": {"id": "c"}}
    # Starts are spaced by the interval — no unspaced burst.
    gaps = [b - a for a, b in zip(sorted(starts), sorted(starts)[1:], strict=False)]
    assert all(g >= 0.02 for g in gaps)


async def test_404_is_isolated_miss():
    async def get(iid: str):
        if iid == "gone":
            raise _Fake404()
        return {"id": iid}

    out, failed = await paced_single_gets(get, ["gone", "here"])
    assert out["gone"] is None
    assert out["here"] == {"id": "here"}
    assert failed == {}


async def test_failure_isolation_and_all_failed_raises():
    async def get(iid: str):
        if iid == "bad":
            raise _Fake500()
        return {"id": iid}

    out, failed = await paced_single_gets(get, ["bad", "good"])
    assert out["bad"] is None
    assert isinstance(failed["bad"], _Fake500)

    async def all_bad(iid: str):
        raise _Fake500()

    with pytest.raises(RuntimeError, match="all 2 lookups failed"):
        await paced_single_gets(all_bad, ["x", "y"])


async def test_empty_ids_noop():
    out, failed = await paced_single_gets(lambda iid: None, [])
    assert out == {} and failed == {}
