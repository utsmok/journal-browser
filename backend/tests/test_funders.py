"""Funder canon: JISC ror/fundref extraction + canon upsert idempotency.

Unit tests assert the OPF identifiers-list extraction literally; DB tests
run the real normalize/upsert path on the throwaway test database.
"""

import pytest
from sqlalchemy import select

from conftest import requires_db
from journal_browser.harvest.funders import _upsert, normalize_fundref, normalize_ror
from journal_browser.harvest.jisc_normalize import _funder_row, normalize_jisc
from journal_browser.models import (
    HarvestRun,
    JiscFunder,
    OpenalexFunder,
    SourceRecord,
)

ROR = {"type": "ror", "identifier": "https://ror.org/04ad7pn51"}
FUNDREF = {"type": "fundref", "identifier": "http://dx.doi.org/10.13039/100009795"}


def _funder_payload(funder_id: int, identifiers: list | None) -> dict:
    """OPF funder record shaped after the live corpus (phrases included)."""
    meta = {
        "name": [{"name": "NWO", "language": "en"}],
        "url": [{"url": "https://nwo.example", "language": "en"}],
        "country": "nl",
    }
    if identifiers is not None:
        meta["identifiers"] = identifiers
        meta["identifiers_phrases"] = [{"value": "ror"}]
    return {"id": funder_id, "funder_metadata": meta, "funder_metadata_phrases": []}


# ── canon normalizers ─────────────────────────────────────────────────────


def test_normalize_ror_shapes():
    assert normalize_ror("https://ror.org/04ad7pn51") == "04ad7pn51"
    assert normalize_ror("http://ROR.ORG/04AD7PN51") == "04ad7pn51"
    assert normalize_ror(None, "", "https://ror.org/04ad7pn51") == "04ad7pn51"
    assert normalize_ror("https://nwo.example") is None
    assert normalize_ror("https://ror.org/short") is None


def test_normalize_fundref_shapes():
    assert normalize_fundref("http://dx.doi.org/10.13039/100009795") == "100009795"
    assert normalize_fundref("https://doi.org/10.13039/501100001871") == "501100001871"
    assert normalize_fundref("100009795") == "100009795"
    assert normalize_fundref(None, "10.13039/100009795") == "100009795"
    assert normalize_fundref("https://ror.org/04ad7pn51") is None
    assert normalize_fundref("10.13039/abc") is None


# ── openalex ids mapping ──────────────────────────────────────────────────


def test_openalex_row_fundref_from_doi_and_crossref_ids():
    from types import SimpleNamespace

    from journal_browser.harvest.funders import _openalex_row

    f = SimpleNamespace(
        id="F4320308302",
        ids=SimpleNamespace(
            openalex="https://openalex.org/F4320308302",
            doi="10.13039/100005198",
            crossref="100005198",
            ror="https://ror.org/01wn80b84",
        ),
        display_name="NSF",
        country_code="US",
        description=None,
        awards_count=10,
        works_count=20,
        cited_by_count=30,
    )
    row = _openalex_row(f)
    assert row["ror"] == "01wn80b84"
    assert row["fundref"] == "100005198"
    assert row["grant_count"] == 10


# ── jisc funder identifiers extraction ────────────────────────────────────


def test_funder_row_extracts_ror_and_fundref():
    row = _funder_row("701", _funder_payload(701, [ROR, FUNDREF]))
    assert row is not None
    assert row["ror"] == "04ad7pn51"
    assert row["fundref"] == "100009795"


def test_funder_row_order_independent_and_repeatable():
    ids = [FUNDREF, ROR]
    a = _funder_row("701", _funder_payload(701, ids))
    b = _funder_row("701", _funder_payload(701, ids))
    assert a is not None and b is not None
    assert (a["ror"], a["fundref"]) == (b["ror"], b["fundref"]) == ("04ad7pn51", "100009795")


def test_funder_row_without_identifiers_yields_nulls():
    row = _funder_row("702", _funder_payload(702, None))
    assert row is not None
    assert row["ror"] is None
    assert row["fundref"] is None
    assert row["identifiers"] is None


def test_funder_row_unmatchable_identifiers_yields_nulls():
    row = _funder_row("703", _funder_payload(703, [{"type": "ror", "identifier": "not-a-ror"}]))
    assert row is not None
    assert row["ror"] is None
    assert row["fundref"] is None


# ── normalize + upsert idempotency (DB) ───────────────────────────────────


async def _land_funder(db, funder_id: int, payload: dict) -> None:
    run = HarvestRun(source="jisc_opf", entity_type="funder", config_fingerprint="test")
    db.add(run)
    await db.flush()
    db.add(
        SourceRecord(
            source="jisc_opf",
            entity_type="funder",
            source_pk=str(funder_id),
            payload=payload,
            content_hash=f"h{funder_id}",
            harvest_run_id=run.id,
        )
    )
    await db.commit()


@requires_db
async def test_normalize_jisc_funder_ids(db):
    await _land_funder(db, 701, _funder_payload(701, [ROR, FUNDREF]))
    stats = await normalize_jisc(db)
    assert stats["jisc_funders"] == 1
    funder = await db.get(JiscFunder, 701)
    assert funder.ror == "04ad7pn51"
    assert funder.fundref == "100009795"


@requires_db
async def test_normalize_jisc_funder_rerun_idempotent(db):
    await _land_funder(db, 701, _funder_payload(701, [ROR, FUNDREF]))
    await normalize_jisc(db)
    stats = await normalize_jisc(db)
    assert stats["jisc_funders"] == 1
    rows = (await db.execute(select(JiscFunder).where(JiscFunder.id == 701))).scalars().all()
    assert len(rows) == 1
    assert (rows[0].ror, rows[0].fundref) == ("04ad7pn51", "100009795")


async def test_openaire_row_from_funding_funder():
    from aireloom.models.project import FundingFunder, FundingJurisdiction

    from journal_browser.harvest.funders import _openaire_row

    funder = FundingFunder(
        id="nwo_________::NWO",
        shortname="NWO",
        name="Netherlands Organisation for Scientific Research (NWO)",
        jurisdiction=FundingJurisdiction(code="NL", label="Netherlands"),
        pid=None,
    )
    row = _openaire_row(funder)
    assert row["openaire_id"] == "nwo_________::NWO"
    assert row["short_name"] == "NWO"
    assert row["jurisdiction"] == "NL"
    assert row["ror"] is None
    with pytest.raises(RuntimeError, match="without id"):
        _openaire_row(FundingFunder(id="", shortname=None, name=None, jurisdiction=None, pid=None))


@requires_db
async def test_openalex_funder_upsert_idempotent(db):
    row = {
        "openalex_id": "F4320330286",
        "ror": "04ad7pn51",
        "fundref": "100009795",
        "display_name": "NWO",
        "country_code": "nl",
        "description": None,
        "grant_count": 1,
        "works_count": 2,
        "cited_by_count": 3,
    }
    assert await _upsert(db, OpenalexFunder, "openalex_id", [row]) == 1
    assert await _upsert(db, OpenalexFunder, "openalex_id", [dict(row, grant_count=9)]) == 1
    await db.commit()
    rows = (await db.execute(select(OpenalexFunder))).scalars().all()
    assert len(rows) == 1
    assert rows[0].grant_count == 9
    assert (rows[0].ror, rows[0].fundref) == ("04ad7pn51", "100009795")
