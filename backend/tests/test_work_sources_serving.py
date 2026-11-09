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
    PureOrg,
    PureOrgParent,
    Work,
    WorkPureAuthor,
)


def _oa_work(inst_id, w_id, *, doi, title, year, authorships, work_type="article", oa="gold"):
    return OpenalexWork(
        institution_id=inst_id,
        w_id=w_id,
        doi_normalized=doi,
        title=title,
        year=year,
        work_type=work_type,
        oa_status=oa,
        venue_issn_l="1234-5678",
        venue_name="Journal One",
        cited_by_count=4,
        authorships=authorships,
    )


@pytest.fixture
async def serving_api(db, institution_factory):
    """ut: journal 1234-5678 with three stored openalex works anchored to
    pure (confirmed-author twin + org-closure twin), one canonical-only
    row and one journal-only row that must NOT serve (no UT-affiliated
    author behind their DOIs), plus one out-of-window row."""

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
            research_group="Group X",
            n_works=1,
            confirmed=True,
        )
    )
    db.add(AuthorWork(institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid="w1"))
    # Pure affiliation evidence the venue filter requires: a confirmed
    # author on the shared work, and an author edge whose affiliation org
    # closes on the institution root.
    db.add(WorkPureAuthor(institution_id=ut.id, work_pure_uuid="w1", person_uuid="alice-uuid"))
    db.add_all(
        [
            PureOrg(institution_id=ut.id, uuid="root-uuid", name="University of Twente"),
            PureOrg(institution_id=ut.id, uuid="child-uuid", name="TechMed Centre"),
            PureOrgParent(institution_id=ut.id, org_uuid="child-uuid", parent_uuid="root-uuid"),
            Work(
                institution_id=ut.id,
                pure_uuid="w2",
                title="Org Work",
                norm_title="org work",
                year=2022,
                doi_normalized="10.1000/orgwork",
                journal_issn_l="1234-5678",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
        ]
    )
    await db.flush()  # the work FK must exist before author edges resolve
    db.add(
        WorkPureAuthor(
            institution_id=ut.id,
            work_pure_uuid="w2",
            person_uuid="bob-uuid",
            affiliations=["child-uuid"],
        )
    )
    await db.flush()
    db.add_all(
        [
            # canonical-only: DOI held by no UT-affiliated pure work -> must not serve
            _oa_work(
                ut.id,
                "W-ghost",
                doi="10.9999/ghost",
                title="Ghost Work",
                year=2024,
                authorships=[{"a": "A-ALICE", "n": "Alice Author", "o": None}],
            ),
            # same publication as the Pure copy -> merged away; a second
            # W-id record for the same DOI carries the stale closed color,
            # and the most open record must win the DOI dedup
            _oa_work(
                ut.id,
                "W-twin",
                doi="10.1000/shared",
                title="Pure Work (OA twin)",
                year=2023,
                authorships=[{"a": "A-ALICE", "n": "Alice Author", "o": None}],
            ),
            _oa_work(
                ut.id,
                "W-twin-aaa",
                doi="10.1000/shared",
                title="Pure Work (OA twin)",
                year=2023,
                authorships=[{"a": "A-ALICE", "n": "Alice Author", "o": None}],
                oa="closed",
            ),
            # same publication as the org-closure pure copy -> merged away
            _oa_work(
                ut.id,
                "W-org",
                doi="10.1000/orgwork",
                title="Org Work (OA twin)",
                year=2022,
                authorships=[],
            ),
            # outside the publication window -> gated everywhere
            _oa_work(
                ut.id,
                "W-old",
                doi="10.9999/old",
                title="Old Work",
                year=2015,
                authorships=[{"a": "A-ALICE", "n": "Alice Author", "o": None}],
            ),
            # journal-only DOI with no UT affiliation behind it -> must not serve
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
    # the tab lists the Pure works-table population; store-only rows whose
    # DOI has no Pure work behind it (ghost, journal-only) stay out, and
    # the out-of-window row is gated
    assert titles == {"Pure Work", "Org Work"}
    # the store copy only enriches: the DOI dedup keeps the most open of
    # the two W-id records (gold over closed), and a Pure work with a
    # store copy reports in_openalex True; Pure authors/groups ride along
    twin = next(i for i in body["items"] if i["title"] == "Pure Work")
    assert twin["in_openalex"] is True
    assert twin["id"] == "W-twin"
    assert twin["doi"] == "https://doi.org/10.1000/shared"
    assert twin["cited_by_count"] == 4
    assert twin["oa_status"] == "gold"
    assert twin["ut_authors"] == [{"id": "alice-uuid", "name": "Alice Author"}]
    assert twin["ut_groups"] == [{"name": "Group X"}]
    org = next(i for i in body["items"] if i["title"] == "Org Work")
    assert org["oa_status"] == "gold"
    assert org["ut_authors"] == []


@requires_db
async def test_journal_metrics_count_canonical_rows(serving_api):
    r = await serving_api.get("/api/v1/ut/journals/1234-5678")
    assert r.status_code == 200
    metrics = r.json()["institution_metrics"]
    # canonical rows (2 in-window after the UT-affiliation filter) count
    # even with no works_stats rows
    assert metrics["canonical_total"] == 2


@requires_db
async def test_author_profile_merges_openalex_only(serving_api):
    r = await serving_api.get("/api/v1/ut/authors/alice-uuid")
    assert r.status_code == 200
    # the works list is the Pure canon only; the missed work lives in the
    # openalex_only section
    works = r.json()["works"]
    assert [w["title"] for w in works] == ["Pure Work"]
    section = r.json()["openalex_only"]
    assert section["available"] is True
    assert section["total"] == 1
    ghost = section["items"][0]
    assert ghost["title"] == "Ghost Work"
    assert ghost["in_pure"] is False
    assert ghost["doi"] == "10.9999/ghost"
    assert ghost["journal_title"] == "Journal One"
    assert ghost["year"] == 2024
    assert ghost["openalex_id"] == "W-ghost"
    assert ghost["openalex_url"] == "https://openalex.org/W-ghost"
    # roster attribution rides on the store row's authorships
    assert ghost["ut_authors"] == [
        {
            "name": "Alice Author",
            "orcid": None,
            "faculty": None,
            "research_group": "Group X",
            "institute": None,
        }
    ]
    # the exact gated count rides beside the section
    assert r.json()["openalex_only_count"] == 1


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


@requires_db
async def test_foreign_institution_never_reads_dsn(
    db, serving_api, institution_factory, monkeypatch
):
    """A second institution must not serve the DSN owner's works as its own.

    Regression: /api/v1/rug/journals/{issn}/works fell through to the
    ut-metadata DSN (one deployment's database) and rendered another
    site's publications as RUG works. The tab no longer reads the DSN at
    all; the author page's openalex-only merge still can, so it is the
    patched tripwire."""
    from journal_browser.services import work_sources

    async def _boom(*args, **kwargs):
        raise AssertionError("DSN works must not be read for a foreign institution")

    monkeypatch.setattr(work_sources.ut_metadata, "ut_openalex_only_works_for_author", _boom)
    rug = await institution_factory(code="rug", data_window_start=2025)
    db.add(
        Author(
            institution_id=rug.id,
            pure_uuid="rug-uuid",
            name="Rug Author",
            openalex_ids=["a-rug"],
            n_works=0,
            confirmed=True,
        )
    )
    await db.commit()  # the request runs in its own session
    assert rug.active is True
    r = await serving_api.get("/api/v1/rug/journals/1234-5678/works")
    assert r.status_code == 200
    # no local store rows for RUG, no DSN read -> honest empty tab, not
    # foreign rows
    assert r.json()["total"] == 0
    assert r.json()["items"] == []
    # the author path must not read the DSN for a foreign institution either
    r = await serving_api.get("/api/v1/rug/authors/rug-uuid")
    assert r.status_code == 200
