"""Publisher browsing API: per-publisher journal aggregates, filters with
pipe multi-select OR semantics, drop-own-dimension facets, institution
scoping, detail bundle (deals/stats reuse), and slash-bearing names."""

from urllib.parse import quote

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.db import get_session
from journal_browser.main import app
from journal_browser.models import (
    Deal,
    DealInstitution,
    DealJournal,
    HarvestRun,
    InstitutionWorksStats,
    Journal,
    JournalApcAggregate,
    JournalFlags,
    OpenalexPublisher,
    Publisher,
    SourceRecord,
)


@pytest.fixture
async def publishers_api(db, institution_factory):
    """ut: Elsevier BV (J1 covered hybrid Q1 with OpenAPC evidence + topics,
    J2 diamond Q2), Springer (J3 covered hybrid Q1 with an OpenAlex list
    price, J7 subscription without quartile), Wiley (J8 subscription Q3) and
    Alpha/Beta Press (J9, slash name, no works). Excluded from grouping: a
    NULL publisher, a below-cutoff journal, a browse-excluded one. rug: only
    Elsevier BV is browsable, with different flag numbers."""

    async def _override():
        async with async_sessionmaker(db.bind, expire_on_commit=False)() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    ut = await institution_factory(code="ut")
    rug = await institution_factory(code="rug")
    session = db
    session.add_all(
        [
            journal_factory(
                "1234-5678",
                publisher_name="Elsevier BV",
                latest_quartile="Q1",
                latest_apc_euro=2400,
                topics=[
                    {
                        "display_name": "Condensed Matter Physics",
                        "count": 30,
                        "subfield": "Physics",
                    },
                    {"display_name": "Nanotech", "count": 10, "subfield": "Materials Science"},
                ],
            ),  # J1: covered hybrid
            journal_factory(
                "2222-2221",
                publisher_name="Elsevier BV",
                is_in_doaj=True,
                doaj_in_doaj=True,
                doaj_has_apc=False,
                latest_quartile="Q2",
            ),
            journal_factory(
                "3333-3331",
                publisher_name="Springer",
                latest_quartile="Q1",
                apc_prices=[{"currency": "EUR", "price": 1500}],
                latest_apc_euro=1500,
            ),
            journal_factory("4444-4441", publisher_name=None),  # NULL publisher: excluded
            journal_factory("5555-5551", publisher_name="Springer"),  # below cutoff (flags)
            journal_factory("6666-6661", publisher_name="Small Press"),  # browse-excluded
            journal_factory("7777-7771", publisher_name="Springer"),
            journal_factory("8888-8881", publisher_name="Wiley", latest_quartile="Q3"),
            journal_factory("9999-9991", publisher_name="Alpha/Beta Press"),
        ]
    )
    await session.flush()

    def _flags(issn_l: str, **kw) -> JournalFlags:
        return JournalFlags(institution_id=ut.id, issn_l=issn_l, **kw)

    session.add_all(
        [
            _flags("1234-5678", works_count=5, works_window_plus=10, deal_covered=True),
            _flags("2222-2221", works_count=3, works_window_plus=8),
            _flags("3333-3331", works_count=10, works_window_plus=12, deal_covered=True),
            _flags("5555-5551", works_count=2, works_window_plus=1),  # cutoff
            _flags("6666-6661", works_count=2, works_window_plus=10, browse_excluded=True),
            _flags("7777-7771", works_count=2, works_window_plus=5),
            _flags("8888-8881", works_count=4, works_window_plus=6),
            _flags("9999-9991", works_count=0, works_window_plus=4),
        ]
    )
    # rug sees only Elsevier BV, with its own numbers and no deal coverage.
    session.add_all(
        [
            JournalFlags(
                institution_id=rug.id, issn_l="1234-5678", works_count=2, works_window_plus=6
            )
        ]
    )
    session.add(
        JournalApcAggregate(
            issn_l="1234-5678",
            period=2024,
            article_count=2,
            euro_min=2000,
            euro_max=2400,
            euro_mean=2200,
        )
    )
    deal_publisher = Publisher(name="Elsevier BV")
    session.add(deal_publisher)
    await session.flush()
    deal = Deal(publisher_id=deal_publisher.id, esac_id="elsevier2024", status="current")
    session.add(deal)
    await session.flush()
    session.add_all(
        [
            DealInstitution(deal_id=deal.id, institution_id=ut.id),
            DealJournal(deal_id=deal.id, issn_l="1234-5678", issn="1234-5678", source="manual"),
            # Window-bounded works stats for the ut detail bundle.
            InstitutionWorksStats(
                institution_id=ut.id,
                source="pure_canon",
                issn_l="1234-5678",
                year=2023,
                works_count=2,
            ),
            InstitutionWorksStats(
                institution_id=ut.id,
                source="openalex_institution_filter",
                issn_l="1234-5678",
                year=2023,
                works_count=3,
                oa_gold=1,
                oa_green=1,
            ),
            InstitutionWorksStats(
                institution_id=ut.id,
                source="openalex_institution_filter",
                issn_l="1234-5678",
                year=2024,
                works_count=2,
                oa_hybrid=1,
                oa_closed=1,
            ),
            # rug-window stats row must never leak into the ut detail.
            InstitutionWorksStats(
                institution_id=rug.id,
                source="openalex_institution_filter",
                issn_l="1234-5678",
                year=2023,
                works_count=99,
            ),
        ]
    )
    await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client, {"ut": ut.id, "rug": rug.id, "deal": deal.id}
    app.dependency_overrides.clear()


