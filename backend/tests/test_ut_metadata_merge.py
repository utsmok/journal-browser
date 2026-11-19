"""Works-tab population tests (services.ut_metadata helpers + API path).

The pure bucket/sort logic runs everywhere (no ut-metadata dependency). The
tab itself serves the works-table population (see test_data_windows.py for
the card-vs-tab parity regression); here the API path is exercised through
the request cycle, including the detail metrics.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.db import get_session
from journal_browser.main import app
from journal_browser.models import (
    Author,
    HarvestRun,
    Institution,
    OpenalexWork,
    Work,
    WorkPureAuthor,
)
from journal_browser.services import ut_metadata as utmd

# ── Pure logic (no database) ───────────────────────────────────────────────


def test_oa_buckets():
    rows = [
        {"oa_status": "gold"},
        {"oa_status": "gold"},
        {"oa_status": "closed"},
        {"oa_status": None},
        {"oa_status": "exotic-new-value"},
    ]
    assert utmd.oa_buckets(rows) == {
        "gold": 2,
        "hybrid": 0,
        "green": 0,
        "bronze": 0,
        "diamond": 0,
        "closed": 1,
        "unknown": 2,
    }


def test_sort_order_year_cited_title():
    items = [
        {"year": 2023, "cited_by_count": 1, "title": "zzz"},
        {"year": None, "cited_by_count": 99, "title": "no year"},
        {"year": 2023, "cited_by_count": 9, "title": "B title"},
        {"year": 2023, "cited_by_count": 9, "title": "a title"},
        {"year": 2021, "cited_by_count": 5, "title": "old"},
    ]
    ordered = utmd.sort_work_items(items)
    assert ordered == [
        {"year": 2023, "cited_by_count": 9, "title": "a title"},
        {"year": 2023, "cited_by_count": 9, "title": "B title"},
        {"year": 2023, "cited_by_count": 1, "title": "zzz"},
        {"year": 2021, "cited_by_count": 5, "title": "old"},
        {"year": None, "cited_by_count": 99, "title": "no year"},
    ]


# ── API path: works tab + detail metrics over the works-table corpus ──────


@pytest.fixture
async def api(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with maker() as session:
        home = Institution(name="Test U", code="tu", active=True, data_window_start=2020)
        session.add(home)
        await session.flush()
        session.add(journal_factory("1234-5678", search_text=None))
        run = HarvestRun(
            source="pure",
            entity_type="work",
            status="completed",
            institution_id=home.id,
            config_fingerprint="t",
        )
        session.add(run)
        await session.flush()
        session.add_all(
            [
                Work(
                    institution_id=home.id,
                    pure_uuid="w-doi",
                    title="Doi Work",
                    norm_title="doi work",
                    year=2021,
                    work_type="article",
                    doi_normalized="10.1/one",
                    oa_status="green",
                    journal_issn_l="1234-5678",
                    first_seen_run=run.id,
                    last_seen_run=run.id,
                ),
                Work(
                    institution_id=home.id,
                    pure_uuid="w-nodoi",
                    title="No Doi Work",
                    norm_title="no doi work",
                    year=2020,
                    work_type="article",
                    oa_status="green",
                    journal_issn_l="1234-5678",
                    first_seen_run=run.id,
                    last_seen_run=run.id,
                ),
            ]
        )
        session.add_all(
            [
                # Store enrichment for the DOI'd work (most-open record).
                OpenalexWork(
                    institution_id=home.id,
                    w_id="W1",
                    doi_normalized="10.1/one",
                    title="Doi Work",
                    year=2021,
                    work_type="article",
                    venue_issn_l="1234-5678",
                    oa_status="gold",
                    fwci=1.5,
                    cited_by_count=5,
                    is_retracted=True,
                ),
                # Merged-profile twin of W1: lower openness, must lose.
                OpenalexWork(
                    institution_id=home.id,
                    w_id="W1b",
                    doi_normalized="10.1/one",
                    title="Doi Work (closed copy)",
                    year=2021,
                    work_type="article",
                    venue_issn_l="1234-5678",
                    oa_status="closed",
                    cited_by_count=5,
                ),
                # Store-only row: not in Pure, never ours.
                OpenalexWork(
                    institution_id=home.id,
                    w_id="W9",
                    doi_normalized="10.9/store-only",
                    title="Store Only",
                    year=2021,
                    work_type="article",
                    venue_issn_l="1234-5678",
                    cited_by_count=99,
                ),
            ]
        )
        session.add_all(
            [
                Author(
                    institution_id=home.id,
                    pure_uuid="a1",
                    name="Alice Alpha",
                    research_group="Group X",
                    confirmed=True,
                    n_works=1,
                ),
                Author(
                    institution_id=home.id,
                    pure_uuid="a2",
                    name="Bob Beta",
                    confirmed=True,
                    n_works=1,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                WorkPureAuthor(
                    institution_id=home.id,
                    work_pure_uuid="w-doi",
                    person_uuid="a1",
                    position=0,
                ),
                WorkPureAuthor(
                    institution_id=home.id,
                    work_pure_uuid="w-nodoi",
                    person_uuid="a2",
                    position=0,
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
async def test_works_tab_enrichment_and_authors(api, client):
    r = await client.get("/api/v1/tu/journals/1234-5678/works")
    assert r.status_code == 200
    body = r.json()
    # The Pure population: DOI'd + DOI-less; the store-only row stays out.
    assert body["total"] == 2
    items = body["items"]
    assert [i["title"] for i in items] == ["Doi Work", "No Doi Work"]
    doi_item, nodoi_item = items
    assert doi_item["in_openalex"] is True
    assert doi_item["id"] == "W1"  # most-open record wins the merged twin
    assert doi_item["oa_status"] == "gold"
    assert doi_item["fwci"] == 1.5
    assert doi_item["is_retracted"] is True
    assert doi_item["doi"] == "https://doi.org/10.1/one"
    assert doi_item["ut_authors"] == [{"id": "a1", "name": "Alice Alpha"}]
    assert doi_item["ut_groups"] == [{"name": "Group X"}]
    assert nodoi_item["in_openalex"] is False
    assert nodoi_item["id"] is None
    assert nodoi_item["oa_status"] == "green"  # Pure's own OA status fallback
    assert nodoi_item["ut_authors"] == [{"id": "a2", "name": "Bob Beta"}]
    assert nodoi_item["ut_groups"] == []


@requires_db
async def test_detail_metrics_canonical_side_matches_tab(api, client):
    r = await client.get("/api/v1/tu/journals/1234-5678")
    assert r.status_code == 200
    metrics = r.json()["institution_metrics"]
    works = await client.get("/api/v1/tu/journals/1234-5678/works")
    assert metrics["canonical_total"] == works.json()["total"] == 2
    assert metrics["canonical_retracted"] == 1
    assert metrics["canonical_oa"] == {
        "gold": 1,  # store OA status wins for the DOI'd work
        "hybrid": 0,
        "green": 1,  # Pure's own status for the DOI-less work
        "bronze": 0,
        "diamond": 0,
        "closed": 0,
        "unknown": 0,
    }
    # Existing OpenAlex-view numbers untouched.
    assert metrics["openalex_matched"] == 3
    assert metrics["fwci_n"] == 1
