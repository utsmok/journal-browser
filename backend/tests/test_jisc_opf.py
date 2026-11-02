"""Jisc Open Policy Finder harvester tests (MockTransport only, no live calls)."""

import httpx
import pytest

from journal_browser.config import reset_settings_cache
from journal_browser.harvest import jisc_opf as jisc


async def test_jisc_retrieve_page_sends_documented_params():
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"items": [], "totalHits": 0})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await jisc.retrieve_page(client, filters=[["issn", "equals", "0043-1354"]])
    assert seen["item-type"] == "publication"
    assert seen["format"] == "Json"
    assert seen["filter"] == '[["issn","equals","0043-1354"]]'


class _FakeIngest:
    """Duck-typed IngestSession recording ingested pks."""

    def __init__(self) -> None:
        self.pks: list[str] = []

    async def ingest_records(self, records: list[tuple[str, dict]]) -> int:
        self.pks.extend(pk for pk, _ in records)
        return len(records)

    async def commit(self) -> None:
        return None


async def test_jisc_sweep_follows_next_search_after():
    pages = [
        {
            "items": [{"system_metadata": {"id": 1}}, {"system_metadata": {"id": 2}}],
            "next_search_after": [9],
        },
        {"items": [{"system_metadata": {"id": 3}}], "next_search_after": None},
    ]
    seen_search_after: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_search_after.append(request.url.params.get("search_after"))
        return httpx.Response(200, json=pages[len(seen_search_after) - 1])

    ingest = _FakeIngest()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        stats = await jisc.sweep_type(client, ingest, "publisher", sleep_s=0)
    assert ingest.pks == ["1", "2", "3"]
    assert seen_search_after == [None, "[9]"]
    assert stats == {"item_type": "publisher", "pages": 2, "records": 3, "skipped": 0}


async def test_jisc_sweep_type_caps_records():
    page = {
        "items": [{"system_metadata": {"id": n}} for n in range(3)],
        "next_search_after": [1],
    }
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json=page)

    ingest = _FakeIngest()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        stats = await jisc.sweep_type(client, ingest, "publisher", sleep_s=0, max_records=2)
    assert ingest.pks == ["0", "1"]
    assert requests == 1
    assert stats == {"item_type": "publisher", "pages": 1, "records": 2, "skipped": 0}


def _empty_pages_handler() -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [], "totalHits": 0})

    return httpx.MockTransport(handler)


async def test_jisc_harvest_all_only_publisher(monkeypatch, tmp_path):
    # Overlay off + explicit key: settings.yaml pins whatever the live file has.
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "no-overlay.yaml"))
    monkeypatch.setenv("JB_JISC_API_KEY", "test-key")
    reset_settings_cache()
    calls: list[tuple[str, str, str]] = []

    async def fake_run_harvest(source, entity_type, filter_set, config, body, session):
        calls.append((source, entity_type, filter_set))
        return await body(_FakeIngest())

    monkeypatch.setattr(jisc, "run_harvest", fake_run_harvest)
    real_async_client = jisc.httpx.AsyncClient

    def mock_async_client(**kwargs):
        kwargs["transport"] = _empty_pages_handler()
        return real_async_client(**kwargs)

    monkeypatch.setattr(jisc.httpx, "AsyncClient", mock_async_client)
    results = await jisc.harvest_all(None, only="publisher")
    reset_settings_cache()
    assert calls == [("jisc_opf", "publisher", "all")]
    assert results == {
        "publisher": {"item_type": "publisher", "pages": 1, "records": 0, "skipped": 0}
    }


async def test_jisc_harvest_all_default_sweeps_all_types(monkeypatch, tmp_path):
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "no-overlay.yaml"))
    monkeypatch.setenv("JB_JISC_API_KEY", "test-key")
    reset_settings_cache()
    calls: list[str] = []

    async def fake_run_harvest(source, entity_type, filter_set, config, body, session):
        calls.append(entity_type)
        return await body(_FakeIngest())

    monkeypatch.setattr(jisc, "run_harvest", fake_run_harvest)
    real_async_client = jisc.httpx.AsyncClient

    def mock_async_client(**kwargs):
        kwargs["transport"] = _empty_pages_handler()
        return real_async_client(**kwargs)

    monkeypatch.setattr(jisc.httpx, "AsyncClient", mock_async_client)
    results = await jisc.harvest_all(None)
    reset_settings_cache()
    assert calls == list(jisc.SWEEP_TYPES)
    assert list(results) == list(jisc.SWEEP_TYPES)


async def test_jisc_harvest_all_rejects_unknown_type():
    with pytest.raises(ValueError, match="unknown item type"):
        await jisc.harvest_all(None, only="not-a-type")
