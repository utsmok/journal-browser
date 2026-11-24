"""Public search/browse contract: journals list, facets, filters, sort,
paging, search scopes, similar, semantic search, healthz, meta, and the
route-precedence invariant.

Replaces test_api.py, test_search_scopes.py, test_meta.py, test_health.py
and test_route_precedence.py (scenario map: .audit/2026-11-19-sweep/p2-tests-plan.md).
"""

import base64
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.config import reset_settings_cache
from journal_browser.currency import year_rate
from journal_browser.harvest.denorm import BROWSE_EXCLUDED_SQL, MATERIALIZE_SQL, refresh_apcs
from journal_browser.models import (
    Institution,
    IssnMap,
    JournalApcAggregate,
    JournalFlags,
    Limitation,
)

DIM = 384


def _vec(i: int) -> list[float]:
    """Unit basis vector: distance 0 to itself, 1 (orthogonal) to the others."""
    return [1.0 if j == i else 0.0 for j in range(DIM)]


def _usd_in_eur(amount: float) -> float:
    """An amount in USD at the bundled rate, as refresh_apcs stores it."""
    rate = year_rate("USD")
    assert rate is not None
    return round(amount * rate, 2)


@pytest.fixture
async def api(client, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async with db_engine.begin() as conn:
        # create_all skips migration-side extensions; the trigram operators
        # the fuzzy fallback needs live in pg_trgm (added by migration 0004).
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    async with maker() as session:
        session.add_all(
            [
                # Publisher/ISSN fixture: issn_l "1234-5678", print variant
                # "5678-4321" resolves via IssnMap.
                journal_factory(
                    "1234-5678",
                    title="Journal of Widgets",
                    publisher_name="Massachusetts Institute of Technology Press",
                    search_text="Journal of Widgets",
                ),
                # Fuzzy fixture: near-miss queries must hit via trigram.
                journal_factory(
                    "1111-1111",
                    title="Bioinformatics Quarterly",
                    search_text="Bioinformatics Quarterly",
                    language="en",
                ),
                # Topic fixture.
                journal_factory(
                    "2222-2222",
                    title="Quantum Studies",
                    topics=[{"display_name": "Quantum Chemistry"}],
                    search_text="Quantum Studies",
                    language="en",
                ),
                # OA-type fixtures.
                journal_factory(
                    "3333-3333", title="Gold Journal", is_in_doaj=True, search_text=None
                ),
                journal_factory(
                    "4444-4444",
                    title="Diamond Journal",
                    is_in_doaj=True,
                    doaj_in_doaj=True,
                    doaj_has_apc=False,
                    search_text=None,
                    language="nl",
                ),
                # DOAJ canon gold: DOAJ itself declares an APC.
                journal_factory(
                    "3030-3030",
                    title="Doaj Gold Journal",
                    is_oa=True,
                    doaj_in_doaj=True,
                    doaj_has_apc=True,
                    search_text=None,
                ),
                journal_factory("5555-5555", title="Hybrid Journal", search_text=None),
                journal_factory("6666-6666", title="Subscription Journal", search_text=None),
                # Fully-OA per OpenAlex but missing from DOAJ (the MDPI
                # Water case): priced -> gold; unpriced takes the color
                # observed from recent works, falling back through the
                # deal to subscription when nothing else says OA.
                journal_factory(
                    "2323-2323",
                    title="Water Journal",
                    is_oa=True,
                    apc_prices=[{"currency": "EUR", "price": 2500}],
                    search_text=None,
                ),
                journal_factory(
                    "2424-2424",
                    title="Free OA Journal",
                    is_oa=True,
                    oa_status_observed="diamond",
                    search_text=None,
                ),
                journal_factory(
                    "2626-2626",
                    title="Observed Gold Journal",
                    is_oa=True,
                    oa_status_observed="gold",
                    search_text=None,
                ),
                journal_factory(
                    "2727-2727",
                    title="Observed Closed Covered Journal",
                    is_oa=True,
                    oa_status_observed="closed",
                    search_text=None,
                ),
                journal_factory(
                    "2828-2828", title="Unobserved OA Journal", is_oa=True, search_text=None
                ),
                # Similar fixtures.
                journal_factory(
                    "7777-7777",
                    title="Similar Strong",
                    topics=[{"display_name": "A"}, {"display_name": "B"}],
                    summary_stats={"two_yr_mean_citedness": "5.0"},
                    search_text=None,
                ),
                journal_factory(
                    "8888-8888",
                    title="Similar Weak",
                    topics=[{"display_name": "A"}],
                    search_text=None,
                ),
                journal_factory(
                    "9999-9999",
                    title="No Shared Topic",
                    topics=[{"display_name": "C"}],
                    search_text=None,
                ),
                journal_factory(
                    "1010-1010",
                    title="Below Cutoff Similar",
                    topics=[{"display_name": "A"}],
                    works_2020_plus=2,
                    search_text=None,
                ),
                # Proceedings fixtures: pattern match, no deal, no UT works
                # -> hidden; deal-covered -> stays; UT works -> stays.
                journal_factory(
                    "1212-1212",
                    title="Proceedings of the 2024 Workshop on Widgets",
                    search_text="Proceedings of the 2024 Workshop on Widgets",
                ),
                journal_factory(
                    "1313-1313",
                    title="Conference Abstracts in Medicine",
                    search_text="Conference Abstracts in Medicine",
                ),
                journal_factory(
                    "1414-1414",
                    title="Annual Symposium Proceedings",
                    search_text="Annual Symposium Proceedings",
                ),
                # APC fixtures: two periods for the most-recent test.
                journal_factory(
                    "1515-1515",
                    title="Priced Journal",
                    is_in_doaj=True,
                    search_text="Priced Journal",
                ),
                # NULL-twoyr pagination fixtures: no summary_stats at all.
                # They double as the semantic-search fixtures: the only
                # journals with vectors (near and far from the patched
                # query vector).
                journal_factory(
                    "1717-1717",
                    title="Metricless Alpha",
                    embedding=_vec(0),
                    search_text="Metricless Alpha Journal",
                ),
                journal_factory(
                    "1818-1818",
                    title="Metricless Beta",
                    embedding=_vec(1),
                    search_text="Metricless Beta Journal",
                ),
                journal_factory(
                    "1919-1919",
                    title="Metric Gamma",
                    summary_stats={"two_yr_mean_citedness": "2.5"},
                    search_text="Metric Gamma Journal",
                ),
                # OpenAlex list-price fixture (no OpenAPC aggregates): the
                # list endpoint must prefer it, EUR over USD.
                journal_factory(
                    "1616-1616",
                    title="Fee Listed Journal",
                    apc_prices=[
                        {"currency": "USD", "price": 3000},
                        {"currency": "EUR", "price": 2700},
                    ],
                    harvested_at=datetime(2026, 10, 4, tzinfo=UTC),
                    search_text="Fee Listed Journal",
                ),
                # USD-only list price: the display path must convert to EUR
                # (or keep USD when no rate is available).
                journal_factory(
                    "2121-2121",
                    title="Dollar Listed Journal",
                    apc_prices=[{"currency": "USD", "price": 1000}],
                    search_text="Dollar Listed Journal",
                ),
                # List price in a currency without an exchange rate.
                journal_factory(
                    "2525-2525",
                    title="Hryvnia Listed Journal",
                    apc_prices=[{"currency": "UAH", "price": 120000}],
                    search_text="Hryvnia Listed Journal",
                ),
                # Corpus-cutoff boundary: exactly 4 window works stays in,
                # 3 drops out; a non-journal venue drops regardless.
                journal_factory(
                    "8181-8181",
                    title="Boundary Four Works",
                    works_2020_plus=4,
                    search_text="Boundary four works",
                ),
                journal_factory(
                    "8282-8282",
                    title="Boundary Three Works",
                    works_2020_plus=3,
                    search_text="Boundary three works",
                ),
                journal_factory(
                    "8383-8383",
                    title="Repository Venue",
                    type="repository",
                    works_2020_plus=50,
                    search_text="Repository venue",
                ),
                # Other OpenAlex venue types join the corpus once the
                # institution has >= 1 work in them (owner decision
                # 2026-11-04); the cutoff keeps applying to plain journals.
                journal_factory(
                    "8989-8989",
                    type="book series",
                    title="Lecture notes in computer science",
                    search_text="Lecture notes in computer science",
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
                Limitation(
                    code="window-2020",
                    source="project",
                    scope="global",
                    hint="Journal-level statistics use publication years "
                    "{window_start} and later (this institution's window).",
                ),
                Limitation(
                    code="scimagojr-lag",
                    source="scimago",
                    scope="journals.sjr",
                    hint="The latest available year typically lags one to two years behind.",
                ),
            ]
        )
        await session.commit()

        # Per-institution flags (journal_flags) replace the old journals
        # columns. Materialize one row per journal, then set the fixture
        # specifics; the corpus cutoff passes for everything except the
        # below-cutoff and boundary-out fixtures.
        home = Institution(
            name="University of Twente",
            code="ut",
            active=True,
            short_name="UT",
            ror="https://ror.org/006hf6230",
            library_url="https://lib.example",
            data_window_start=2010,
        )
        session.add(home)
        await session.flush()
        await session.execute(MATERIALIZE_SQL, {"iid": home.id})
        await session.execute(
            text(
                "UPDATE journal_flags SET works_window_plus = 10"
                " WHERE institution_id = :iid AND issn_l NOT IN"
                " ('1010-1010', '8181-8181', '8282-8282', '8383-8383', '8989-8989')"
            ),
            {"iid": home.id},
        )
        for issn, works in (
            ("1010-1010", 2),
            ("8181-8181", 4),
            ("8282-8282", 3),
            ("8383-8383", 50),
        ):
            await session.execute(
                text(
                    "UPDATE journal_flags SET works_window_plus = :works"
                    " WHERE institution_id = :iid AND issn_l = :issn"
                ),
                {"iid": home.id, "issn": issn, "works": works},
            )
        await session.execute(
            text(
                "UPDATE journal_flags SET deal_covered = true"
                " WHERE institution_id = :iid AND issn_l IN ('5555-5555', '1313-1313', '2727-2727')"
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
        await session.execute(
            text(
                "UPDATE journal_flags SET works_count = 7, works_window_plus = 200"
                " WHERE institution_id = :iid AND issn_l = '8989-8989'"
            ),
            {"iid": home.id},
        )
        await session.commit()
        # The browse-excluded flag is denormalized (migration 0011 backfills
        # prod); recompute here so the proceedings fixtures get real values.
        await session.execute(BROWSE_EXCLUDED_SQL, {"iid": home.id})
        # The price columns are denormalized, as after a harvest.
        await refresh_apcs(session)
        await session.commit()
    return client


def _issns(body: dict) -> set[str]:
    return {i["issn_l"] for i in body["items"]}


@requires_db
async def test_corpus_cutoff_boundary(api):
    """Journals below the 4-works window cutoff drop out; 4 exactly stays
    in; a non-journal venue drops regardless of its work count."""
    body = (await api.get("/api/v1/ut/journals")).json()
    issns = _issns(body)
    assert "8181-8181" in issns
    assert "1010-1010" not in issns
    assert "8282-8282" not in issns
    assert "8383-8383" not in issns

    # Unknown query params are ignored; the response carries no badge field.
    plain = (await api.get("/api/v1/ut/journals")).json()
    scoped = (await api.get("/api/v1/ut/journals", params={"scope": "all"})).json()
    assert scoped["total"] == plain["total"] > 0
    assert "in_quality_bar" not in plain["items"][0]


@requires_db
async def test_eligibility_toggles(api, db_engine):
    """The default browse view applies both eligibility toggles: an inactive
    journal and an active-but-unlisted one are hidden, `active=false &
    vouched=false` shows both, and the reported total matches the facet
    pass under the same toggles."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        inst = (
            await session.execute(select(Institution).where(Institution.code == "ut"))
        ).scalar_one()
        year = datetime.now(UTC).year
        session.add_all(
            [
                journal_factory("7070-7070", title="Ceased Journal", last_active_year=year - 5),
                journal_factory("7373-7373", title="Unlisted Journal", listed_in=[]),
                JournalFlags(institution_id=inst.id, issn_l="7070-7070", works_window_plus=10),
                JournalFlags(institution_id=inst.id, issn_l="7373-7373", works_window_plus=10),
            ]
        )
        await session.commit()

    default = (await api.get("/api/v1/ut/journals", params={"limit": 100})).json()
    assert "7070-7070" not in _issns(default)
    assert "7373-7373" not in _issns(default)

    off = (
        await api.get(
            "/api/v1/ut/journals", params={"active": "false", "vouched": "false", "limit": 100}
        )
    ).json()
    assert {"7070-7070", "7373-7373"} <= _issns(off)
    assert off["total"] == len(_issns(off))
    assert default["total"] == len(_issns(default))
    assert off["total"] - default["total"] == 2

    # One toggle at a time: each filter hides exactly its own fixture.
    active_only = (
        await api.get("/api/v1/ut/journals", params={"vouched": "false", "limit": 100})
    ).json()
    assert "7070-7070" not in _issns(active_only)
    assert "7373-7373" in _issns(active_only)
    vouched_only = (
        await api.get("/api/v1/ut/journals", params={"active": "false", "limit": 100})
    ).json()
    assert "7070-7070" in _issns(vouched_only)
    assert "7373-7373" not in _issns(vouched_only)


@requires_db
async def test_nonjournal_venues_browse_with_ut_works(api):
    body = (await api.get("/api/v1/ut/journals")).json()
    assert _issns(body) >= {"8989-8989"}
    assert body["facets"]["pub_type"]["book series"] == 1

    # The venue-type filter narrows to the series; its own facet keeps the
    # full distribution (drop-own-dimension).
    filtered = (await api.get("/api/v1/ut/journals", params={"pub_type": "book series"})).json()
    assert _issns(filtered) == {"8989-8989"}
    assert filtered["facets"]["pub_type"]["book series"] == 1

    # Free text finds the series by title, like any journal.
    hits = (await api.get("/api/v1/ut/journals", params={"q": "lecture notes"})).json()
    assert _issns(hits) == {"8989-8989"}


@requires_db
async def test_malformed_cursor_is_400(api):
    # "not-a-cursor" is pattern-legal ([A-Za-z0-9_-]), so it reaches
    # parse_cursor and the app-level ValueError handler answers 400.
    r = await api.get("/api/v1/ut/journals", params={"cursor": "not-a-cursor"})
    assert r.status_code == 400
    # Valid base64 but not JSON: same handler.
    junk = base64.urlsafe_b64encode(b"nonsense").decode()
    r = await api.get("/api/v1/ut/journals", params={"cursor": junk})
    assert r.status_code == 400


@pytest.mark.parametrize(
    "sort", ["2yr_mean_citedness", "relevance", "title"], ids=["twoyr", "relevance", "title"]
)
@requires_db
async def test_sort_pages_cleanly(api, sort):
    """Every sort key pages to exhaustion with no repeats. NULL twoyr must
    coalesce (never a NULL cursor or a 500) and relevance rank must cast
    its cursor to Numeric, not String."""
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"sort": sort, "q": "journal", "limit": 2}
        if cursor:
            params["cursor"] = cursor
        r = await api.get("/api/v1/ut/journals", params=params)
        assert r.status_code == 200
        body = r.json()
        seen += [i["issn_l"] for i in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
        if sort == "2yr_mean_citedness":
            payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            assert payload["v"] is not None
    assert cursor is None
    assert len(seen) == len(set(seen)) > 0


@requires_db
async def test_search_in_scopes(api):
    r = await api.get(
        "/api/v1/ut/journals", params={"q": "massachusetts", "search_in": "publisher"}
    )
    assert r.status_code == 200
    assert _issns(r.json()) == {"1234-5678"}
    # Same query in the title scope must not match the publisher.
    r = await api.get("/api/v1/ut/journals", params={"q": "massachusetts", "search_in": "title"})
    assert r.status_code == 200
    assert r.json()["total"] == 0
    # The default "all" scope matches publisher too.
    r = await api.get("/api/v1/ut/journals", params={"q": "massachusetts"})
    assert {"1234-5678"} <= _issns(r.json())
    # LIKE wildcards in user input stay literal, no crash.
    r = await api.get(
        "/api/v1/ut/journals", params={"q": "mass%achu_setts", "search_in": "publisher"}
    )
    assert r.status_code == 200
    assert r.json()["total"] == 0

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
async def test_facets_and_drop_own_filter(api):
    browse = (await api.get("/api/v1/ut/journals")).json()
    facets = browse["facets"]
    # 3333 + 1515 have paid articles; 1616, 2121, 2323 and 2525 a list price.
    assert facets["apc"] == {"true": 6, "false": browse["total"] - 6}
    for group in ("deal_coverage", "oa", "doaj", "apc"):
        assert sum(facets[group].values()) == browse["total"]
    assert facets["publisher"]["Massachusetts Institute of Technology Press"] == 1

    # Active filter: the apc facet excludes its own filter; the publisher
    # facet respects it.
    body = (await api.get("/api/v1/ut/journals", params={"has_apc": "true"})).json()
    assert body["total"] == 6
    assert body["facets"]["apc"] == facets["apc"]
    assert _issns(body) == {
        "3333-3333",
        "1515-1515",
        "1616-1616",
        "2121-2121",
        "2323-2323",
        "2525-2525",
    }

    # Chip facets must drop exactly their own filter. The variants used to
    # re-include it, so e.g. deal=covered rendered the "No deal" chip with
    # a zero count.
    body = (await api.get("/api/v1/ut/journals", params={"deal": "covered"})).json()
    assert body["total"] == 3  # 5555-5555, 1313-1313, 2727-2727 are deal-covered
    assert body["facets"]["deal_coverage"] == browse["facets"]["deal_coverage"]
    body = (await api.get("/api/v1/ut/journals", params={"oa": "true"})).json()
    assert body["facets"]["oa"] == browse["facets"]["oa"]

    # The apc facet drops only its own filter: has_works stays applied.
    # Regression: it used to drop has_works too. 1414-1414 and 8989-8989
    # are the only home-works fixtures and neither has APC evidence.
    body = (
        await api.get("/api/v1/ut/journals", params={"has_apc": "true", "has_works": "true"})
    ).json()
    assert body["total"] == 0
    assert body["facets"]["apc"] == {"true": 0, "false": 2}

    # has_apc=false excludes every journal with any APC info.
    body = (await api.get("/api/v1/ut/journals", params={"has_apc": "false", "limit": 100})).json()
    assert {"1515-1515", "3333-3333", "1616-1616"}.isdisjoint(_issns(body))
    assert body["total"] == len(body["items"])

    # Active publisher filter narrows to its journal.
    params = {"publisher": "Massachusetts Institute of Technology Press"}
    body = (await api.get("/api/v1/ut/journals", params=params)).json()
    assert _issns(body) == {"1234-5678"}


@requires_db
async def test_apc_fields_on_list_items(api):
    r = await api.get("/api/v1/ut/journals", params={"q": "priced"})
    assert r.status_code == 200
    (item,) = r.json()["items"]
    # No list price on this fixture: the shown price is the mean amount
    # paid in the newest OpenAPC period, and the paid block spans the
    # newest two. The periods carry no paid/zero split (NULL), and a
    # lowest amount of NULL falls back to the period's highest.
    assert (item["apc_source"], item["apc_currency"], item["apc_price"], item["apc_year"]) == (
        "openapc",
        "EUR",
        2200.0,
        2024,
    )
    assert item["apc_original_currency"] is None and item["apc_original_price"] is None
    assert (item["apc_low"], item["apc_high"]) == (2000.0, 2500.0)
    assert item["apc_stats"] == [
        {
            "period": 2024,
            "article_count": 8,
            "paid_count": None,
            "zero_count": None,
            "euro_min": None,
            "euro_max": 2500.0,
            "euro_mean": 2200.0,
        },
        {
            "period": 2023,
            "article_count": 5,
            "paid_count": None,
            "zero_count": None,
            "euro_min": None,
            "euro_max": 2000.0,
            "euro_mean": 1800.0,
        },
    ]

    # The OpenAlex list price wins when known: EUR over USD, dated by the
    # harvest, and no paid block.
    r = await api.get("/api/v1/ut/journals", params={"q": "fee listed"})
    (item,) = r.json()["items"]
    assert (item["apc_source"], item["apc_currency"], item["apc_price"], item["apc_year"]) == (
        "openalex",
        "EUR",
        2700.0,
        2026,
    )
    assert (item["apc_original_currency"], item["apc_original_price"]) == ("EUR", 2700.0)
    assert item["apc_low"] is None and item["apc_high"] is None and item["apc_stats"] == []

    # A USD list price shows in EUR at the rate of the refresh; the dollar
    # amount is kept for display.
    r = await api.get("/api/v1/ut/journals", params={"q": "dollar listed"})
    (item,) = r.json()["items"]
    assert (
        item["apc_source"],
        item["apc_currency"],
        item["apc_original_currency"],
        item["apc_original_price"],
    ) == ("openalex", "EUR", "USD", 1000.0)
    assert item["apc_price"] == _usd_in_eur(1000)

    # No exchange rate for the currency: the list price stays in it.
    r = await api.get("/api/v1/ut/journals", params={"q": "hryvnia listed"})
    (item,) = r.json()["items"]
    assert (
        item["apc_source"],
        item["apc_currency"],
        item["apc_price"],
        item["apc_original_currency"],
        item["apc_original_price"],
    ) == ("openalex", "UAH", 120000.0, "UAH", 120000.0)

    # No price evidence at all: nulls across the board.
    r = await api.get("/api/v1/ut/journals", params={"q": "quantum studies"})
    (item,) = r.json()["items"]
    assert item["apc_source"] is None
    assert item["apc_price"] is None and item["apc_low"] is None


@requires_db
async def test_oa_type_mapping_and_facet(api):
    r = await api.get("/api/v1/ut/journals", params={"limit": 100})
    by_issn = {i["issn_l"]: i["oa_type"] for i in r.json()["items"]}
    assert by_issn["3333-3333"] == "gold"  # doaj + apc evidence
    assert by_issn["4444-4444"] == "diamond"  # DOAJ canon: listed, no APC
    assert by_issn["3030-3030"] == "gold"  # DOAJ canon: listed with APC
    assert by_issn["5555-5555"] == "hybrid"  # deal-covered, not doaj
    assert by_issn["6666-6666"] == "subscription"
    assert by_issn["1515-1515"] == "gold"
    assert by_issn["2323-2323"] == "gold"  # fully-OA, priced (MDPI Water case)
    assert by_issn["2424-2424"] == "diamond"  # observed diamond works
    assert by_issn["2626-2626"] == "gold"  # observed gold works, no prices
    assert by_issn["2727-2727"] == "hybrid"  # closed works, deal-covered
    assert by_issn["2828-2828"] == "generic"  # OA, model unknown
    assert set(by_issn.values()) <= {"gold", "diamond", "generic", "hybrid", "subscription"}

    # OR semantics: gold OR diamond returns exactly those fixtures.
    r = await api.get("/api/v1/ut/journals", params={"oa_type": "gold,diamond"})
    assert r.status_code == 200
    assert _issns(r.json()) == {
        "3333-3333",
        "1515-1515",
        "4444-4444",
        "3030-3030",
        "2323-2323",
        "2424-2424",
        "2626-2626",
    }
    # Single value narrows to one fixture.
    r = await api.get("/api/v1/ut/journals", params={"oa_type": "diamond"})
    assert _issns(r.json()) == {"4444-4444", "2424-2424"}

    # The facet's own filter is excluded from its counts, so every option
    # stays visible (with the rest of the filter set applied).
    oa_facets = r.json()["facets"]["oa_type"]
    assert oa_facets["diamond"] == 2
    assert oa_facets["gold"] == 5
    assert oa_facets["hybrid"] == 3
    assert oa_facets["generic"] == 1
    # Feedback 2026-11-05: the facet renders most open first, not in
    # jsonb's arbitrary key order. The fixture corpus observes every
    # value, so the order is total here.
    assert list(oa_facets) == ["diamond", "gold", "hybrid", "generic", "subscription"]

    # Unknown vocabulary is a 422, not a silent empty result.
    r = await api.get("/api/v1/ut/journals", params={"oa_type": "gold,bogus"})
    assert r.status_code == 422


@requires_db
async def test_language_facet_and_filter(api):
    """Feedback 2026-11-05: filter journals by their (modal work) language."""
    body = (await api.get("/api/v1/ut/journals")).json()
    assert body["facets"]["language"] == {"en": 2, "nl": 1}

    # The filter narrows the list; its facet drops its own filter so every
    # observed language stays visible with counts under the remaining set.
    r = (await api.get("/api/v1/ut/journals", params={"language": "nl"})).json()
    assert _issns(r) == {"4444-4444"}
    assert r["items"][0]["language"] == "nl"
    assert r["facets"]["language"] == {"en": 2, "nl": 1}

    # Comma multi-select ORs; unknown codes match nothing.
    r = (await api.get("/api/v1/ut/journals", params={"language": "en,nl"})).json()
    assert _issns(r) == {"1111-1111", "2222-2222", "4444-4444"}
    assert (await api.get("/api/v1/ut/journals", params={"language": "xx"})).json()["total"] == 0


@requires_db
async def test_proceedings_exclusion(api):
    body = (await api.get("/api/v1/ut/journals", params={"limit": 100})).json()
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
        "deal_cap_reached",
        "works",
        "shared_topics",
    }
    # No fixture journal here is deal-covered, so False proves the flag
    # flows through SimilarJournalItem.
    assert items[0]["deal_cap_reached"] is False
    # Fixture journals carry no UT works and no deal, so the teaser cuts are
    # empty and every item lands in "all" only.
    assert bundle["institution"] == []
    assert bundle["deals"] == []

    # Unknown journal -> 404.
    r = await api.get("/api/v1/ut/journals/0000-0000/similar")
    assert r.status_code == 404


@requires_db
async def test_semantic_search_distance_cap(api, monkeypatch):
    """Semantic search serves only journals within the 0.32 cosine-distance
    cap: the near vector lands in total and items, the far one (distance 1)
    stays out of both."""
    from journal_browser.services import embeddings

    monkeypatch.setattr(embeddings, "encode_query", lambda q: _vec(0))
    r = await api.get("/api/v1/ut/journals/semantic-search", params={"q": "open science"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert [i["issn_l"] for i in body["items"]] == ["1717-1717"]
    assert body["next_cursor"] is None


@requires_db
async def test_healthz_serves_with_db(api):
    r = await api.get("/api/v1/healthz")
    assert r.status_code == 200


@requires_db
async def test_meta_freshness_and_limitations(api):
    """/{code}/meta/freshness serves the institution display block from its
    row; limitations substitute the institution's own window start."""
    r = await api.get("/api/v1/ut/meta/freshness")
    assert r.status_code == 200
    settings = r.json()
    assert settings["institution"] == "University of Twente"
    assert settings["institution_short"] == "UT"
    assert settings["ror"] == "https://ror.org/006hf6230"
    assert settings["library_url"] == "https://lib.example"
    # Optional display fields serve the row verbatim: None when unset.
    assert settings["oa_guide_url"] is None
    assert settings["support_email"] is None
    assert settings["research_portal_url"] is None

    r = await api.get("/api/v1/ut/meta/limitations")
    assert r.status_code == 200
    hints = {h["code"]: h["hint"] for h in r.json()}
    # {window_start} hints render the scoped institution's year (2010
    # here), not a global 2020; the other hint passes through verbatim.
    assert hints["window-2020"] == (
        "Journal-level statistics use publication years 2010 and later (this institution's window)."
    )
    assert hints["scimagojr-lag"].startswith("The latest available year")


@pytest.fixture
async def bare_client(api, monkeypatch):
    monkeypatch.setenv("JB_ADMIN_PASSWORD", "route-test-pw")
    reset_settings_cache()
    yield api
    reset_settings_cache()


@requires_db
async def test_route_precedence(bare_client):
    """Fixed prefixes are not shadowed by /{institution_code}: the routers
    in main.py are included in a load-bearing order."""
    from journal_browser.main import app

    paths = list(app.openapi()["paths"].keys())
    prefixes = ("/api/v1/admin", "/api/v1/feedback", "/api/v1/docs")
    fixed = [i for i, p in enumerate(paths) if p.startswith(prefixes)]
    first_scoped = min(i for i, p in enumerate(paths) if "{institution_code}" in p)
    assert fixed, "no admin/feedback/docs routes found"
    assert first_scoped > max(fixed), (
        "a /{institution_code} route shadows a fixed prefix; "
        "router include order in main.py changed"
    )

    res = await bare_client.get("/api/v1/admin/deals")
    assert res.status_code == 401
    res = await bare_client.get("/api/v1/docs")
    assert res.status_code == 200


# ── Institution-rank tie-break + semantic total (regression folds) ────────


@pytest.fixture
async def rank_api(client, db, db_engine, institution_factory):
    """Two identically-titled journals — one with UT works, one without —
    plus a third distinct title, so FTS rank, prefix tier and global
    prominence tie and the institution nudge alone decides."""
    async with db_engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    ut = await institution_factory(code="ut", data_window_start=2020)
    common = {"title": "Water Management Reports", "search_text": "Water Management Reports"}
    db.add_all(
        [
            journal_factory("1111-2222", works_count=5000, **common),
            journal_factory("3333-4444", works_count=5000, **common),
            journal_factory(
                "5555-6666",
                title="Water Management X",
                search_text="Water Management X",
                works_count=5000,
            ),
        ]
    )
    await db.flush()
    db.add_all(
        [
            JournalFlags(
                institution_id=ut.id, issn_l="1111-2222", works_count=4, works_window_plus=10
            ),
            JournalFlags(
                institution_id=ut.id, issn_l="3333-4444", works_count=0, works_window_plus=10
            ),
            JournalFlags(
                institution_id=ut.id, issn_l="5555-6666", works_count=0, works_window_plus=10
            ),
        ]
    )
    await db.commit()
    return client


@requires_db
async def test_institution_works_break_ties(rank_api):
    """The institution's own works count (journal_flags) breaks rank ties
    toward journals UT publishes in; exact FTS hits keep fuzzy off."""
    r = await rank_api.get("/api/v1/ut/journals", params={"q": "water management"})
    assert r.status_code == 200
    body = r.json()
    assert body["fuzzy"] is False
    issns = [i["issn_l"] for i in body["items"]]
    # Identical titles tie on rank, prefix tier and prominence; the
    # UT-published journal (works_count 4) must come first.
    assert issns[0] == "1111-2222"
    assert set(issns) == {"1111-2222", "3333-4444", "5555-6666"}


@requires_db
async def test_semantic_total_exact_and_capped(client, db, institution_factory, monkeypatch):
    """The semantic total counts only in-cap rows: exact below the cap
    with paging through all of them, capped above it, where paging stops
    at the cap and a cursor past the end serves an empty page."""
    inst = await institution_factory(code="ut")
    for n, (issn, vec_i) in enumerate(
        [("aaaa-0001", 0), ("aaaa-0002", 0), ("aaaa-0003", 0), ("bbbb-0001", 1)]
    ):
        db.add(
            journal_factory(
                issn, title=f"Journal {n}", search_text=f"Journal {n}", embedding=_vec(vec_i)
            )
        )
        db.add(
            JournalFlags(institution_id=inst.id, issn_l=issn, works_count=10, works_window_plus=10)
        )
    await db.commit()

    from journal_browser.services import embeddings
    from journal_browser.services.search import similar

    monkeypatch.setattr(embeddings, "encode_query", lambda q: _vec(0))
    url = "/api/v1/ut/journals/semantic-search"
    body = (await client.get(url, params={"q": "water technology", "limit": 2})).json()
    # Three same-vector journals sit within the distance cap (the
    # orthogonal bbbb-0001 stays out of items and total); order follows
    # the (distance, issn) key.
    assert body["total"] == 3
    assert [i["issn_l"] for i in body["items"]] == ["aaaa-0001", "aaaa-0002"]
    page2 = (
        await client.get(url, params={"q": "wq", "limit": 2, "cursor": body["next_cursor"]})
    ).json()
    assert [i["issn_l"] for i in page2["items"]] == ["aaaa-0003"]
    assert page2["next_cursor"] is None

    monkeypatch.setattr(similar, "SEMANTIC_TOTAL_CAP", 2)
    page1 = (await client.get(url, params={"q": "wq", "limit": 1})).json()
    assert page1["total"] == 2
    assert [i["issn_l"] for i in page1["items"]] == ["aaaa-0001"]
    page2 = (
        await client.get(url, params={"q": "wq", "limit": 1, "cursor": page1["next_cursor"]})
    ).json()
    assert [i["issn_l"] for i in page2["items"]] == ["aaaa-0002"]
    assert page2["next_cursor"] is None
    page3 = (await client.get(url, params={"q": "wq", "limit": 1, "cursor": "2"})).json()
    assert page3["items"] == []
    assert page3["total"] == 2
