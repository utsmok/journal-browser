"""Docs surface: markdown block parser + /api/v1/docs GETs + admin edits."""

import hashlib
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import requires_db
from journal_browser.config import reset_settings_cache
from journal_browser.db import get_session
from journal_browser.docs import parse_blocks
from journal_browser.main import app

PASSWORD = "test-admin-pw"
REPO_DOCS = Path(__file__).resolve().parents[2] / "docs"


# ── Parser ─────────────────────────────────────────────────────────────────


def test_parse_headings_and_paragraph():
    blocks = parse_blocks("# Title\n\nSome text.\nMore text.")
    assert blocks == [
        {"type": "heading", "level": 1, "text": "# Title"},
        {"type": "paragraph", "text": "Some text.\nMore text."},
    ]


def test_parse_table_list_quote_hr():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n\n- one\n- two\n\n> quoted\n\n---\n"
    types = [b["type"] for b in parse_blocks(md)]
    assert types == ["table", "list", "quote", "hr"]
    assert parse_blocks(md)[1]["text"] == "- one\n- two"


def test_parse_fence_keeps_blank_lines_and_lang():
    blocks = parse_blocks("```python\nx = 1\n\ny = 2\n```\n\nAfter.")
    assert len(blocks) == 2
    assert blocks[0]["type"] == "code"
    assert blocks[0]["lang"] == "python"
    assert blocks[0]["text"] == "```python\nx = 1\n\ny = 2\n```"
    assert blocks[1]["text"] == "After."


# ── Routers ────────────────────────────────────────────────────────────────


@pytest.fixture
async def docs_api(db_engine, monkeypatch, tmp_path):
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "settings.yaml"))
    monkeypatch.setenv("JB_DOCS_DIR", str(REPO_DOCS))
    reset_settings_cache()
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.clear()
    reset_settings_cache()


async def _login(client: AsyncClient) -> dict[str, str]:
    r = await client.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


@requires_db
async def test_list_orders_overview_first(docs_api):
    r = await docs_api.get("/api/v1/docs")
    assert r.status_code == 200
    docs = r.json()
    assert docs[0]["slug"] == "overview"
    assert docs[0]["group"] == "overview"
    assert docs[0]["order"] == 0
    sources = [d for d in docs if d["group"] == "sources"]
    assert sources and sources == sorted(sources, key=lambda d: d["order"])
    assert all(d["edits"] == 0 for d in docs)
    assert all(d["title"] for d in docs)


@requires_db
async def test_detail_blocks_and_unknown_slug(docs_api):
    r = await docs_api.get("/api/v1/docs/OVERVIEW")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "overview"
    assert body["group"] == "overview"
    assert body["blocks"]
    assert [b["key"] for b in body["blocks"]] == [f"b{i:03d}" for i in range(len(body["blocks"]))]
    assert all(
        b["type"] in ("heading", "paragraph", "list", "table", "code", "quote", "hr")
        for b in body["blocks"]
    )

    r = await docs_api.get("/api/v1/docs/no-such-doc")
    assert r.status_code == 404


@requires_db
async def test_edit_round_trip(docs_api):
    slug = "OVERVIEW"
    detail = (await docs_api.get(f"/api/v1/docs/{slug}")).json()
    block = next(b for b in detail["blocks"] if b["type"] == "paragraph")
    headers = await _login(docs_api)

    r = await docs_api.put(
        f"/api/v1/admin/docs/{slug}/edits",
        headers=headers,
        json={
            "block_key": block["key"],
            "original_hash": hashlib.sha256(block["text"].encode()).hexdigest(),
            "replacement": "A replacement paragraph.",
        },
    )
    assert r.status_code == 200
    assert r.json() == {"slug": "overview", "block_key": block["key"], "edited": True}

    detail = (await docs_api.get(f"/api/v1/docs/{slug}")).json()
    edited = next(b for b in detail["blocks"] if b["key"] == block["key"])
    assert edited["text"] == "A replacement paragraph."
    assert edited["edited"] is True

    listing = (await docs_api.get("/api/v1/docs")).json()
    assert next(d for d in listing if d["slug"] == "overview")["edits"] >= 1

    r = await docs_api.delete(f"/api/v1/admin/docs/{slug}/edits/{block['key']}", headers=headers)
    assert r.status_code == 204
    detail = (await docs_api.get(f"/api/v1/docs/{slug}")).json()
    restored = next(b for b in detail["blocks"] if b["key"] == block["key"])
    assert restored["text"] == block["text"]
    assert restored["edited"] is False


@requires_db
async def test_put_rejects_empty_replacement_and_unknown_slug(docs_api):
    headers = await _login(docs_api)
    r = await docs_api.put(
        "/api/v1/admin/docs/OVERVIEW/edits",
        headers=headers,
        json={"block_key": "b000", "original_hash": "x", "replacement": "   "},
    )
    assert r.status_code == 422
    r = await docs_api.put(
        "/api/v1/admin/docs/no-such-doc/edits",
        headers=headers,
        json={"block_key": "b000", "original_hash": "x", "replacement": "text"},
    )
    assert r.status_code == 404


@requires_db
async def test_edit_requires_admin(docs_api):
    r = await docs_api.put(
        "/api/v1/admin/docs/OVERVIEW/edits",
        json={"block_key": "b000", "original_hash": "x", "replacement": "text"},
    )
    assert r.status_code == 401
