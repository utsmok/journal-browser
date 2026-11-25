"""GET /api/v1/{code}/journals/batch: the saved-journal (shortlist) lookup.

Rows must match the browse list for the same institution, deal names must
follow the deal-participation rules, and anything outside the browsable
corpus is reported as missing."""

from types import SimpleNamespace

import pytest

from conftest import journal_factory, requires_db
from journal_browser.config import get_settings
from journal_browser.harvest.denorm import refresh_apcs
from journal_browser.models import (
    Deal,
    DealInstitution,
    DealJournal,
    InstitutionWorksStats,
    JournalFlags,
    Publisher,
)

ALPHA, BETA, GAMMA, DELTA, CUTOFF = (
    "1000-0001",
    "1000-0002",
    "1000-0003",
    "1000-0004",
    "1000-0005",
)


@pytest.fixture
async def api(client, db, db_engine, institution_factory):
    """ut and rug host: ALPHA (DOAJ, green route, list price, yearly stats),
    BETA (covered by one current deal per institution), GAMMA (inactive and
    not vouched), DELTA (only archive and admin-excluded deal rows) and
    CUTOFF (below the corpus cutoff for ut)."""
    # The browse list's fuzzy fallback needs the trigram extension, which
    # create_all skips (migration 0004 adds it in a real database).
    async with db_engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    ut = await institution_factory(code="ut")
    rug = await institution_factory(code="rug")
    wiley = Publisher(name="Wiley")
    db.add_all(
        [
            journal_factory(
                ALPHA,
                title="Alpha Journal",
                publisher_name="Alpha Press",
                is_in_doaj=True,
                jisc_allows_sa_accepted=True,
                latest_quartile="Q1",
                apc_prices=[{"currency": "EUR", "price": 2400}],
                search_text="Alpha Journal",
            ),
            journal_factory(BETA, title="Beta Journal", search_text="Beta Journal"),
            journal_factory(
                GAMMA,
                title="Gamma Journal",
                last_active_year=2000,
                listed_in=[],
                search_text="Gamma Journal",
            ),
            journal_factory(DELTA, title="Delta Journal", search_text="Delta Journal"),
            journal_factory(CUTOFF, title="Cutoff Journal", search_text="Cutoff Journal"),
            wiley,
        ]
    )
    await db.flush()
    ut_deal = Deal(
        esac_id="shared-1", status="current", publisher_id=wiley.id, duration_text="2024-2027"
    )
    archived = Deal(esac_id="archived-1", status="archive")
    rug_only = Deal(esac_id="rug-1", status="current")
    excluded = Deal(esac_id="excluded-1", status="current")
    db.add_all([ut_deal, archived, rug_only, excluded])
    await db.flush()
    db.add_all(
        [
            DealInstitution(deal_id=ut_deal.id, institution_id=ut.id),
            DealInstitution(deal_id=archived.id, institution_id=ut.id),
            DealInstitution(deal_id=rug_only.id, institution_id=rug.id),
            DealInstitution(deal_id=excluded.id, institution_id=ut.id),
            DealJournal(deal_id=ut_deal.id, issn=BETA, issn_l=BETA, source="manual"),
            DealJournal(deal_id=archived.id, issn=DELTA, issn_l=DELTA, source="manual"),
            DealJournal(deal_id=rug_only.id, issn=BETA, issn_l=BETA, source="manual"),
            DealJournal(
                deal_id=excluded.id, issn=ALPHA, issn_l=ALPHA, source="manual", excluded=True
            ),
            JournalFlags(institution_id=ut.id, issn_l=ALPHA, works_count=12, works_window_plus=10),
            JournalFlags(
                institution_id=ut.id,
                issn_l=BETA,
                works_count=7,
                works_window_plus=10,
                deal_covered=True,
            ),
            JournalFlags(institution_id=ut.id, issn_l=GAMMA, works_count=0, works_window_plus=10),
            JournalFlags(institution_id=ut.id, issn_l=DELTA, works_count=3, works_window_plus=10),
            JournalFlags(institution_id=ut.id, issn_l=CUTOFF, works_count=9, works_window_plus=2),
            JournalFlags(
                institution_id=rug.id,
                issn_l=BETA,
                works_count=2,
                works_window_plus=10,
                deal_covered=True,
            ),
            *[
                InstitutionWorksStats(
                    institution_id=ut.id,
                    issn_l=ALPHA,
                    year=year,
                    works_count=count,
                    source="pure_canon",
                )
                for year, count in ((2022, 5), (2023, 4), (2024, 3))
            ],
        ]
    )
    await db.flush()
    await refresh_apcs(db)
    await db.commit()
    return SimpleNamespace(client=client, ut_deal=ut_deal.id, rug_only=rug_only.id)