@requires_db
async def test_publisher_list_aggregates(publishers_api):
    client, _ids = publishers_api
    r = await client.get("/api/v1/ut/publishers")
    assert r.status_code == 200
    body = r.json()
    # NULL publisher, below-cutoff and browse-excluded journals never group.
    assert body["total"] == 4
    assert [i["name"] for i in body["items"]] == [
        "Springer",
        "Elsevier BV",
        "Wiley",
        "Alpha/Beta Press",
    ]
    springer, elsevier = body["items"][0], body["items"][1]
    assert springer == {
        "name": "Springer",
        "n_journals": 2,
        "n_works": 12,  # 10 + 2 flags.works_count
        "deal_journals": 1,
        "oa_types": {"gold": 0, "diamond": 0, "generic": 0, "hybrid": 1, "subscription": 1},
        "quartiles": {"q1": 1, "q2": 0, "q3": 0, "q4": 0, "none": 1},
        "apc": {"n_journals": 1, "eur_min": 1500.0, "eur_max": 1500.0},
        "topics": [],
    }
    assert elsevier == {
        "name": "Elsevier BV",
        "n_journals": 2,
        "n_works": 8,  # 5 + 3
        "deal_journals": 1,
        "oa_types": {"gold": 0, "diamond": 1, "generic": 0, "hybrid": 1, "subscription": 0},
        "quartiles": {"q1": 1, "q2": 1, "q3": 0, "q4": 0, "none": 0},
        "apc": {"n_journals": 1, "eur_min": 2400.0, "eur_max": 2400.0},
        # J1's 5 works spread over its topics by count (30/10).
        "topics": [{"name": "Physics", "n": 3.75}, {"name": "Materials Science", "n": 1.25}],
    }


