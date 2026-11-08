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


@requires_db
async def test_refresh_funder_links_dedupes_twin_matched_via_both_keys(db):
    """Regression: one OpenAlex twin matching a jisc funder via BOTH ror and
    fundref used to violate funder_links_pkey on the fundref INSERT."""
    from journal_browser.harvest.funders import refresh_funder_links
    from journal_browser.models import FunderLink, OpenalexFunder

    db.add(JiscFunder(id=701, ror="04ad7pn51", fundref="100009795"))
    db.add(OpenalexFunder(openalex_id="F1", ror="04ad7pn51", fundref="100009795"))
    await db.flush()

    links = await refresh_funder_links(db)
    assert links == 1
    rows = (await db.execute(select(FunderLink).where(FunderLink.funder_id == 701))).scalars().all()
    assert len(rows) == 1
    assert (rows[0].source, rows[0].source_id, rows[0].via) == ("openalex", "F1", "ror")


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


# ── harvest_openalex_funders: raws-driven singleton backfill ─────────────


class _FakeFunderEntity:
    """Shaped after an aletheca Funder entity for _openalex_row."""

    def __init__(self, pk: str):
        self.id = f"https://openalex.org/{pk}"
        self.ids = {"ror": "https://ror.org/04ad7pn51", "doi": "10.13039/100009795"}
        self.display_name = "NWO"
        self.country_code = "nl"
        self.description = None
        self.awards_count = 10
        self.works_count = 100
        self.cited_by_count = 5


@requires_db
async def test_openalex_funders_backfilled_from_work_funders(db, institution_factory, monkeypatch):
    from journal_browser.harvest import funders as funders_mod
    from journal_browser.harvest.funders import harvest_openalex_funders
    from journal_browser.models import HarvestRun, Work, WorkFunder

    inst = await institution_factory()
    run = HarvestRun(source="test", entity_type="works", config_fingerprint="t")
    db.add(run)
    await db.flush()
    db.add(
        Work(
            institution_id=inst.id,
            pure_uuid="uuid-f",
            doi_normalized="10.1234/f1",
            title="t",
            norm_title="t",
            year=2020,
            first_seen_run=run.id,
            last_seen_run=run.id,
        )
    )
    db.add(
        WorkFunder(
            institution_id=inst.id,
            pure_uuid="uuid-f",
            funder_openalex_id="F1234567890",
            funder_name="NWO",
        )
    )
    await db.commit()

    calls: list[str] = []

    class _FakeClient:
        def __init__(self, **kwargs):
            self.funders = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url: str):
            calls.append(url)
            return _FakeFunderEntity(url.rsplit("/", 1)[-1])

    monkeypatch.setattr(funders_mod, "AlethecaClient", _FakeClient)

    stats = await harvest_openalex_funders(db)
    assert stats["linked_ids"] == 1
    assert stats["todo"] == 1
    assert stats["fetched"] == 1
    assert stats["with_ror"] == 1
    assert stats["with_fundref"] == 1
    assert calls == ["https://openalex.org/F1234567890"]

    row = (
        await db.execute(select(OpenalexFunder).where(OpenalexFunder.openalex_id == "F1234567890"))
    ).scalar_one()
    assert row.display_name == "NWO"
    assert row.ror == "04ad7pn51"
    assert row.fundref == "100009795"

    # Rerun: id known, nothing fetched, links still rebuilt.
    stats2 = await harvest_openalex_funders(db)
    assert stats2["todo"] == 0
    assert stats2["fetched"] == 0
    assert len(calls) == 1
