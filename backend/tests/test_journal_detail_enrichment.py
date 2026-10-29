"""Detail enrichment tests: openalex/openaire/institution_metrics on the detail
bundle, per-year oa_* stats columns, and the paginated /works list."""

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import requires_db
from journal_browser.db import get_session
from journal_browser.main import app
from journal_browser.models import (
    HarvestRun,
    Institution,
    InstitutionWorksStats,
    Journal,
    SourceRecord,
    Work,
    WorkIdentity,
)

MAIN_ISSN = "1234-5678"
OTHER_ISSN = "2222-2222"

#: Raw venue source object; topic counts deliberately unsorted with a NULL.
SOURCE_PAYLOAD = {
    "id": "S123456",
    "issn_l": MAIN_ISSN,
    "cited_by_count": 100,
    "works_count": 42,
    "host_organization_name": "Widget Press",
    "counts_by_year": [
        {"year": 2023, "works_count": 5},
        {"year": 2021, "works_count": 7},
        {"year": 2019, "works_count": 2},
    ],
    "topics": [
        {
            "id": "T1",
            "display_name": "Small",
            "count": 2,
            "score": None,
            "subfield": {"id": "sf", "display_name": "S"},
            "field": {"id": "f", "display_name": "F"},
            "domain": {"id": "d", "display_name": "D"},
        },
        {"id": "T2", "display_name": "Big", "count": 9, "score": None},
        {"id": "T3", "display_name": "NullCount", "count": None, "score": None},
    ],
}

