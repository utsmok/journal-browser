"""Usage geo enrichment job: batching, private-IP skip, mocked writes."""

import importlib.util
import json
from pathlib import Path

import httpx
from sqlalchemy import select

from conftest import requires_db
from journal_browser.models import UsageEvent

ROOT = Path(__file__).resolve().parents[1]


def _load_job(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "jobs" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


geo = _load_job("enrich_usage_geo")


def test_plan_batches():
    ips = [f"203.0.113.{i}" for i in range(250)]
    batches = geo.plan_batches(ips)
    assert [len(b) for b in batches] == [100, 100, 50]
    assert batches[0][0] == "203.0.113.0" and batches[2][-1] == "203.0.113.249"
    assert geo.plan_batches([]) == []


def test_is_trackable():
    assert geo.is_trackable("8.8.8.8")
    assert geo.is_trackable("2001:4860:4860::8888")
    assert not geo.is_trackable("10.0.0.1")
    assert not geo.is_trackable("192.168.1.1")
    assert not geo.is_trackable("127.0.0.1")
    assert not geo.is_trackable("169.254.1.1")
    assert not geo.is_trackable("224.0.0.1")
    assert not geo.is_trackable("not-an-ip")


@requires_db
async def test_enrich_writes_countries_and_counts_failures(db):
    db.add(UsageEvent(session_id="s1", event_type="page_view", path="/x", ip="8.8.8.8"))
    db.add(UsageEvent(session_id="s1", event_type="page_view", path="/x", ip="1.1.1.1"))
    db.add(UsageEvent(session_id="s1", event_type="page_view", path="/x", ip="10.0.0.5"))
    await db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        wanted = json.loads(request.content)
        codes = {"8.8.8.8": "NL", "1.1.1.1": None}
        return httpx.Response(
            200,
            json=[
                (
                    {"status": "success", "countryCode": codes[q], "query": q}
                    if codes.get(q)
                    else {"status": "fail", "query": q}
                )
                for q in wanted
            ],
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        stats = await geo.enrich(
            db, sleep=0, fetch=lambda batch: geo.fetch_countries(client, batch)
        )

    assert stats == {"resolved": 1, "batches": 1, "skipped_private": 1, "failed": 1}
    rows = (await db.scalars(select(UsageEvent))).all()
    by_ip = {str(row.ip): row.country for row in rows}
    assert by_ip == {"8.8.8.8": "NL", "1.1.1.1": None, "10.0.0.5": None}


@requires_db
async def test_enrich_limit_caps_batches(db):
    for i in range(150):
        ip = f"8.8.{i // 256}.{i % 256}"
        db.add(UsageEvent(session_id="s1", event_type="page_view", path="/x", ip=ip))
    await db.commit()

    async def fetch(batch):
        return dict.fromkeys(batch, "US")

    stats = await geo.enrich(db, limit=1, sleep=0, fetch=fetch)
    assert stats["batches"] == 1
    assert stats["resolved"] == 100
    remaining = (await db.scalars(select(UsageEvent).where(UsageEvent.country.is_(None)))).all()
    assert len(remaining) == 50
