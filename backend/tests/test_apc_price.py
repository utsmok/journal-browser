"""APC price rules: the publisher's list price stays apart from the amounts
actually paid, so articles an agreement paid for (€0 in OpenAPC) never
make a journal look free.

Covers the list-price choice and its EUR conversion (select_list_price),
the OpenAPC period figures (build_aggregates), the denormalized columns
both concepts read (refresh_apcs), the list and detail endpoints, and the
cost labels of the guided finder.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser import currency
from journal_browser.currency import to_eur, year_rate
from journal_browser.harvest.denorm import (
    MATERIALIZE_SQL,
    ListPrice,
    refresh_apcs,
    select_list_price,
)
from journal_browser.harvest.openapc import build_aggregates
from journal_browser.models import Institution, Journal, JournalApcAggregate
from journal_browser.schemas import RecommendDealSummary
from journal_browser.services.recommend import _extract_apc_and_cost
from journal_browser.vocab import ApcSource, OaType

# Journal of Membrane Science: a list price, and OpenAPC articles paid
# under a deal.
MEMBRANES = "0376-7388"
# Remote Sensing of Environment.
REMOTE = "0034-4257"
# Soft Computing: no list price, only paid articles.
PAID_ONLY = "1432-7643"
# Nature: a DOAJ price and nothing else.
DOAJ_ONLY = "0028-0836"
# Chemical Engineering Science: only €0 articles, no list price anywhere.
DEAL_ONLY = "0009-2509"

MEMBRANE_PRICES = [{"price": 4890, "currency": "USD"}, {"price": 4460, "currency": "EUR"}]
HARVESTED = datetime(2026, 10, 4, tzinfo=UTC)


@pytest.fixture
def rates(monkeypatch):
    """USD at 0.9 and no other currency: the entry choice and the
    conversion both read this one function."""
    monkeypatch.setattr(currency, "year_rate", lambda code: {"EUR": 1.0, "USD": 0.9}.get(code))


def _list(**sources) -> ListPrice:
    """select_list_price with the harvest years set, asserting it found one."""
    sources.setdefault("openalex_year", 2026)
    sources.setdefault("doaj_year", 2025)
    price = select_list_price(**sources)
    assert price is not None
    return price


def _usd_in_eur(amount: float) -> float:
    """An amount in USD at the bundled rate, as refresh_apcs stores it."""
    rate = year_rate("USD")
    assert rate is not None
    return round(amount * rate, 2)


def test_list_price_is_the_openalex_eur_entry():
    # One source lists the same price in several currencies.
    price = _list(apc_prices=MEMBRANE_PRICES, doaj_apc_max=5000, doaj_apc_currency="EUR")
    assert price == ListPrice(ApcSource.OPENALEX, "EUR", 4460.0, 2026, 4460.0)


def test_list_price_converts_to_eur_and_keeps_the_original(rates):
    usd = _list(apc_prices=[{"price": 4450, "currency": "USD"}])
    assert (usd.currency, usd.amount, usd.euro) == ("USD", 4450.0, 4005.0)

    # No exchange rate for the currency: the price keeps its own currency
    # and has no euro figure.
    uah = _list(apc_prices=[{"price": 120000, "currency": "UAH"}])
    assert (uah.currency, uah.amount, uah.euro) == ("UAH", 120000.0, None)

    # Beyond EUR and USD entries, an entry that converts wins.
    both = _list(
        apc_prices=[{"price": 120000, "currency": "UAH"}, {"price": 1000, "currency": "USD"}]
    )
    assert (both.currency, both.euro) == ("USD", 900.0)


def test_list_price_falls_back_to_doaj_then_to_nothing(rates):
    doaj = _list(doaj_apc_max=2500, doaj_apc_currency="USD")
    assert doaj == ListPrice(ApcSource.DOAJ, "USD", 2500.0, 2025, 2250.0)
    assert (
        select_list_price(
            apc_prices=None,
            doaj_apc_max=None,
            doaj_apc_currency=None,
            openalex_year=2026,
            doaj_year=2025,
        )
        is None
    )
    # An OpenAlex entry without a usable price is no list price.
    broken = _list(apc_prices=[{"currency": "EUR"}], doaj_apc_max=2500, doaj_apc_currency="USD")
    assert broken.source is ApcSource.DOAJ

    # Currency strings are normalized, >3-char codes and <=0 amounts are ignored.
    normalized = _list(
        apc_prices=[
            {"price": 0, "currency": "EUR"},
            {"price": 500, "currency": "EURO"},
            {"price": 1200, "currency": " usd "},
        ]
    )
    assert (normalized.currency, normalized.amount, normalized.euro) == ("USD", 1200.0, 1080.0)
    assert select_list_price(apc_prices=[{"price": 0, "currency": "EUR"}]) is None
    assert select_list_price(doaj_apc_max=0, doaj_apc_currency="EUR") is None


def test_eur_conversion_reads_the_bundled_rate_table():
    assert year_rate("EUR") == 1.0
    usd = year_rate("USD")
    assert usd is not None and 0.8 < usd < 1.3
    assert to_eur(1000, "USD") == ("EUR", round(1000 * usd, 2))
    # XXX is not a quoted currency.
    assert year_rate("XXX") is None
    assert to_eur(120000, "XXX") == ("XXX", 120000)


async def _unmapped(issn):
    return None


async def test_paid_figures_skip_articles_an_agreement_paid_for():
    rows = [
        {"issn_l": MEMBRANES, "period": "2025", "euro": "0", "doi": "10.1/a"},
        {"issn_l": MEMBRANES, "period": "2025", "euro": "NA", "doi": "10.1/b"},
        {"issn_l": MEMBRANES, "period": "2024", "euro": "0", "doi": "10.1/c"},
        {"issn_l": MEMBRANES, "period": "2024", "euro": "2000", "doi": "10.1/d"},
        {"issn_l": MEMBRANES, "period": "2024", "euro": "3000", "doi": "10.1/e"},
    ]
    aggregates, _counters = await build_aggregates(rows, _unmapped)

    paid, deal_only = aggregates
    assert (paid["article_count"], paid["paid_count"], paid["zero_count"]) == (3, 2, 1)
    assert (paid["euro_min"], paid["euro_max"], paid["euro_mean"]) == (2000.0, 3000.0, 2500.0)
    assert (deal_only["article_count"], deal_only["paid_count"], deal_only["zero_count"]) == (
        2,
        0,
        1,
    )
    assert (deal_only["euro_min"], deal_only["euro_max"], deal_only["euro_mean"]) == (
        None,
        None,
        None,
    )


def _cost(item, oa_type=OaType.HYBRID, deal_covered=False, deal_summary=None):
    return _extract_apc_and_cost(item, oa_type, deal_covered, deal_summary, "Twente")


def test_cost_labels_name_the_list_price_or_the_paid_amount():
    listed = {
        "apc_source": "openalex",
        "apc_currency": "EUR",
        "apc_price": 4460.0,
        "apc_year": 2026,
        "apc_low": 2193.35,
        "apc_high": 2193.35,
        "apc_stats": [{"period": 2024, "euro_mean": 2193.35}],
    }
    display, cost, label = _cost(listed)
    assert (cost, label) == (4460.0, "€4,460 APC (list price)")
    assert (display.source, display.year, display.mean) == ("openalex", 2026, 2193.35)

    paid = {
        "apc_source": "openapc",
        "apc_currency": "EUR",
        "apc_price": 2193.35,
        "apc_year": 2024,
        "apc_low": 2000.0,
        "apc_high": 2500.0,
        "apc_stats": [{"period": 2024, "euro_mean": 2193.35}],
    }
    assert _cost(paid)[1:] == (2193.35, "~€2,193 APC (mean amount paid, OpenAPC 2024)")

    # A list price without an exchange rate has no euro estimate.
    unconverted = {**listed, "apc_currency": "UAH", "apc_price": 120000.0}
    assert _cost(unconverted)[1:] == (None, "UAH 120,000 APC (list price, no euro exchange rate)")

    # Deals and Diamond OA stay €0, whatever the list price says.
    assert _cost(listed, deal_covered=True)[2] == "€0 (Covered by Twente deal)"
    assert _cost(listed, oa_type=OaType.DIAMOND)[1:] == (0.0, "€0 (Diamond OA)")
    capped = RecommendDealSummary(publisher_name="Elsevier", is_capped=True, cap_reached=True)
    reached = _cost(listed, deal_covered=True, deal_summary=capped)
    assert reached[2] == "€4,460 APC (list price; deal cap reached)"
    # No price of any kind.
    assert _cost({"apc_source": None})[2] == "APC unknown"


@pytest.fixture
async def priced_api(client, db_engine):
    """The journals of the live-data review, with the OpenAPC periods as
    the ingest writes them."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        ut = Institution(
            name="University of Twente",
            code="ut",
            active=True,
            short_name="UT",
            ror="https://ror.org/006hf6230",
            library_url="https://lib.example",
            data_window_start=2010,
        )
        session.add(ut)
        session.add_all(
            [
                journal_factory(MEMBRANES, apc_prices=MEMBRANE_PRICES, harvested_at=HARVESTED),
                journal_factory(
                    REMOTE,
                    apc_prices=[
                        {"price": 4450, "currency": "USD"},
                        {"price": 4160, "currency": "EUR"},
                    ],
                    harvested_at=HARVESTED,
                ),
                journal_factory(PAID_ONLY),
                journal_factory(
                    DOAJ_ONLY,
                    doaj_apc_max=2500,
                    doaj_apc_currency="USD",
                    doaj_harvested_at=datetime(2025, 9, 1, tzinfo=UTC),
                ),
                journal_factory(DEAL_ONLY),
                JournalApcAggregate(
                    issn_l=MEMBRANES, period=2025, article_count=4, paid_count=0, zero_count=1
                ),
                JournalApcAggregate(
                    issn_l=MEMBRANES,
                    period=2024,
                    article_count=3,
                    paid_count=2,
                    zero_count=1,
                    euro_min=2000,
                    euro_max=3000,
                    euro_mean=2500,
                ),
                JournalApcAggregate(
                    issn_l=REMOTE, period=2026, article_count=1, paid_count=0, zero_count=0
                ),
                JournalApcAggregate(
                    issn_l=REMOTE, period=2025, article_count=17, paid_count=0, zero_count=0
                ),
                JournalApcAggregate(
                    issn_l=REMOTE,
                    period=2024,
                    article_count=22,
                    paid_count=22,
                    zero_count=0,
                    euro_min=1500,
                    euro_max=3000,
                    euro_mean=2193.35,
                ),
                JournalApcAggregate(
                    issn_l=PAID_ONLY,
                    period=2020,
                    article_count=3,
                    paid_count=2,
                    zero_count=1,
                    euro_min=1000,
                    euro_max=2000,
                    euro_mean=1500,
                ),
                JournalApcAggregate(
                    issn_l=DEAL_ONLY, period=2025, article_count=2, paid_count=0, zero_count=2
                ),
            ]
        )
        await session.flush()
        await session.execute(MATERIALIZE_SQL, {"iid": ut.id})
        await session.execute(
            text("UPDATE journal_flags SET works_window_plus = 10 WHERE institution_id = :iid"),
            {"iid": ut.id},
        )
        await refresh_apcs(session)
        await session.commit()
    return client