@requires_db
async def test_batch_rows_match_the_browse_list(api):
    r = await api.client.get(
        "/api/v1/ut/journals/batch", params={"issn_l": f"{GAMMA},{ALPHA},{BETA}"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [j["issn_l"] for j in body["items"]] == [GAMMA, ALPHA, BETA]
    assert body["missing"] == []
    alpha, beta = body["items"][1], body["items"][2]
    assert alpha["works"] == 12
    assert alpha["green_oa"] == "accepted"
    assert (alpha["apc_source"], alpha["apc_currency"], alpha["apc_price"]) == (
        "openalex",
        "EUR",
        2400.0,
    )
    # The admin-excluded deal row does not cover the journal.
    assert alpha["deals"] == []
    assert beta["deal_covered"] is True
    assert beta["deals"] == [
        {"id": api.ut_deal, "publisher_name": "Wiley", "duration_text": "2024-2027"}
    ]

    # The eligibility toggles hide GAMMA from the default browse list; the
    # saved list still serves it.
    browse = await api.client.get(
        "/api/v1/ut/journals", params={"q": "Gamma", "include_facets": "false"}
    )
    assert browse.json()["items"] == []
    # Every list field is computed exactly as the browse list computes it.
    browse = await api.client.get(
        "/api/v1/ut/journals", params={"q": "Alpha", "include_facets": "false"}
    )
    row = browse.json()["items"][0]
    assert {key: alpha[key] for key in row} == row


@requires_db
async def test_batch_reports_missing(api, monkeypatch):
    settings = get_settings().model_copy(update={"ignored_issns": [DELTA]})
    monkeypatch.setattr("journal_browser.services.search.get_settings", lambda: settings)
    r = await api.client.get(
        "/api/v1/ut/journals/batch", params={"issn_l": f"{ALPHA},{CUTOFF},{DELTA},9999-9999"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Below the corpus cutoff, on the admin ignore-list, unknown.
    assert [j["issn_l"] for j in body["items"]] == [ALPHA]
    assert body["missing"] == [CUTOFF, DELTA, "9999-9999"]


@requires_db
async def test_batch_normalises_issn_ls(api):
    r = await api.client.get(
        "/api/v1/ut/journals/batch", params={"issn_l": " 10000001,1000-0002,1000-000X,1000-0001"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [j["issn_l"] for j in body["items"]] == [ALPHA, BETA]
    assert body["missing"] == ["1000-000X"]


@requires_db
async def test_batch_accepts_one_hundred_issn_ls(api):
    r = await api.client.get(
        "/api/v1/ut/journals/batch",
        params={"issn_l": ",".join(f"{n:04d}-0000" for n in range(1, 101))},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["missing"]) == 100


@requires_db
@pytest.mark.parametrize(
    "issn_l",
    [
        ",",
        "1000-0001,,1000-0002",
        "not-an-issn",
        ",".join(f"{n:04d}-0000" for n in range(1, 102)),
    ],
    ids=["empty", "blank-item", "malformed", "too-many"],
)
async def test_batch_rejects_bad_issn_ls(api, issn_l):
    r = await api.client.get("/api/v1/ut/journals/batch", params={"issn_l": issn_l})
    assert r.status_code == 422


@requires_db
async def test_batch_deal_names_follow_participation(api):
    ut = await api.client.get("/api/v1/ut/journals/batch", params={"issn_l": f"{DELTA},{ALPHA}"})
    # An archived deal and an admin-excluded deal row cover nothing.
    assert [j["deals"] for j in ut.json()["items"]] == [[], []]
    assert [j["deal_covered"] for j in ut.json()["items"]] == [False, False]
    # The same journal sits under another institution's own deal.
    rug = await api.client.get("/api/v1/rug/journals/batch", params={"issn_l": BETA})
    assert rug.json()["items"][0]["deals"] == [
        {"id": api.rug_only, "publisher_name": None, "duration_text": None}
    ]


@requires_db
async def test_batch_year_range_rescopes_works(api):
    full = await api.client.get("/api/v1/ut/journals/batch", params={"issn_l": ALPHA})
    ranged = await api.client.get(
        "/api/v1/ut/journals/batch", params={"issn_l": ALPHA, "year_from": 2023, "year_to": 2024}
    )
    assert (full.json()["items"][0]["works"], ranged.json()["items"][0]["works"]) == (12, 7)


@requires_db
async def test_batch_unknown_institution_is_404(api):
    r = await api.client.get("/api/v1/nope/journals/batch", params={"issn_l": ALPHA})
    assert r.status_code == 404
