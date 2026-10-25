"""ut-metadata integration tests.

The pure merge/bucket/sort logic and the API union path run everywhere (no
ut-metadata dependency). The live-database test only runs when
JB_TEST_UT_METADATA is set (its value is the ut-metadata DSN) — mirroring
the conftest loud opt-out convention.
"""

import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import requires_db
from journal_browser.db import get_session
from journal_browser.main import app
from journal_browser.models import HarvestRun, Journal, SourceRecord
from journal_browser.services import ut_metadata

# ── Pure logic (no database) ───────────────────────────────────────────────


def test_normalize_doi():
    assert ut_metadata.normalize_doi("HTTPS://DOI.org/10.1/ABC") == "10.1/abc"
    assert ut_metadata.normalize_doi("doi:10.1/x") == "10.1/x"
    assert ut_metadata.normalize_doi("  10.1/x  ") == "10.1/x"
    assert ut_metadata.normalize_doi("") is None
    assert ut_metadata.normalize_doi(None) is None


def test_oa_buckets():
    rows = [
        {"oa_status": "gold"},
        {"oa_status": "gold"},
        {"oa_status": "closed"},
        {"oa_status": None},
        {"oa_status": "exotic-new-value"},
    ]
    assert ut_metadata.oa_buckets(rows) == {
        "gold": 2,
        "hybrid": 0,
        "green": 0,
        "bronze": 0,
        "diamond": 0,
        "closed": 1,
        "unknown": 2,
    }


def _stats_item(**kw) -> dict:
    base = {
        "id": "W1",
        "url": "https://openalex.org/W1",
        "doi": "https://doi.org/10.1/one",
        "title": "Stats Title",
        "year": 2021,
        "oa_status": "green",
        "fwci": 1.5,
        "cited_by_count": 5,
        "is_retracted": False,
        "type": "article",
        "work_type": None,
        "in_openalex": True,
    }
    base.update(kw)
    return base


def _ut_row(**kw) -> dict:
    base = {
        "id": 42,
        "doi": "10.1/ONE",
        "title": "Canonical Title",
        "year": 2023,
        "work_type": "article",
        "oa_status": "gold",
        "cited_by_count": 12,
        "is_retracted": True,
    }
    base.update(kw)
    return base


def test_merge_doi_match_ut_wins_enriched_from_stats():
    merged = ut_metadata.merge_work_lists([_ut_row()], [_stats_item()])
    assert merged == [
        {
            "id": "W1",  # from works_stats
            "url": "https://openalex.org/W1",
            "doi": "10.1/ONE",  # ut-metadata row wins
            "title": "Canonical Title",
            "year": 2023,
            "oa_status": "gold",
            "fwci": 1.5,  # enrichment from works_stats
            "cited_by_count": 5,
            "is_retracted": True,
            "type": "article",
            "work_type": "article",
            "in_openalex": True,
        }
    ]


def test_merge_keeps_stats_only_and_doi_less_ut_rows():
    ut = [
        _ut_row(id=7, doi=None),
        _ut_row(id=8, doi="10.2/only-ut", cited_by_count=None),
    ]
    stats = [_stats_item(doi="https://doi.org/10.1/one")]
    merged = ut_metadata.merge_work_lists(ut, stats)
    assert merged == [
        {
            "id": "ut-7",
            "url": None,
            "doi": None,
            "title": "Canonical Title",
            "year": 2023,
            "oa_status": "gold",
            "fwci": None,
            "cited_by_count": 12,
            "is_retracted": True,
            "type": None,
            "work_type": "article",
            "in_openalex": False,
        },
        {
            "id": "ut-8",
            "url": "https://doi.org/10.2/only-ut",
            "doi": "10.2/only-ut",
            "title": "Canonical Title",
            "year": 2023,
            "oa_status": "gold",
            "fwci": None,
            "cited_by_count": 0,
            "is_retracted": True,
            "type": None,
            "work_type": "article",
            "in_openalex": False,
        },
        _stats_item(),
    ]


def test_merge_case_insensitive_doi_dedupes():
    merged = ut_metadata.merge_work_lists(
        [_ut_row(doi="10.9/same")], [_stats_item(doi="https://doi.org/10.9/SAME")]
    )
    assert len(merged) == 1
    assert merged[0]["in_openalex"] is True


def test_sort_order_year_cited_title():
    items = [
        {"year": 2023, "cited_by_count": 1, "title": "zzz"},
        {"year": None, "cited_by_count": 99, "title": "no year"},
        {"year": 2023, "cited_by_count": 9, "title": "B title"},
        {"year": 2023, "cited_by_count": 9, "title": "a title"},
        {"year": 2021, "cited_by_count": 5, "title": "old"},
    ]
    ordered = ut_metadata.sort_work_items(items)
    assert ordered == [
        {"year": 2023, "cited_by_count": 9, "title": "a title"},
        {"year": 2023, "cited_by_count": 9, "title": "B title"},
        {"year": 2023, "cited_by_count": 1, "title": "zzz"},
        {"year": 2021, "cited_by_count": 5, "title": "old"},
        {"year": None, "cited_by_count": 99, "title": "no year"},
    ]


# ── API path: union via a faked ut_works_for_journal ──────────────────────


def _journal(issn_l: str) -> Journal:
    return Journal(
        issn_l=issn_l,
        title=f"Journal {issn_l}",
        type="journal",
        is_oa=False,
        is_in_doaj=False,
        in_scimago=False,
        works_2020_plus=10,
    )