@requires_db
async def test_refresh_apcs_keeps_list_price_apart_from_paid_amount(priced_api, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        rows = {j.issn_l: j for j in (await session.execute(select(Journal))).scalars()}

    membranes = rows[MEMBRANES]
    assert (
        membranes.list_price_source,
        membranes.list_price_currency,
        membranes.list_price_amount,
        membranes.list_price_euro,
    ) == ("openalex", "EUR", Decimal("4460.00"), Decimal("4460.00"))
    assert membranes.list_price_year == 2026
    # The paid amount skips the period whose articles were all €0 or
    # without an amount.
    assert (membranes.latest_apc_euro, membranes.latest_apc_period) == (Decimal("2500.00"), 2024)

    remote = rows[REMOTE]
    assert remote.list_price_amount == Decimal("4160.00")
    assert (remote.latest_apc_euro, remote.latest_apc_period) == (Decimal("2193.35"), 2024)

    paid_only = rows[PAID_ONLY]
    assert paid_only.list_price_source is None
    assert (paid_only.latest_apc_euro, paid_only.latest_apc_period) == (Decimal("1500.00"), 2020)

    # Only €0 articles and no list price: no price at all, not €0.
    deal_only = rows[DEAL_ONLY]
    assert (deal_only.list_price_source, deal_only.latest_apc_euro) == (None, None)

    # DOAJ's maximum APC stands in where OpenAlex has no price.
    doaj = rows[DOAJ_ONLY]
    assert (
        doaj.list_price_source,
        doaj.list_price_currency,
        doaj.list_price_amount,
        doaj.list_price_year,
    ) == ("doaj", "USD", Decimal("2500.00"), 2025)
    euro = doaj.list_price_euro
    assert euro is not None and float(euro) == _usd_in_eur(2500)


@requires_db
async def test_list_rows_show_the_list_price_and_the_paid_block(priced_api):
    body = (await priced_api.get("/api/v1/ut/journals", params={"limit": 100})).json()
    items = {i["issn_l"]: i for i in body["items"]}

    # The list price is shown as such, in EUR, with the year OpenAlex was
    # harvested; the paid block sits next to it.
    item = items[MEMBRANES]
    assert (item["apc_source"], item["apc_currency"], item["apc_price"], item["apc_year"]) == (
        "openalex",
        "EUR",
        4460.0,
        2026,
    )
    assert (item["apc_original_currency"], item["apc_original_price"]) == ("EUR", 4460.0)
    assert (item["apc_low"], item["apc_high"]) == (2000.0, 3000.0)
    assert item["apc_stats"] == [
        {
            "period": 2024,
            "article_count": 3,
            "paid_count": 2,
            "zero_count": 1,
            "euro_min": 2000.0,
            "euro_max": 3000.0,
            "euro_mean": 2500.0,
        }
    ]

    # Without a list price the mean of the newest paid period stands in,
    # labelled OpenAPC with that period.
    item = items[PAID_ONLY]
    assert (item["apc_source"], item["apc_currency"], item["apc_price"], item["apc_year"]) == (
        "openapc",
        "EUR",
        1500.0,
        2020,
    )
    assert (item["apc_original_currency"], item["apc_original_price"]) == (None, None)
    assert (item["apc_low"], item["apc_high"]) == (1000.0, 2000.0)

    # Only €0 articles and no list price: no price, never €0.
    item = items[DEAL_ONLY]
    assert (item["apc_source"], item["apc_price"], item["apc_low"], item["apc_high"]) == (
        None,
        None,
        None,
        None,
    )

    # A DOAJ price in USD: shown in EUR, the dollar amount kept for display.
    item = items[DOAJ_ONLY]
    assert (
        item["apc_source"],
        item["apc_currency"],
        item["apc_original_currency"],
        item["apc_original_price"],
        item["apc_year"],
    ) == ("doaj", "EUR", "USD", 2500.0, 2025)
    assert item["apc_price"] == _usd_in_eur(2500)


@requires_db
async def test_apc_sort_and_filter_follow_the_list_price(priced_api):
    body = (
        await priced_api.get(
            "/api/v1/ut/journals",
            params={"sort": "apc", "dir": "asc", "has_apc": "true", "limit": 100},
        )
    ).json()
    # Prices rise by the list price, with the paid-only journal first; the
    # €0-only journal has no price and drops out of the filter.
    assert [i["issn_l"] for i in body["items"]] == [PAID_ONLY, DOAJ_ONLY, REMOTE, MEMBRANES]

    # Without has_apc=true, unpriced journals still sort AFTER every EUR price
    # on ascending sort ("cheapest first"), not first as €0.
    all_asc = (
        await priced_api.get(
            "/api/v1/ut/journals",
            params={"sort": "apc", "dir": "asc", "limit": 100},
        )
    ).json()
    assert [i["issn_l"] for i in all_asc["items"]] == [
        PAID_ONLY,
        DOAJ_ONLY,
        REMOTE,
        MEMBRANES,
        DEAL_ONLY,
    ]


@requires_db
async def test_detail_bundle_carries_the_same_price_fields(priced_api):
    body = (await priced_api.get(f"/api/v1/ut/journals/{MEMBRANES}")).json()
    journal = body["journal"]
    assert (journal["apc_source"], journal["apc_price"], journal["apc_year"]) == (
        "openalex",
        4460.0,
        2026,
    )
    assert (journal["apc_low"], journal["apc_high"]) == (2000.0, 3000.0)
    # Every period is listed with the split the evidence table explains.
    assert [
        (a["period"], a["article_count"], a["paid_count"], a["zero_count"], a["euro_mean"])
        for a in body["apc_aggregates"]
    ] == [(2025, 4, 0, 1, None), (2024, 3, 2, 1, 2500.0)]