#: Works payloads: (2023, 9 cites, fwci null, retracted), (2021, 5, 1.5),
#: (no year, 7, 2.5). Window (2020+) drops the year-less W3: metrics must
#: be matched=2, avg=1.5, n=1, retracted=1, cited=14; order W2, W1.
WORKS_PAYLOADS = {
    "W1": {
        "id": "W1",
        "doi": "https://doi.org/10.1/w1",
        "display_name": "Old Work",
        "publication_year": 2021,
        "fwci": 1.5,
        "cited_by_count": 5,
        "open_access": {"oa_status": "gold", "is_oa": True},
        "is_retracted": False,
        "type": "article",
        "authorships": [{"author": {"display_name": "Secret Author"}}],
        "primary_location": {"source": {"issn_l": MAIN_ISSN}},
    },
    "W2": {
        "id": "https://openalex.org/W2",  # full-URL form must normalize to W2
        "display_name": "New Retracted",
        "publication_year": 2023,
        "fwci": None,
        "cited_by_count": 9,
        "open_access": {"oa_status": "closed", "is_oa": False},
        "is_retracted": True,
        "type": "article",
        "primary_location": {"source": {"issn_l": MAIN_ISSN}},
    },
    "W3": {
        "id": "W3",
        "display_name": "No Year",
        "fwci": 2.5,
        "cited_by_count": 7,
        "is_retracted": False,
        "type": "preprint",
        "primary_location": {"source": {"issn_l": MAIN_ISSN}},
    },
    "W4": {  # belongs to OTHER_ISSN; must not leak into MAIN_ISSN numbers
        "id": "W4",
        "display_name": "Other Journal Work",
        "publication_year": 2022,
        "fwci": None,
        "cited_by_count": 3,
        "is_retracted": False,
        "type": "article",
        "primary_location": {"source": {"issn_l": OTHER_ISSN}},
    },
}


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
async def api(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with maker() as session:
        session.add_all([_journal(MAIN_ISSN), _journal(OTHER_ISSN)])
        home = Institution(name="Test U", code="tu", active=True)
        session.add(home)
        await session.flush()
        # works_stats records are institution-scoped via their harvest run.
        run = HarvestRun(
            source="openalex", entity_type="test", config_fingerprint="t",
            institution_id=home.id,
        )
        oa_run = HarvestRun(source="openaire", entity_type="test", config_fingerprint="t")
        session.add_all([run, oa_run])
        await session.flush()

        session.add(
            SourceRecord(
                source="openalex",
                entity_type="sources",
                source_pk="S123456",
                payload=SOURCE_PAYLOAD,
                content_hash="v1",
                harvest_run_id=run.id,
            )
        )
        # Latest + a stale duplicate version of W1: only the newest must count.
        session.add_all(
            [
                SourceRecord(
                    source="openalex",
                    entity_type="works_stats",
                    source_pk=pk,
                    payload=payload,
                    content_hash=f"{pk}-v1",
                    harvest_run_id=run.id,
                    harvested_at=datetime(2026, 1, 2, tzinfo=UTC),
                )
                for pk, payload in WORKS_PAYLOADS.items()
            ]
        )
        stale = dict(WORKS_PAYLOADS["W1"], cited_by_count=999)
        session.add(
            SourceRecord(
                source="openalex",
                entity_type="works_stats",
                source_pk="W1",
                payload=stale,
                content_hash="W1-v0",
                harvest_run_id=run.id,
                harvested_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )

        # OpenAIRE: u1 matched twice (distinct works must dedupe), u2 once;
        # u3 belongs to the other journal.
        for uuid, issn in (("u1", MAIN_ISSN), ("u2", MAIN_ISSN), ("u3", OTHER_ISSN)):
            session.add(
                Work(
                    institution_id=home.id,
                    pure_uuid=uuid,
                    title=f"T {uuid}",
                    norm_title=f"t {uuid}",
                    year=2021,
                    journal_issn_l=issn,
                    first_seen_run=oa_run.id,
                    last_seen_run=oa_run.id,
                )
            )
        session.add_all(
            [
                WorkIdentity(
                    institution_id=home.id,
                    source="openaire",
                    source_pk="W1",
                    work_id="u1",
                    matched_by="doi",
                ),
                WorkIdentity(
                    institution_id=home.id,
                    source="openaire",
                    source_pk="W9",
                    work_id="u1",
                    matched_by="doi",
                ),
                WorkIdentity(
                    institution_id=home.id,
                    source="openaire",
                    source_pk="W2",
                    work_id="u2",
                    matched_by="doi",
                ),
                WorkIdentity(
                    institution_id=home.id,
                    source="openaire",
                    source_pk="W4",
                    work_id="u3",
                    matched_by="doi",
                ),
            ]
        )

        session.add_all(
            [
                InstitutionWorksStats(
                    institution_id=home.id,
                    source="pure_canon",
                    issn_l=MAIN_ISSN,
                    year=2021,
                    works_count=10,
                ),
                InstitutionWorksStats(
                    institution_id=home.id,
                    source="openalex_institution_filter",
                    issn_l=MAIN_ISSN,
                    year=2021,
                    works_count=12,
                    oa_gold=3,
                    oa_hybrid=2,
                    oa_green=4,
                    oa_bronze=1,
                    oa_diamond=1,
                    oa_closed=1,
                ),
                InstitutionWorksStats(
                    institution_id=home.id,
                    source="openalex_institution_filter",
                    issn_l=MAIN_ISSN,
                    year=2022,
                    works_count=5,
                    oa_green=5,
                ),
            ]
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.clear()


@requires_db
async def test_works_pagination_and_sort(api):
    r = await api.get(f"/api/v1/tu/journals/{MAIN_ISSN}/works", params={"page_size": 2})
    assert r.status_code == 200
    body = r.json()
    # W3 has no year and falls outside the data window.
    assert [i["id"] for i in body["items"]] == ["W2", "W1"]
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["page_size"] == 2

    r = await api.get(f"/api/v1/tu/journals/{MAIN_ISSN}/works", params={"page": 2, "page_size": 2})
    body = r.json()
    assert [i["id"] for i in body["items"]] == []

    r = await api.get(f"/api/v1/tu/journals/{MAIN_ISSN}/works", params={"page": 4, "page_size": 2})
    assert r.json()["items"] == []
    assert r.json()["total"] == 2


@requires_db
async def test_works_page_size_capped_at_50(api):
    r = await api.get(f"/api/v1/tu/journals/{MAIN_ISSN}/works", params={"page_size": 51})
    assert r.status_code == 422


@requires_db
async def test_works_404_unknown_journal(api):
    r = await api.get("/api/v1/tu/journals/0000-0000/works")
    assert r.status_code == 404


@requires_db
async def test_works_item_shape(api):
    r = await api.get(f"/api/v1/tu/journals/{MAIN_ISSN}/works")
    item = r.json()["items"][0]  # W2
    assert item == {
        "id": "W2",
        "url": "https://openalex.org/W2",
        "doi": None,
        "title": "New Retracted",
        "year": 2023,
        "oa_status": "closed",
        "fwci": None,
        "cited_by_count": 9,
        "is_retracted": True,
        "type": "article",
        "work_type": None,
        "in_openalex": True,
    }
    # Stale W1 version (cited 999) must not surface, authorships must never.
    w1 = next(i for i in r.json()["items"] if i["id"] == "W1")
    assert w1["cited_by_count"] == 5
    assert w1["url"] == "https://openalex.org/W1"
    assert w1["doi"] == "https://doi.org/10.1/w1"
    assert w1["oa_status"] == "gold"
    assert "authorships" not in r.text


@requires_db
async def test_detail_enrichment(api):
    r = await api.get(f"/api/v1/tu/journals/{MAIN_ISSN}")
    assert r.status_code == 200
    body = r.json()

    openalex = body["openalex"]
    assert openalex["id"] == "S123456"
    assert openalex["url"] == "https://openalex.org/S123456"
    assert openalex["cited_by_count"] == 100
    assert openalex["works_count"] == 42
    assert openalex["host_organization_name"] == "Widget Press"
    assert openalex["first_publication_year"] == 2019
    assert openalex["last_publication_year"] == 2023
    assert [t["display_name"] for t in openalex["topics"]] == ["Big", "Small", "NullCount"]
    # Hierarchy objects pass through verbatim where the source has them;
    # absent hierarchy keys serialize as explicit nulls (typed model).
    assert openalex["topics"][1]["subfield"] == {"id": "sf", "display_name": "S"}
    assert openalex["topics"][0]["subfield"] is None

    assert body["openaire"] == {"matched_works": 2}

    assert body["institution_metrics"] == {
        "openalex_matched": 2,
        "fwci_avg": 1.5,
        "fwci_n": 1,
        "retracted": 1,
        "cited_total": 14,
        "canonical_total": None,
        "canonical_retracted": None,
        "canonical_oa": None,
    }

    for key in ("openalex", "openaire", "works"):
        assert key in body["attribution"]
    assert body["attribution"]["openalex"]["url"] == "https://openalex.org"
    assert body["attribution"]["openaire"]["url"] == "https://openaire.eu"
    assert "Twente" in body["attribution"]["works"]["source"]


@requires_db
async def test_detail_homepage_prefers_doaj(api, db):
    """DOAJ is the canon homepage source; OpenAlex fills the gap."""
    from sqlalchemy import select

    result = await db.execute(select(Journal).where(Journal.issn_l == MAIN_ISSN))
    row = result.scalar_one()
    row.homepage_url = "https://openalex.example/journal"
    row.doaj_homepage_url = "https://doaj.example/journal"
    await db.commit()

    r = await api.get(f"/api/v1/tu/journals/{MAIN_ISSN}")
    assert r.json()["homepage_url"] == "https://doaj.example/journal"

    row.doaj_homepage_url = None
    await db.commit()
    r = await api.get(f"/api/v1/tu/journals/{MAIN_ISSN}")
    assert r.json()["homepage_url"] == "https://openalex.example/journal"


@requires_db
async def test_detail_enrichment_without_source_rows(api):
    r = await api.get(f"/api/v1/tu/journals/{OTHER_ISSN}")
    assert r.status_code == 200
    body = r.json()
    assert body["openalex"] is None
    # u3 matched once for this journal.
    assert body["openaire"] == {"matched_works": 1}
    # Only W4 (no fwci) belongs to this journal.
    assert body["institution_metrics"] == {
        "openalex_matched": 1,
        "fwci_avg": None,
        "fwci_n": 0,
        "retracted": 0,
        "cited_total": 3,
        "canonical_total": None,
        "canonical_retracted": None,
        "canonical_oa": None,
    }


@requires_db
async def test_stats_rows_carry_oa_columns(api):
    r = await api.get(f"/api/v1/tu/journals/{MAIN_ISSN}")
    stats = {s["year"]: s for s in r.json()["stats"]}
    assert set(stats) == {2021, 2022}
    for year in stats:
        assert {"oa_gold", "oa_hybrid", "oa_green", "oa_bronze", "oa_diamond", "oa_closed"} <= (
            stats[year].keys()
        )
    # 2021: pure_canon works count, OpenAlex OA split.
    assert stats[2021]["works_count"] == 10
    assert stats[2021]["works_count_source"] == "pure_canon"
    assert (stats[2021]["oa_gold"], stats[2021]["oa_hybrid"], stats[2021]["oa_green"]) == (3, 2, 4)
    assert (stats[2021]["oa_bronze"], stats[2021]["oa_diamond"], stats[2021]["oa_closed"]) == (
        1,
        1,
        1,
    )
    # 2022: OpenAlex-only year keeps its own count.
    assert stats[2022]["works_count"] == 5
    assert stats[2022]["oa_green"] == 5
