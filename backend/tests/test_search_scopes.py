"""Search scopes/contract tests: search_in, ISSN normalization, fuzzy
fallback, cursor fixes, publisher/apc facets, /similar, proceedings
exclusion, apc fields, oa_type."""

import base64
import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import requires_db
from journal_browser.db import get_session
from journal_browser.harvest.denorm import BROWSE_EXCLUDED_SQL, MATERIALIZE_SQL
from journal_browser.main import app
from journal_browser.models import Institution, IssnMap, Journal, JournalApcAggregate


def _journal(issn_l: str, **kw) -> Journal:
    base = dict(
        issn_l=issn_l,
        title=f"Journal {issn_l}",
        type="journal",
        is_oa=False,
        is_in_doaj=False,
        in_scimago=False,
        works_2020_plus=10,
    )
    base.update(kw)
    return Journal(**base)


@pytest.fixture
async def api(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with db_engine.begin() as conn:
        # create_all skips migration-side extensions; the trigram operators
        # the fuzzy fallback needs live in pg_trgm (added by migration 0004).
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    async with maker() as session:
        session.add_all(
            [
                # Publisher/ISSN fixture: issn_l "1234-5678", print variant
                # "5678-4321" resolves via IssnMap.
                _journal(
                    "1234-5678",
                    title="Journal of Widgets",
                    publisher_name="Massachusetts Institute of Technology Press",
                    search_text="Journal of Widgets",
                ),
                # Fuzzy fixture: near-miss queries must hit via trigram.
                _journal(
                    "1111-1111",
                    title="Bioinformatics Quarterly",
                    search_text="Bioinformatics Quarterly",
                ),
                # Topic fixture.
                _journal(
                    "2222-2222",
                    title="Quantum Studies",
                    topics=[{"display_name": "Quantum Chemistry"}],
                    search_text="Quantum Studies",
                ),
                # OA-type fixtures.
                _journal("3333-3333", title="Gold Journal", is_in_doaj=True),
                _journal("4444-4444", title="Diamond Journal", is_in_doaj=True),
                _journal("5555-5555", title="Hybrid Journal"),
                _journal("6666-6666", title="Subscription Journal"),
                # Similar fixtures.
                _journal(
                    "7777-7777",
                    title="Similar Strong",
                    topics=[{"display_name": "A"}, {"display_name": "B"}],
                    summary_stats={"two_yr_mean_citedness": "5.0"},
                ),
                _journal(
                    "8888-8888",
                    title="Similar Weak",
                    topics=[{"display_name": "A"}],
                ),
                _journal(
                    "9999-9999",
                    title="No Shared Topic",
                    topics=[{"display_name": "C"}],
                ),
                _journal(
                    "1010-1010",
                    title="Below Cutoff Similar",
                    topics=[{"display_name": "A"}],
                    works_2020_plus=2,
                ),
                # Proceedings fixtures: pattern match, no deal, no UT works
                # -> hidden; deal-covered -> stays; UT works -> stays.
                _journal(
                    "1212-1212",
                    title="Proceedings of the 2024 Workshop on Widgets",
                    search_text="Proceedings of the 2024 Workshop on Widgets",
                ),
                _journal(
                    "1313-1313",
                    title="Conference Abstracts in Medicine",
                    search_text="Conference Abstracts in Medicine",
                ),
                _journal(
                    "1414-1414",
                    title="Annual Symposium Proceedings",
                    search_text="Annual Symposium Proceedings",
                ),
                # APC fixtures: two periods for the most-recent test.
                _journal(
                    "1515-1515",
                    title="Priced Journal",
                    is_in_doaj=True,
                    search_text="Priced Journal",
                ),
                # NULL-twoyr pagination fixtures: no summary_stats at all.
                _journal(
                    "1717-1717",
                    title="Metricless Alpha",
                    search_text="Metricless Alpha Journal",
                ),
                _journal(
                    "1818-1818",
                    title="Metricless Beta",
                    search_text="Metricless Beta Journal",
                ),
                _journal(
                    "1919-1919",
                    title="Metric Gamma",
                    summary_stats={"two_yr_mean_citedness": "2.5"},
                    search_text="Metric Gamma Journal",
                ),
            ]
        )
        session.add_all(
            [
                IssnMap(issn="1234-5678", issn_l="1234-5678", source="test"),
                IssnMap(issn="5678-4321", issn_l="1234-5678", source="test"),
                JournalApcAggregate(
                    issn_l="1515-1515",
                    period=2023,
                    article_count=5,
                    euro_mean=1800.0,
                    euro_max=2000.0,
                ),
                JournalApcAggregate(
                    issn_l="1515-1515",
                    period=2024,
                    article_count=8,
                    euro_mean=2200.0,
                    euro_max=2500.0,
                ),
                # gold fixture evidence
                JournalApcAggregate(
                    issn_l="3333-3333",
                    period=2024,
                    article_count=3,
                    euro_mean=900.0,
                    euro_max=1000.0,
                ),
            ]
        )
        await session.commit()

        # Per-institution flags (journal_flags) replace the old journals
        # columns. Materialize one row per journal, then set the fixture
        # specifics; the corpus cutoff passes for everything except the
        # below-cutoff fixture.
        home = Institution(
            name="University of Twente", code="ut", active=True, is_default=True
        )
        session.add(home)
        await session.flush()
        await session.execute(MATERIALIZE_SQL, {"iid": home.id})
        await session.execute(
            text(
                "UPDATE journal_flags SET works_window_plus = 10"
                " WHERE institution_id = :iid AND issn_l <> '1010-1010'"
            ),
            {"iid": home.id},
        )
        await session.execute(
            text(
                "UPDATE journal_flags SET works_window_plus = 2"
                " WHERE institution_id = :iid AND issn_l = '1010-1010'"
            ),
            {"iid": home.id},
        )
        await session.execute(
            text(
                "UPDATE journal_flags SET deal_covered = true"
                " WHERE institution_id = :iid AND issn_l IN ('5555-5555', '1313-1313')"
            ),
            {"iid": home.id},
        )
        await session.execute(
            text(
                "UPDATE journal_flags SET works_count = 7"
                " WHERE institution_id = :iid AND issn_l = '1414-1414'"
            ),
            {"iid": home.id},
        )
        await session.commit()
        # The browse-excluded flag is denormalized (migration 0011 backfills
        # prod); recompute here so the proceedings fixtures get real values.
        await session.execute(BROWSE_EXCLUDED_SQL, {"iid": home.id})
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.clear()


def _issns(body: dict) -> set[str]:
    return {i["issn_l"] for i in body["items"]}


@requires_db
async def test_malformed_cursor_is_400(api):
    r = await api.get("/api/v1/ut/journals", params={"cursor": "not-a-cursor"})
    assert r.status_code == 400
    # Valid base64 but not JSON.
    junk = base64.urlsafe_b64encode(b"nonsense").decode()
    r = await api.get("/api/v1/ut/journals", params={"cursor": junk})
    assert r.status_code == 400


@requires_db
async def test_null_twoyr_sort_pages_cleanly(api):
    # 1515-1515 has no summary_stats -> NULL twoyr must coalesce, never
    # produce a NULL cursor or a 500.
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {
            "sort": "2yr_mean_citedness",
            "q": "journal",
            "limit": 2,
        }
        if cursor:
            params["cursor"] = cursor
        r = await api.get("/api/v1/ut/journals", params=params)
        assert r.status_code == 200
        body = r.json()
        seen += [i["issn_l"] for i in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        assert payload["v"] is not None
    assert cursor is None
    assert len(seen) == len(set(seen)) > 0


@requires_db
async def test_relevance_sort_pages_cleanly(api):
    # Regression: relevance rank is float8 in SQL, so its cursor must cast
    # to Numeric; as String it died with "operator does not exist: double
    # precision < character varying" on every page after the first.
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"sort": "relevance", "q": "journal", "limit": 2}
        if cursor:
            params["cursor"] = cursor
        r = await api.get("/api/v1/ut/journals", params=params)
        assert r.status_code == 200
        body = r.json()
        seen += [i["issn_l"] for i in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert cursor is None
    assert len(seen) == len(set(seen)) > 0


@requires_db
async def test_title_sort_pages_with_lower_case_cursor(api):
    cursor = None
    seen: list[str] = []
    for _ in range(10):
        params = {"sort": "title", "q": "journal", "limit": 3}
        if cursor:
            params["cursor"] = cursor
        r = await api.get("/api/v1/ut/journals", params=params)
        assert r.status_code == 200
        body = r.json()
        seen += [i["issn_l"] for i in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert cursor is None
    assert len(seen) == len(set(seen)) > 0


@requires_db
async def test_search_in_publisher_scope(api):
    r = await api.get("/api/v1/ut/journals", params={"q": "massachusetts", "search_in": "publisher"})
    assert r.status_code == 200
    assert _issns(r.json()) == {"1234-5678"}
    # Same query in the title scope must not match the publisher.
    r = await api.get("/api/v1/ut/journals", params={"q": "massachusetts", "search_in": "title"})
    assert r.status_code == 200
    assert r.json()["total"] == 0
    # The "all" scope matches publisher too.
    r = await api.get("/api/v1/ut/journals", params={"q": "massachusetts"})
    assert {"1234-5678"} <= _issns(r.json())
    # LIKE wildcards in user input stay literal, no crash.
    r = await api.get("/api/v1/ut/journals", params={"q": "mass%achu_setts", "search_in": "publisher"})
    assert r.status_code == 200
    assert r.json()["total"] == 0


@requires_db
async def test_search_in_topic_scope(api):
    # "chemistry" appears only in the topic display_name, not the title.
    r = await api.get("/api/v1/ut/journals", params={"q": "chemistry", "search_in": "topic"})
    assert r.status_code == 200
    assert _issns(r.json()) == {"2222-2222"}
    r = await api.get("/api/v1/ut/journals", params={"q": "chemistry", "search_in": "title"})
    assert r.json()["total"] == 0


@requires_db
async def test_issn_query_resolves_variants(api):
    # Print variant via IssnMap, hyphenless and spaced forms via
    # normalized direct comparison.
    for q in ("5678-4321", "56784321", "1234 5678", "1234-5678"):
        r = await api.get("/api/v1/ut/journals", params={"q": q})
        assert r.status_code == 200, q
        assert _issns(r.json()) == {"1234-5678"}, q


@requires_db
async def test_fuzzy_fallback_sets_flag(api):
    # Both words misspelled: FTS, prefix and scopes all miss; the trigram
    # retry must find it and set fuzzy.
    r = await api.get("/api/v1/ut/journals", params={"q": "bioinformatiks quaterly"})
    assert r.status_code == 200
    body = r.json()
    assert body["fuzzy"] is True
    assert _issns(body) == {"1111-1111"}
    # A clean hit does not set the flag.
    r = await api.get("/api/v1/ut/journals", params={"q": "bioinformatics"})
    assert r.json()["fuzzy"] is False


@requires_db
async def test_publisher_and_apc_facets(api):
    body = (await api.get("/api/v1/ut/journals")).json()
    facets = body["facets"]
    assert facets["apc"] == {"true": 2, "false": len(body["items"]) - 2}
    # Cross-consistency: every non-publisher facet sums to the total.
    for group in ("deal_coverage", "oa", "doaj", "apc"):
        assert sum(facets[group].values()) == body["total"]
    assert facets["publisher"]["Massachusetts Institute of Technology Press"] == 1

    # Active has_apc filter: apc facet excludes its own filter (matches the
    # unfiltered counts); publisher facet respects it.
    browse_facets = facets
    body = (await api.get("/api/v1/ut/journals", params={"has_apc": "true"})).json()
    assert body["total"] == 2
    assert body["facets"]["apc"] == browse_facets["apc"]
    assert set(_issns(body)) == {"3333-3333", "1515-1515"}

    # Active publisher filter: publisher facet excludes its own filter; the
    # apc facet respects it (only 1515-1515 has apc evidence and its
    # publisher is MIT Press -> all non-MIT journals drop out).
    params = {"publisher": "Massachusetts Institute of Technology Press"}
    body = (await api.get("/api/v1/ut/journals", params=params)).json()
    assert _issns(body) == {"1234-5678"}


@requires_db
async def test_facet_variants_drop_own_filter(api):
    """Regression: chip facets must drop exactly their own filter. The
    variants used to re-include it, so e.g. deal=covered rendered the "No
    deal" chip with a zero count."""
    browse = (await api.get("/api/v1/ut/journals")).json()
    body = (await api.get("/api/v1/ut/journals", params={"deal": "covered"})).json()
    assert body["total"] == 2  # 5555-5555 and 1313-1313 are deal-covered
    assert body["facets"]["deal_coverage"] == browse["facets"]["deal_coverage"]

    body = (await api.get("/api/v1/ut/journals", params={"oa": "true"})).json()
    assert body["facets"]["oa"] == browse["facets"]["oa"]

    # The apc facet drops only its own filter: has_ut_works stays applied.
    # Regression: it used to drop has_ut_works too. 1414-1414 is the only
    # home-works fixture and has no APC evidence.
    params = {"has_apc": "true", "has_works": "true"}
    body = (await api.get("/api/v1/ut/journals", params=params)).json()
    assert body["total"] == 0
    assert body["facets"]["apc"] == {"true": 0, "false": 1}

@requires_db
async def test_has_apc_filter(api):
    r = await api.get("/api/v1/ut/journals", params={"has_apc": "false"})
    assert r.status_code == 200
    body = r.json()
    assert "1515-1515" not in _issns(body)
    assert "3333-3333" not in _issns(body)
    assert body["total"] == len(body["items"])


@requires_db
async def test_apc_fields_on_list_items(api):
    r = await api.get("/api/v1/ut/journals", params={"q": "priced"})
    assert r.status_code == 200
    (item,) = r.json()["items"]
    # Latest known cost: highest single APC in the newest period with
    # evidence (2024), not the period mean.
    assert item["apc_period"] == "2024"
    assert item["apc_euro_latest"] == 2500.0
    r = await api.get("/api/v1/ut/journals", params={"q": "quantum studies"})
    (item,) = r.json()["items"]
    assert item["apc_period"] is None
    assert item["apc_euro_latest"] is None


@requires_db
async def test_oa_type_mapping(api):
    r = await api.get("/api/v1/ut/journals")
    by_issn = {i["issn_l"]: i["oa_type"] for i in r.json()["items"]}
    assert by_issn["3333-3333"] == "gold"  # doaj + apc evidence
    assert by_issn["4444-4444"] == "diamond"  # doaj, no evidence
    assert by_issn["5555-5555"] == "hybrid"  # deal-covered, not doaj
    assert by_issn["6666-6666"] == "subscription"
    assert by_issn["1515-1515"] == "gold"
    assert set(by_issn.values()) <= {"gold", "diamond", "hybrid", "subscription"}


@requires_db
async def test_oa_type_facet_filter(api):
    # OR semantics: gold OR diamond returns exactly those fixtures.
    r = await api.get("/api/v1/ut/journals", params={"oa_type": "gold,diamond"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert {i["issn_l"] for i in items} == {"3333-3333", "1515-1515", "4444-4444"}

    # Single value narrows to one fixture.
    r = await api.get("/api/v1/ut/journals", params={"oa_type": "diamond"})
    assert r.status_code == 200
    assert _issns(r.json()) == {"4444-4444"}

    # The facet's own filter is excluded from its counts, so every option
    # stays visible (with the rest of the filter set applied).
    oa_facets = r.json()["facets"]["oa_type"]
    assert oa_facets["gold"] == 2
    assert oa_facets["diamond"] == 1
    assert oa_facets["hybrid"] == 2

    # Unknown vocabulary is a 400, not a silent empty result.
    r = await api.get("/api/v1/ut/journals", params={"oa_type": "gold,bogus"})
    assert r.status_code == 400


@requires_db
async def test_proceedings_exclusion(api):
    body = (await api.get("/api/v1/ut/journals")).json()
    issns = _issns(body)
    assert "1212-1212" not in issns  # pattern + no deal + no UT works
    assert "1313-1313" in issns  # deal-covered proceedings stay
    assert "1414-1414" in issns  # UT works keep it visible
    # Facets agree with the list.
    assert sum(body["facets"]["oa"].values()) == body["total"]


@requires_db
async def test_similar_journals(api):
    r = await api.get("/api/v1/ut/journals/1234-5678/similar")
    assert r.status_code == 200
    # No topic overlap with anything: three empty lists.
    assert r.json() == {"institution": [], "deals": [], "all": []}

    r = await api.get("/api/v1/ut/journals/7777-7777/similar")
    assert r.status_code == 200
    bundle = r.json()
    items = bundle["all"]
    # Shared-topic count desc, then twoyr desc; self, non-overlapping and
    # cutoff-failing journals are out.
    assert [(i["issn_l"], i["shared_topics"]) for i in items] == [("8888-8888", 1)]
    assert all(i["issn_l"] != "7777-7777" for i in items)
    assert set(items[0]) >= {
        "issn_l",
        "title",
        "publisher_name",
        "quartile",
        "is_oa",
        "deal_covered",
        "works",
        "shared_topics",
    }
    # Fixture journals carry no UT works and no deal, so the teaser cuts are
    # empty and every item lands in "all" only.
    assert bundle["institution"] == []
    assert bundle["deals"] == []

    # Unknown journal -> 404.
    r = await api.get("/api/v1/ut/journals/0000-0000/similar")
    assert r.status_code == 404
