"""Serving cutover: the journal works tab and the author profile's
openalex-only merge read the local openalex_works store (work_sources),
degrading to works_stats-only / pure-only when the store is unbuilt and
no DSN is configured."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.db import get_session
from journal_browser.main import app
from journal_browser.models import (
    Author,
    AuthorWork,
    HarvestRun,
    OpenalexWork,
    Work,
)


def _oa_work(inst_id, w_id, *, doi, title, year, authorships, work_type="article"):
    return OpenalexWork(
        institution_id=inst_id,
        w_id=w_id,
        doi_normalized=doi,
        title=title,
        year=year,
        work_type=work_type,
        oa_status="gold",
        venue_issn_l="1234-5678",
        venue_name="Journal One",
        cited_by_count=4,
        authorships=authorships,
    )


@pytest.fixture
async def serving_api(db, institution_factory):
    """ut: journal 1234-5678 with two stored openalex works (one local-DOI
    twin), one pure work + author (openalex id a-alice)."""

    async def _override():
        async with async_sessionmaker(db.bind, expire_on_commit=False)() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    ut = await institution_factory(code="ut", data_window_start=2020)
    db.add(journal_factory("1234-5678"))
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()
    w = Work(
        institution_id=ut.id,
        pure_uuid="w1",
        title="Pure Work",
        norm_title="pure work",
        year=2023,
        doi_normalized="10.1000/shared",
        journal_issn_l="1234-5678",
        first_seen_run=run.id,
        last_seen_run=run.id,
    )
    db.add(w)
    await db.flush()  # the work FK must exist before author edges resolve
    db.add(
        Author(
            institution_id=ut.id,
            pure_uuid="alice-uuid",
            name="Alice Author",
            openalex_author_id="a-alice",
            openalex_ids=["a-alice"],
            n_works=1,
            confirmed=True,
        )
    )
    db.add(AuthorWork(institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid="w1"))
    db.add_all(
        [
            # canonical-only: DOI not held by the Pure population
            _oa_work(
                ut.id,
                "W-ghost",
                doi="10.9999/ghost",
                title="Ghost Work",
                year=2024,
                authorships=[{"a": "a-alice", "n": "Alice Author", "o": None}],
            ),
            # same publication as the Pure copy -> merged away
            _oa_work(
                ut.id,
                "W-twin",
                doi="10.1000/shared",
                title="Pure Work (OA twin)",
                year=2023,
                authorships=[{"a": "a-alice", "n": "Alice Author", "o": None}],
            ),
            # outside the publication window -> gated everywhere
            _oa_work(
                ut.id,
                "W-old",
                doi="10.9999/old",
                title="Old Work",
                year=2015,
                authorships=[{"a": "a-alice", "n": "Alice Author", "o": None}],
            ),
            # journal works tab row (journal map covers the whole table)
            _oa_work(
                ut.id,
                "W-journal",
                doi="10.9999/journal-only",
                title="Journal Only Work",
                year=2022,
                authorships=[],
            ),
        ]
    )
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.clear()


@requires_db
async def test_journal_works_tab_serves_local_rows(serving_api):
    r = await serving_api.get("/api/v1/ut/journals/1234-5678/works")
    assert r.status_code == 200
    body = r.json()
    titles = {i["title"] for i in body["items"]}
    # the tab lists OpenAlex-side rows only (works_stats + canonical);
    # the Pure works table is not a tab source
    assert titles == {"Pure Work (OA twin)", "Journal Only Work", "Ghost Work"}
    # canonical-side item shape survives the merge unchanged
    ghost = next(i for i in body["items"] if i["title"] == "Journal Only Work")
    assert ghost["in_openalex"] is False
    assert ghost["doi"] == "10.9999/journal-only"
    assert ghost["cited_by_count"] == 4


@requires_db
async def test_journal_metrics_count_canonical_rows(serving_api):
    r = await serving_api.get("/api/v1/ut/journals/1234-5678")
    assert r.status_code == 200
    metrics = r.json()["institution_metrics"]
    # canonical rows (3 in-window after gates) count even with no works_stats
    assert metrics["canonical_total"] == 3


@requires_db
async def test_author_profile_merges_openalex_only(serving_api):
    r = await serving_api.get("/api/v1/ut/authors/alice-uuid")
    assert r.status_code == 200
    works = r.json()["works"]
    titles = [w["title"] for w in works]
    # local work first (pure), then the gated openalex-only merge
    assert titles == ["Pure Work", "Ghost Work"]
    ghost = works[-1]
    assert ghost["in_pure"] is False
    assert ghost["doi"] == "10.9999/ghost"
    assert ghost["journal_title"] == "Journal One"
    assert ghost["year"] == 2024


@requires_db
async def test_author_page_pure_only_without_store(db, client, institution_factory):
    """No openalex_works rows + no DSN -> pure-only page, no merge, no 500."""
    ut = await institution_factory(code="ut")
    db.add(
        Author(
            institution_id=ut.id,
            pure_uuid="solo-uuid",
            name="Solo Author",
            n_works=0,
            confirmed=True,
        )
    )
    await db.commit()
    r = await client.get("/api/v1/ut/authors/solo-uuid")
    assert r.status_code == 200
    assert r.json()["works"] == []