@requires_db
async def test_publisher_filters_and_multiselect(publishers_api):
    client, _ids = publishers_api

    async def names(params: dict) -> list[str]:
        body = (await client.get("/api/v1/ut/publishers", params=params)).json()
        return [i["name"] for i in body["items"]]

    # Pipe multi-select ORs within the dimension.
    assert await names({"oa_type": "diamond"}) == ["Elsevier BV"]
    assert await names({"oa_type": "diamond|hybrid"}) == ["Springer", "Elsevier BV"]
    assert await names({"oa_type": "gold"}) == []
    assert await names({"deal": "none"}) == ["Wiley", "Alpha/Beta Press"]
    assert await names({"quartile": "Q2"}) == ["Elsevier BV"]
    assert await names({"quartile": "Q1|Q3"}) == ["Springer", "Elsevier BV", "Wiley"]
    # Topic matches a topics display_name case-insensitively.
    assert await names({"topic": "Condensed Matter Physics"}) == ["Elsevier BV"]
    assert await names({"topic": "condensed matter physics"}) == ["Elsevier BV"]
    assert await names({"topic": "Nanotech|Condensed Matter Physics"}) == ["Elsevier BV"]
    assert await names({"has_apc": True}) == ["Springer", "Elsevier BV"]
    assert await names({"has_works": False}) == ["Alpha/Beta Press"]
    assert await names({"q": "spring"}) == ["Springer"]
    # Size buckets: publisher journal counts (1 vs 2-4).
    assert await names({"size": "1"}) == ["Wiley", "Alpha/Beta Press"]
    assert await names({"size": "2-4|10+"}) == ["Springer", "Elsevier BV"]
    # Size drops its own facet dimension: selecting "1" still counts the rest.
    facet_body = (await client.get("/api/v1/ut/publishers", params={"size": "1"})).json()
    assert facet_body["facets"]["size"]["2-4"] == 2
    # Relevance defaults with q: the "e" prefix match outranks substrings.
    assert (await names({"q": "e"}))[0] == "Elsevier BV"
    # Offset/limit pages the sorted matches.
    assert await names({"offset": 1, "limit": 2}) == ["Elsevier BV", "Wiley"]


@requires_db
async def test_publisher_facets_drop_own_dimension(publishers_api):
    client, _ids = publishers_api
    body = (await client.get("/api/v1/ut/publishers")).json()
    assert body["facets"] == {
        "oa_type": {"gold": 0, "diamond": 1, "generic": 0, "hybrid": 2, "subscription": 3},
        "deal": {"covered": 2, "none": 2},
        "quartile": {"Q1": 2, "Q2": 1, "Q3": 1, "Q4": 0},
        "has_apc": {"yes": 2, "no": 2},
        "size": {"1": 2, "2-4": 2, "5-9": 0, "10+": 0},
        "topic": {"Condensed Matter Physics": 1, "Nanotech": 1},
    }

    # oa_type=gold matches no publisher, yet every OTHER facet value still
    # counts the publishers that would gain it.
    body = (await client.get("/api/v1/ut/publishers", params={"oa_type": "gold"})).json()
    assert body["total"] == 0 and body["items"] == []
    assert body["facets"]["oa_type"] == {
        "gold": 0,
        "diamond": 1,
        "generic": 0,
        "hybrid": 2,
        "subscription": 3,
    }

    # A non-empty own filter: deal facet keeps its unfiltered distribution.
    body = (await client.get("/api/v1/ut/publishers", params={"deal": "covered"})).json()
    assert body["total"] == 2
    assert body["facets"]["deal"] == {"covered": 2, "none": 2}
    assert body["facets"]["quartile"] == {"Q1": 2, "Q2": 1, "Q3": 0, "Q4": 0}

    body = (await client.get("/api/v1/ut/publishers", params={"include_facets": False})).json()
    assert body["facets"] == {}