@pytest.fixture
async def api(db_engine, monkeypatch):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with maker() as session:
        run = HarvestRun(source="openalex", entity_type="test", config_fingerprint="t")
        session.add(run)
        session.add(_journal("1234-5678"))
        await session.flush()
        session.add_all(
            [
                # Merges with the faked ut-metadata row via DOI 10.1/one.
                SourceRecord(
                    source="openalex",
                    entity_type="works_stats",
                    source_pk="W1",
                    payload={
                        "id": "W1",
                        "doi": "https://doi.org/10.1/one",
                        "display_name": "Stats One",
                        "publication_year": 2021,
                        "fwci": 1.5,
                        "cited_by_count": 5,
                        "is_retracted": False,
                        "type": "article",
                        "primary_location": {"source": {"issn_l": "1234-5678"}},
                    },
                    content_hash="W1",
                    harvest_run_id=run.id,
                ),
                # Pure works_stats-only row (no ut-metadata counterpart).
                SourceRecord(
                    source="openalex",
                    entity_type="works_stats",
                    source_pk="W2",
                    payload={
                        "id": "W2",
                        "doi": "10.5/stats-only",
                        "display_name": "Stats Only",
                        "publication_year": 2021,
                        "cited_by_count": 5,
                        "is_retracted": False,
                        "type": "article",
                        "primary_location": {"source": {"issn_l": "1234-5678"}},
                    },
                    content_hash="W2",
                    harvest_run_id=run.id,
                ),
            ]
        )
        await session.commit()
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
async def client(api):
    async with AsyncClient(transport=ASGITransport(api), base_url="http://t") as c:
        yield c


@requires_db
async def test_works_union_and_detail_ut_metrics(api, client, monkeypatch):
    async def fake_ut_rows(issn_l, dsn=None):
        return [
            _ut_row(id=1, doi="10.1/one", oa_status="gold", is_retracted=True),
            _ut_row(id=2, doi="10.9/ut-only", cited_by_count=3, oa_status=None),
            _ut_row(id=3, doi="10.8/beyond-stats", year=None, cited_by_count=1, oa_status="hybrid"),
        ]

    monkeypatch.setattr(ut_metadata, "ut_works_for_journal", fake_ut_rows)

    r = await client.get("/api/v1/journals/1234-5678/works")
    assert r.status_code == 200
    body = r.json()
    # 1 merged (10.1/one) + 2 ut-only + 1 stats-only = 4; ut-3 has no year ->
    # last despite citing more than the 2021 stats-only row.
    assert body["total"] == 4
    items = body["items"]
    assert [i["id"] for i in items] == ["W1", "ut-2", "W2", "ut-3"]
    merged = items[0]
    assert merged["in_openalex"] is True
    assert merged["fwci"] == 1.5
    assert merged["is_retracted"] is True
    assert merged["year"] == 2023
    assert items[1]["in_openalex"] is False
    assert items[1]["cited_by_count"] == 3
    assert items[2]["in_openalex"] is True
    assert items[2]["work_type"] is None

    r = await client.get("/api/v1/journals/1234-5678")
    metrics = r.json()["twente_metrics"]
    assert metrics["ut_total"] == 3
    assert metrics["ut_retracted"] == 3
    assert metrics["ut_oa"] == {
        "gold": 1,
        "hybrid": 1,
        "green": 0,
        "bronze": 0,
        "diamond": 0,
        "closed": 0,
        "unknown": 1,
    }
    # Existing OpenAlex-view numbers untouched.
    assert metrics["openalex_matched"] == 2
    assert metrics["fwci_n"] == 1


@requires_db
async def test_ut_metadata_unavailable_degrades_to_stats_only(api, client, monkeypatch):
    async def unavailable(issn_l, dsn=None):
        return None  # what ut_works_for_journal returns when unset/unreachable

    monkeypatch.setattr(ut_metadata, "ut_works_for_journal", unavailable)

    r = await client.get("/api/v1/journals/1234-5678/works")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert all(i["in_openalex"] is True for i in body["items"])

    r = await client.get("/api/v1/journals/1234-5678")
    metrics = r.json()["twente_metrics"]
    assert (metrics["ut_total"], metrics["ut_retracted"], metrics["ut_oa"]) == (
        None,
        None,
        None,
    )


@requires_db
async def test_unreachable_dsn_returns_none():
    # Refused connection (closed port) must degrade, not raise: the
    # works endpoints keep serving works_stats-only.
    assert (
        await ut_metadata.ut_works_for_journal(
            "0043-1354", dsn="postgresql://ut_metadata:ut_metadata@localhost:5999/ut_metadata"
        )
        is None
    )


# ── Live ut-metadata (opt-in: JB_TEST_UT_METADATA=<dsn>) ──────────────────

requires_ut = pytest.mark.skipif(
    not os.environ.get("JB_TEST_UT_METADATA"),
    reason="JB_TEST_UT_METADATA unset: ut-metadata database tests skipped by explicit opt-out",
)


@requires_ut
async def test_ut_works_for_journal_live():
    rows = await ut_metadata.ut_works_for_journal("0043-1354")
    assert rows is not None
    assert len(rows) >= 50  # 60 on the current snapshot
    assert all(r["doi"] for r in rows)
    buckets = ut_metadata.oa_buckets(rows)
    assert sum(buckets.values()) == len(rows)
