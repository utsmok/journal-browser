"""DOAJ canon harvest: CSV normalization, ISSN matching, stamping, and the
reworked oa_type decision (DOAJ gold/diamond + generic fallback)."""

import pytest
from sqlalchemy import select

from conftest import journal_factory, requires_db
from journal_browser.harvest.common import HarvestDataError
from journal_browser.harvest.doaj import (
    _apply_rows,
    _stamp_not_listed,
    harvest_doaj,
    journal_fields,
)
from journal_browser.models import Journal
from journal_browser.services.search import oa_type_value


def _row(**overrides) -> dict[str, str]:
    row = {
        "Journal title": "International Journal of Applied Earth Observations and Geoinformation",
        "Journal URL": "https://www.sciencedirect.com/journal/jag",
        "Journal ISSN (print version)": "1569-8432",
        "Journal EISSN (online version)": "1872-826X",
        "Publisher": "Elsevier",
        "APC": "Yes",
        "APC amount": "3610 USD",
    }
    row.update(overrides)
    return row


def test_journal_fields_normalization():
    fields = journal_fields(_row())
    assert fields is not None
    assert fields["homepage_url"] == "https://www.sciencedirect.com/journal/jag"
    assert fields["has_apc"] is True
    assert (fields["apc_max"], fields["apc_currency"]) == (3610.0, "USD")
    assert set(fields["issns"]) == {"1569-8432", "1872-826X"}

    # No APC: has_apc False with no parsed charge.
    no_apc = journal_fields(_row(APC="No", APC_amount=""))
    assert no_apc is not None
    assert (no_apc["has_apc"], no_apc["apc_max"]) == (False, None)

    # Several declarations: the first wins.
    multi = journal_fields(_row(**{"APC amount": "1000000 IDR; 100 USD"}))
    assert (multi["apc_max"], multi["apc_currency"]) == (1000000.0, "IDR")

    # Unparseable amount keeps has_apc but drops the price.
    odd = journal_fields(_row(**{"APC amount": "see website"}))
    assert (odd["has_apc"], odd["apc_max"]) == (True, None)

    # Garbage ISSNs only: nothing to match on.
    assert (
        journal_fields(
            _row(
                **{
                    "Journal ISSN (print version)": "not-an-issn",
                    "Journal EISSN (online version)": "",
                }
            )
        )
        is None
    )


def test_oa_type_value_mirror():
    # DOAJ canon: listed with charges -> gold; listed without -> diamond.
    assert oa_type_value(False, True, False, False, doaj_in_doaj=True, doaj_has_apc=True) == "gold"
    assert (
        oa_type_value(False, True, False, False, doaj_in_doaj=True, doaj_has_apc=False) == "diamond"
    )
    # Observed prices (OpenAlex list price / OpenAPC) make it gold even
    # without a DOAJ match (has_charges=True).
    assert oa_type_value(True, True, True, False, doaj_in_doaj=False, doaj_has_apc=False) == "gold"
    # Observed work color beats the generic fallback.
    assert oa_type_value(False, True, False, False, "gold") == "gold"
    assert oa_type_value(False, True, False, True, "closed") == "hybrid"
    # OA with no model evidence at all: generic, never diamond.
    assert oa_type_value(False, True, False, False) == "generic"
    # Deal-covered but no OA evidence stays hybrid; nothing at all is
    # subscription.
    assert oa_type_value(False, False, False, True) == "hybrid"
    assert oa_type_value(False, False, False, False) == "subscription"


@requires_db
async def test_apply_rows_matches_variant_issns(db):
    db.add_all(
        [
            # Matched via the linking ISSN itself.
            journal_factory("1569-8432", is_oa=True, search_text=None),
            # Matched via a variant ISSN in journals.issns.
            journal_factory(
                "0303-2434",
                is_oa=True,
                issns=["0303-2434", "1569-8432", "1872-826X"],
                search_text=None,
            ),
            # Untouched: no ISSN overlap.
            journal_factory("9999-9991", is_oa=True, search_text=None),
        ]
    )
    await db.commit()

    fields = journal_fields(_row())
    matched = await _apply_rows(db, [fields])
    assert matched == 2

    result = await db.execute(select(Journal))
    rows = {j.issn_l: j for j in result.scalars()}
    for issn in ("1569-8432", "0303-2434"):
        row = rows[issn]
        assert row.doaj_in_doaj is True
        assert row.doaj_has_apc is True
        assert row.doaj_apc_max == 3610.0
        assert row.doaj_homepage_url == "https://www.sciencedirect.com/journal/jag"
        assert row.doaj_harvested_at is not None
    assert rows["9999-9991"].doaj_in_doaj is None


@requires_db
async def test_stamp_not_listed_targets_oa_candidates(db):
    db.add_all(
        [
            journal_factory("1111-1119", is_oa=True, search_text=None),  # stamped False
            journal_factory("2222-2229", is_in_doaj=True, search_text=None),  # stamped False
            # untouched
            journal_factory("3333-3339", is_oa=False, is_in_doaj=False, search_text=None),
            # untouched
            journal_factory("4444-4449", is_oa=True, doaj_in_doaj=True, search_text=None),
        ]
    )
    await db.commit()
    stamped = await _stamp_not_listed(db)
    assert stamped == 2
    result = await db.execute(select(Journal))
    rows = {j.issn_l: j.doaj_in_doaj for j in result.scalars()}
    assert rows["1111-1119"] is False
    assert rows["2222-2229"] is False
    assert rows["3333-3339"] is None
    assert rows["4444-4449"] is True


async def _fake_download(payload: bytes):
    async def _download(session, ingest, source, entity_type, url, suffix, **kw):
        return payload, True

    return _download


@requires_db
async def test_harvest_doaj_fails_on_renamed_column(db, monkeypatch):
    """A renamed DOAJ column must fail the run, not land zero rows silently."""
    download = await _fake_download(b"Journal Title,Journal URL\nT,u\n")
    monkeypatch.setattr("journal_browser.harvest.doaj.download_to_landing", download)
    with pytest.raises(HarvestDataError, match="missing columns"):
        await harvest_doaj(db)


@requires_db
async def test_harvest_doaj_fails_on_zero_issn_rows(db, monkeypatch):
    download = await _fake_download(
        b"Journal title,Journal URL,Journal ISSN (print version),"
        b"Journal EISSN (online version),Publisher,APC,APC amount\n"
        b"T,https://x,,,P,No,\n"
    )
    monkeypatch.setattr("journal_browser.harvest.doaj.download_to_landing", download)
    with pytest.raises(HarvestDataError, match="zero ISSN-bearing rows"):
        await harvest_doaj(db)