@requires_db
async def test_publisher_detail(publishers_api):
    client, _ids = publishers_api
    r = await client.get(f"/api/v1/ut/publishers/{quote('Elsevier BV')}")
    assert r.status_code == 200
    body = r.json()
    assert body["publisher"]["name"] == "Elsevier BV"
    assert body["publisher"]["topics"] == [
        {"name": "Physics", "n": 3.75},
        {"name": "Materials Science", "n": 1.25},
    ]
    # Its two browsable journals, works desc.
    assert [(j["issn_l"], j["works"]) for j in body["journals"]] == [
        ("1234-5678", 5),
        ("2222-2221", 3),
    ]
    j1 = body["journals"][0]
    assert j1["oa_type"] == "hybrid" and j1["deal_covered"] is True
    assert j1["apc_source"] == "openapc" and j1["apc_low"] == 2000.0 and j1["apc_high"] == 2400.0
    # The deal covering J1, with register-publisher name attached.
    assert [d["esac_id"] for d in body["deals"]] == ["elsevier2024"]
    assert body["deals"][0]["publisher_name"] == "Elsevier BV"
    # Window-bounded, summed over the publisher's issns; pure_canon wins the
    # works total, OpenAlex always carries the OA split. Newest first.
    assert body["works_by_year"] == [
        {
            "year": 2024,
            "works_count": 2,
            "works_count_source": "openalex_institution_filter",
            "oa_gold": 0,
            "oa_hybrid": 1,
            "oa_green": 0,
            "oa_bronze": 0,
            "oa_diamond": 0,
            "oa_closed": 1,
        },
        {
            "year": 2023,
            "works_count": 2,  # pure_canon primary, not OpenAlex's 3 (+rug's 99)
            "works_count_source": "pure_canon",
            "oa_gold": 1,
            "oa_hybrid": 0,
            "oa_green": 1,
            "oa_bronze": 0,
            "oa_diamond": 0,  # J2 has no stats rows seeded
            "oa_closed": 0,
        },
    ]


@requires_db
async def test_publisher_detail_404_and_slash_name(publishers_api):
    client, _ids = publishers_api
    assert (await client.get("/api/v1/ut/publishers/Nonexistent")).status_code == 404
    r = await client.get(f"/api/v1/ut/publishers/{quote('Alpha/Beta Press')}")
    assert r.status_code == 200
    assert r.json()["publisher"]["name"] == "Alpha/Beta Press"
    assert r.json()["publisher"]["n_works"] == 0


@requires_db
async def test_publisher_institution_isolation(publishers_api):
    client, _ids = publishers_api
    body = (await client.get("/api/v1/rug/publishers")).json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item == {
        "name": "Elsevier BV",
        "n_journals": 1,
        "n_works": 2,  # rug's own flags, not ut's 8
        "deal_journals": 0,
        "oa_types": {"gold": 0, "diamond": 0, "generic": 0, "hybrid": 0, "subscription": 1},
        "quartiles": {"q1": 1, "q2": 0, "q3": 0, "q4": 0, "none": 0},
        "apc": {"n_journals": 1, "eur_min": 2400.0, "eur_max": 2400.0},
        # Journal topics are institution-neutral; rug's 2 J1 works spread
        # over them by count (30/10).
        "topics": [{"name": "Physics", "n": 1.5}, {"name": "Materials Science", "n": 0.5}],
    }
    assert (await client.get("/api/v1/nonsense/publishers")).status_code == 404


# ── Canonical grouping (journals.publisher_canonical, migration 0025) ──────


@pytest.fixture
async def canonical_api(publishers_api, db):
    """Springer's two journals merge with a 'Nature Research' journal under
    one canonical 'Springer Nature'; the journals keep their own
    publisher_name for display."""
    client, ids = publishers_api
    session = db
    session.add(
        journal_factory(
            "1010-1010",
            publisher_name="Nature Research",
            publisher_canonical="Springer Nature",
            topics=[{"display_name": "Condensed Matter Physics", "count": 5}],
        )
    )
    await session.flush()
    session.add(
        JournalFlags(
            institution_id=ids["ut"], issn_l="1010-1010", works_count=1, works_window_plus=7
        )
    )
    # Zero-count topics (rows stored before `count` was persisted): all
    # works pile onto the first entry's label.
    session.add(
        journal_factory(
            "1212-1212",
            publisher_name="Legacy Press",
            topics=[{"display_name": "Zoology"}],
        )
    )
    await session.flush()
    session.add(
        JournalFlags(
            institution_id=ids["ut"], issn_l="1212-1212", works_count=4, works_window_plus=9
        )
    )
    await session.execute(
        update(Journal)
        .where(Journal.issn_l.in_(["3333-3331", "7777-7771"]))
        .values(publisher_canonical="Springer Nature")
    )
    await session.commit()
    return client, ids


