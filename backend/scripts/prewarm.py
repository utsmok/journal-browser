"""Warm the API caches and Postgres buffers for every active institution.

The first request after a deploy or a nightly wave pays for cold Postgres
pages, the embedding model, and the in-process facet, publisher, and orgunit
caches: several seconds on the big pages. This script requests the pages a
visitor reaches first, so the first real visitor does not pay that cost.

Run inside the stack (the scheduler runs it daily after the wave):

    docker compose exec scheduler uv run --no-dev python scripts/prewarm.py

JB_PREWARM_BASE overrides the API base (default http://backend:8000/api/v1).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request

BASE = os.environ.get("JB_PREWARM_BASE", "http://backend:8000/api/v1").rstrip("/")
TIMEOUT_S = 120
TOP_N = 10


def get(path: str) -> object | None:
    url = f"{BASE}{path}"
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:
            body = resp.read()
        status = resp.status
    except Exception as exc:  # report and keep warming the rest
        print(f"FAIL {path}: {exc}", flush=True)
        return None
    print(f"{status} {time.monotonic() - started:6.2f}s {path}", flush=True)
    try:
        return json.loads(body)
    except ValueError:
        return None


def items(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        found = payload.get("items")
        return found if isinstance(found, list) else []
    return payload if isinstance(payload, list) else []


def q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def warm_institution(code: str) -> None:
    root = f"/{code}"
    get(f"{root}/meta/freshness")
    journals = items(get(f"{root}/journals?sort=institution_works&limit=50"))
    get(f"{root}/journals?deal=covered&limit=50")
    for query in ("water", "machine learning", "open access"):
        get(f"{root}/journals/semantic-search?q={q(query)}")
    for journal in journals[:TOP_N]:
        issn = journal.get("issn_l")
        if issn:
            get(f"{root}/journals/{issn}")
            get(f"{root}/journals/{issn}/similar")
    get(f"{root}/deals")
    get(f"{root}/funders")
    get(f"{root}/collaborations")
    get(f"{root}/collaborations/map")
    for publisher in items(get(f"{root}/publishers?limit=50"))[:TOP_N]:
        name = publisher.get("name")
        if name:
            get(f"{root}/publishers/{q(name)}")
    orgunits = get(f"{root}/orgunits")
    for unit in items(orgunits):
        if unit.get("level") == "faculty" and unit.get("name"):
            get(f"{root}/orgunits/faculty/{q(unit['name'])}")
    get(f"{root}/authors?limit=50")


def main() -> int:
    institutions = items(get("/institutions"))
    if not institutions:
        print("prewarm: no institutions answered; is the backend up?", flush=True)
        return 1
    for inst in institutions:
        code = inst.get("code")
        if code:
            warm_institution(code)
    return 0


if __name__ == "__main__":
    sys.exit(main())