@requires_db
async def test_publisher_canonical_merges_subbrands(canonical_api):
    client, _ids = canonical_api
    body = (await client.get("/api/v1/ut/publishers")).json()
    # Two publisher_names (Springer, Nature Research) collapse into one
    # canonical group; uncanonicalized names keep their own groups.
    assert body["total"] == 5
    assert [i["name"] for i in body["items"]] == [
        "Springer Nature",
        "Elsevier BV",
        "Legacy Press",
        "Wiley",
        "Alpha/Beta Press",
    ]
    merged = body["items"][0]
    assert merged["n_journals"] == 3
    assert merged["n_works"] == 13  # 10 + 2 + 1
    assert merged["deal_journals"] == 1
    assert merged["oa_types"] == {
        "gold": 0,
        "diamond": 0,
        "generic": 0,
        "hybrid": 1,
        "subscription": 2,
    }
    assert merged["quartiles"] == {"q1": 1, "q2": 0, "q3": 0, "q4": 0, "none": 2}
    assert merged["apc"] == {"n_journals": 1, "eur_min": 1500.0, "eur_max": 1500.0}
    # J10's single work lands whole on its topic label.
    assert merged["topics"] == [{"name": "Condensed Matter Physics", "n": 1.0}]
    # Legacy Press: zero-count topics put all 4 works on the primary label.
    assert body["items"][2]["n_works"] == 4
    assert body["items"][2]["topics"] == [{"name": "Zoology", "n": 4.0}]


@requires_db
async def test_publisher_search_matches_member_names(canonical_api):
    client, _ids = canonical_api
    # q reaches the canonical group through a sub-brand publisher_name,
    # and a member-name prefix ranks the group as relevant.
    body = (await client.get("/api/v1/ut/publishers", params={"q": "Nature"})).json()
    names = [i["name"] for i in body["items"]]
    assert "Springer Nature" in names
    assert names[0] == "Springer Nature"  # member-name prefix match
    body = (await client.get("/api/v1/ut/publishers", params={"q": "nature rese"})).json()
    assert [i["name"] for i in body["items"]] == ["Springer Nature"]


@requires_db
async def test_publisher_detail_by_canonical_name(canonical_api):
    client, _ids = canonical_api
    r = await client.get(f"/api/v1/ut/publishers/{quote('Springer Nature')}")
    assert r.status_code == 200
    body = r.json()
    assert body["publisher"]["n_journals"] == 3
    # All sub-brand journals ride along under the canonical key, own
    # publisher_name intact, institution_works desc.
    assert [(j["issn_l"], j["publisher_name"]) for j in body["journals"]] == [
        ("3333-3331", "Springer"),
        ("7777-7771", "Springer"),
        ("1010-1010", "Nature Research"),
    ]
    # The group lives under the canonical; its former name is gone.
    assert (await client.get(f"/api/v1/ut/publishers/{quote('Springer')}")).status_code == 404


@requires_db
async def test_publisher_facets_on_merged_groups(canonical_api):
    client, _ids = canonical_api
    body = (await client.get("/api/v1/ut/publishers")).json()
    # Size buckets run over merged group sizes (3 journals -> "2-4").
    assert body["facets"]["size"] == {"1": 3, "2-4": 2, "5-9": 0, "10+": 0}
    # J10 shares Elsevier's topic label; the facet counts publishers, not
    # journals.
    assert body["facets"]["topic"] == {
        "Condensed Matter Physics": 2,
        "Nanotech": 1,
        "Zoology": 1,
    }
    names = (
        await client.get("/api/v1/ut/publishers", params={"topic": "condensed matter physics"})
    ).json()
    assert [i["name"] for i in names["items"]] == ["Springer Nature", "Elsevier BV"]


@requires_db
async def test_publisher_snapshot_per_institution(publishers_api):
    client, _ids = publishers_api
    # rug first, ut second: each institution builds its own snapshot.
    rug = (await client.get("/api/v1/rug/publishers")).json()
    assert rug["total"] == 1
    assert rug["items"][0]["n_works"] == 2
    ut = (await client.get("/api/v1/ut/publishers")).json()
    assert ut["total"] == 4
    # Warm snapshot serves identical numbers.
    assert (await client.get("/api/v1/ut/publishers")).json() == ut
    # rug's cached snapshot still holds rug's own aggregates, not ut's 8.
    assert (await client.get("/api/v1/rug/publishers")).json() == rug


# ── harvest.publishers pure parts (no HTTP) ────────────────────────────────


def test_lineage_resolution():
    from journal_browser.harvest.publishers import (
        _rows_for,
        canonical_from_lineage,
        host_pk,
    )

    assert host_pk("https://openalex.org/P4310319808") == "P4310319808"
    assert host_pk(None) == ""
    # lineage is [self, ..., root]; the root is the canonical publisher.
    assert canonical_from_lineage(["P4310316002", "P4310319808"]) == "P4310319808"
    assert canonical_from_lineage(["P4310319808"]) == "P4310319808"
    assert canonical_from_lineage(None) is None
    assert canonical_from_lineage([]) is None
    # Failed fetches (None payload) store a NULL lineage; canonical_name
    # resolves through the names map, root payloads included.
    rows = _rows_for(
        {
            "P2": {"id": "P2", "display_name": "Comms Society", "lineage": ["P2", "P1"]},
            "P3": None,
        },
        {"P1": "IEEE"},
    )
    assert [
        (r["openalex_id"], r["lineage"], r["canonical_id"], r["canonical_name"]) for r in rows
    ] == [
        ("P2", ["P2", "P1"], "P1", "IEEE"),
        ("P3", None, None, None),
    ]
    assert rows[0]["display_name"] == "Comms Society"
    assert all(r["fetched_at"] is not None for r in rows)


@requires_db
async def test_harvest_backfill_canonical(db):
    from journal_browser.harvest.publishers import backfill_canonical

    session = db
    run = HarvestRun(source="openalex", entity_type="sources", config_fingerprint="test")
    session.add(run)
    await session.flush()
    session.add_all(
        [
            SourceRecord(
                source="openalex",
                entity_type="sources",
                source_pk="S1",
                payload={"host_organization": "https://openalex.org/P2"},
                content_hash="h1",
                harvest_run_id=run.id,
            ),
            SourceRecord(
                source="openalex",
                entity_type="sources",
                source_pk="S2",
                payload={"host_organization": "https://openalex.org/I123"},
                content_hash="h2",
                harvest_run_id=run.id,
            ),
            SourceRecord(
                source="openalex",
                entity_type="sources",
                source_pk="S3",
                payload={},
                content_hash="h3",
                harvest_run_id=run.id,
            ),
        ]
    )
    session.add_all(
        [
            journal_factory("1111-1111", openalex_id="S1", publisher_name="Comms Society"),
            journal_factory("2222-2222", openalex_id="S2", publisher_name="Inst Journal"),
            journal_factory("3333-3339", openalex_id="S3", publisher_name="No Host Journal"),
        ]
    )
    session.add(
        OpenalexPublisher(
            openalex_id="P2",
            display_name="Comms Society",
            lineage=["P2", "P1"],
            canonical_id="P1",
            canonical_name="IEEE",
        )
    )
    await session.commit()

    # Only the publisher-hosted journal takes the lineage root's name.
    assert await backfill_canonical(session) == 1
    await session.commit()
    rows = (await session.execute(select(Journal.issn_l, Journal.publisher_canonical))).all()
    assert dict(rows) == {
        "1111-1111": "IEEE",
        "2222-2222": None,  # institution host: no cache row
        "3333-3339": None,  # no host organization
    }
    # Re-run is a no-op (IS DISTINCT FROM guard).
    assert await backfill_canonical(session) == 0
