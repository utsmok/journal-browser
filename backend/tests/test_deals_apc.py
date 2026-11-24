"""Deal register and APC spend outcomes: the participation-gated public API,
latest-period APC aggregation with retired/data-window gates, the OpenAPC
aggregate/evidence build and rerun provenance links, JCT parsing and
agreement storage, ORM-vs-SQL coverage parity with cap-reached flags, and
admin deal CRUD with overrides and tombstones.

Replaces test_deals_api, test_openapc, test_openapc_rerun, test_jct,
test_deal_coverage, and test_admin_deals."""

import importlib.util
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.config import reset_settings_cache
from journal_browser.db import get_session
from journal_browser.harvest.common import HarvestDataError, parse_csv_rows, store_raw_file
from journal_browser.harvest.denorm import DEAL_FLAGS_SQL, refresh_deal_flags
from journal_browser.harvest.jct import (
    INDEX_URL,
    _store_agreement,
    parse_agreement,
    parse_index,
    row_issn,
    split_esac_id,
)
from journal_browser.harvest.openapc import _body, build_aggregates, build_evidence
from journal_browser.ingest import IngestSession
from journal_browser.main import app
from journal_browser.models import (
    ApcEvidence,
    Deal,
    DealInstitution,
    DealJournal,
    FunderLink,
    HarvestRun,
    Institution,
    IssnMap,
    JiscFunder,
    Journal,
    JournalFlags,
    ManualOverride,
    Publisher,
    Work,
    WorkFunder,
)
from journal_browser.services import funders as funders_service
from journal_browser.services.deal_coverage import dj_scope

PASSWORD = "test-admin-pw"

# The exact JCT upsert payload for the admin fixture's deal: a curated
# cap_text must survive this re-ingestion, and excluded rows must not be
# resurrected by it.
EM_AGREEMENT = {
    "esac_id": "em2019caul",
    "end_date": "2026-12-31",
    "ca_only": "",
    "data_url": "https://example.com/em.csv",
    "last_reviewed": "2026-01-15",
}
EM_JOURNALS = [
    {
        "Journal Name": "J Zero",
        "ISSN (Online)": "0000-0000",
        "ISSN (Print)": "",
        "Journal First Seen": "2024-01-01",
        "Journal Last Seen": "2025-01-01",
    }
]
EM_TOMBSTONE_AGREEMENT = EM_AGREEMENT | {
    "end_date": "",
    "ca_only": "no",
    "data_url": "https://jct.example/em",
    "last_reviewed": "",
}
EM_TOMBSTONE_INSTITUTIONS = [
    {
        "ROR ID": "https://ror.org/006hf6230",
        "Institution Name": "University of Twente",
        "Institution First Seen": "2026",
        "Institution Last Seen": "2026",
    }
]


# ── Public deals API ────────────────────────────────────────────────────────


@pytest.fixture
async def deals_api(client, db_engine):
    """Home institution with one participating deal (cap usage included) and
    a foreign deal whose sheet lists the same journal."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async with maker() as session:
        home = Institution(name="University of Twente", code="ut", active=True)
        session.add(home)
        await session.flush()
        pub = Publisher(name="Springer")
        other = Publisher(name="Karger")
        session.add_all([pub, other])
        await session.flush()
        twente_deal = Deal(
            publisher_id=pub.id,
            esac_id="sn2024ukb",
            status="current",
            start_year=2024,
            end_year=2026,
            cap_usage=[
                {
                    "year": 2026,
                    "pool": "full OA",
                    "total": 750,
                    "used": 610,
                    "as_of": "September 2026",
                },
                {"year": 2026, "total": 100, "used": 100},
            ],
        )
        foreign_deal = Deal(
            publisher_id=other.id,
            esac_id="kar2025surf",
            status="current",
            start_year=2025,
            end_year=2027,
            openaccess_nl_url="https://x",
        )
        session.add_all([twente_deal, foreign_deal])
        await session.flush()
        session.add(DealInstitution(deal_id=twente_deal.id, institution_id=home.id))
        # Active + listed so the default eligibility toggles keep the deal
        # fixture browsable; these tests are about deal scoping, not the
        # toggles.
        journal = journal_factory("1111-1111", title="Shared")
        session.add(journal)
        await session.flush()
        session.add_all(
            [
                DealJournal(
                    deal_id=deal.id, issn=journal.issn_l, issn_l=journal.issn_l, source="manual"
                )
                for deal in (twente_deal, foreign_deal)
            ]
        )
        await session.commit()
        ids = (twente_deal.id, foreign_deal.id, journal.issn_l)
    return client, ids


@requires_db
async def test_public_deals_register_contract(deals_api):
    """The register lists only participating deals; cap usage serializes with
    explicit nulls; the journal panel shows only the home-linked deal."""
    client, (twente_id, foreign_id, issn) = deals_api
    r = await client.get("/api/v1/ut/deals")
    assert r.status_code == 200
    got = {d["id"] for d in r.json()}
    # Participation = deal_institutions row: the register hides deals this
    # institution is not part of (no purge needed).
    assert got == {twente_id}
    assert foreign_id not in got
    # Unknown params are ignored; payload equals the plain listing.
    scoped = await client.get("/api/v1/ut/deals", params={"scope": "home"})
    assert {d["id"] for d in scoped.json()} == got

    cap_usage = [
        {
            "year": 2026,
            "pool": "full OA",
            "total": 750,
            "used": 610,
            "as_of": "September 2026",
            "note": None,
        },
        {"year": 2026, "pool": None, "total": 100, "used": 100, "as_of": None, "note": None},
    ]
    listing = {d["id"]: d for d in r.json()}
    assert listing[twente_id]["cap_usage"] == cap_usage
    detail = (await client.get(f"/api/v1/ut/deals/{twente_id}")).json()
    assert detail["cap_usage"] == cap_usage

    body = (await client.get(f"/api/v1/ut/journals/{issn}")).json()
    assert [d["esac_id"] for d in body["deals"]] == ["sn2024ukb"]


# ── APC spend: latest period per DOI, retired and window gates ─────────────


@pytest.fixture
async def apc_api(client, db_engine):
    """One participating deal covering a journal with APC evidence; a second
    deal whose effective list covers no works. The covered journal carries
    works each gate must keep out of the sums: a retired work and works
    outside both data-window bounds."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async with maker() as session:
        home = Institution(
            name="University of Twente",
            code="ut",
            active=True,
            data_window_start=2020,
            data_window_end=2024,
        )
        session.add(home)
        await session.flush()
        run = HarvestRun(source="pure", entity_type="works", config_fingerprint="t")
        session.add(run)
        await session.flush()
        pub = Publisher(name="Springer")
        session.add(pub)
        await session.flush()
        covered_deal = Deal(
            publisher_id=pub.id, esac_id="sn2024ukb", status="current", start_year=2024
        )
        bare_deal = Deal(
            publisher_id=pub.id, esac_id="sn2025bare", status="current", start_year=2025
        )
        session.add_all([covered_deal, bare_deal])
        await session.flush()
        session.add_all(
            [
                DealInstitution(deal_id=covered_deal.id, institution_id=home.id),
                DealInstitution(deal_id=bare_deal.id, institution_id=home.id),
            ]
        )
        covered_journal = Journal(issn_l="1111-1111", title="Covered", type="journal")
        bare_journal = Journal(issn_l="2222-2222", title="Bare", type="journal")
        session.add_all([covered_journal, bare_journal])
        await session.flush()
        session.add_all(
            [
                DealJournal(
                    deal_id=covered_deal.id,
                    issn=covered_journal.issn_l,
                    issn_l=covered_journal.issn_l,
                    source="manual",
                ),
                DealJournal(
                    deal_id=bare_deal.id,
                    issn=bare_journal.issn_l,
                    issn_l=bare_journal.issn_l,
                    source="manual",
                ),
            ]
        )

        def _work(uuid: str, doi: str, year: int, **kw) -> Work:
            return Work(
                institution_id=home.id,
                pure_uuid=uuid,
                doi_normalized=doi,
                title=f"Work {uuid}",
                norm_title=f"work {uuid}",
                year=year,
                journal_issn_l=covered_journal.issn_l,
                first_seen_run=run.id,
                last_seen_run=run.id,
                **kw,
            )

        session.add_all(
            [
                _work("w-apc", "10.1234/apc", 2024),
                _work("w-retired", "10.1234/retired", 2024, retired_at=func.now()),
                _work("w-old", "10.1234/old", 2019),  # before the window start
                _work("w-future", "10.1234/future", 2025),  # after the window end
            ]
        )
        # Two evidence rows for the live DOI: only the latest period counts.
        # The gated-out works each carry their own evidence row.
        session.add_all(
            [
                ApcEvidence(institution_id=home.id, doi=doi, period=period, euro=euro)
                for doi, period, euro in [
                    ("10.1234/apc", 2023, 100.0),
                    ("10.1234/apc", 2024, 250.0),
                    ("10.1234/retired", 2024, 999.0),
                    ("10.1234/old", 2024, 999.0),
                    ("10.1234/future", 2024, 999.0),
                ]
            ]
        )
        await session.commit()
        ids = (covered_deal.id, bare_deal.id)
    return client, ids


@requires_db
async def test_apc_spend_latest_period_and_gates(apc_api):
    client, (covered_id, bare_id) = apc_api
    body = {d["id"]: d for d in (await client.get("/api/v1/ut/deals")).json()}
    # Latest period (2024) wins per DOI; the count is DOIs, not evidence rows.
    assert body[covered_id]["apc_euro_total"] == 250.0
    assert body[covered_id]["apc_n"] == 1
    # Retired works and works outside the institution data window carry
    # their own evidence but stay out of the sums; a deal whose effective
    # list covers no works reports zeros.
    assert body[bare_id]["apc_euro_total"] == 0.0
    assert body[bare_id]["apc_n"] == 0
    detail = (await client.get(f"/api/v1/ut/deals/{covered_id}")).json()
    assert (detail["apc_euro_total"], detail["apc_n"]) == (250.0, 1)


# ── OpenAPC: aggregate/evidence build + rerun provenance ───────────────────

TA_HEADER = (
    "institution,period,euro,doi,is_hybrid,opt_out,publisher,journal_full_title,issn,"
    "issn_print,issn_electronic,issn_l,license_ref,indexed_in_crossref,pmid,pmcid,ut,url,"
    "doaj,agreement,group_id"
)
TA_CSV = "\n".join(
    [
        TA_HEADER,
        # Twente, own issn_l, hybrid TRUE
        "University of Twente,2020,1000,10.1/tw1,TRUE,FALSE,Springer Nature,Soft Computing,"
        "1432-7643,1432-7643,1433-7479,1432-7643,http://cc/by,TRUE,NA,NA,NA,NA,TRUE,"
        "Springer Compact,g1",
        # Twente lower-case (filter is case-insensitive), agreement missing -> contracts fill
        "university of twente,2020,2000,10.1/tw2,FALSE,FALSE,Springer Nature,Soft Computing,"
        "1432-7643,1432-7643,1433-7479,1432-7643,http://cc/by,TRUE,NA,NA,NA,NA,FALSE,NA,g1",
        # Twente, no own issn_l -> strict map resolve to 3333-3335; euro NA
        "University of Twente,2020,NA,10.1/tw3,TRUE,FALSE,Wiley,Journal X,"
        "1111-1119,1111-1119,NA,NA,http://cc/by,TRUE,NA,NA,NA,NA,TRUE,NA,g2",
        # Twente, no ISSN at all and no group_id/doi -> source_pk falls back in _body
        "University of Twente,2021,500,NA,FALSE,FALSE,Elsevier,Journal Y,NA,NA,NA,NA,"
        "http://cc/by,FALSE,NA,NA,NA,NA,FALSE,NA,NA",
        # Other institution: aggregates only, never evidence
        "TU Delft,2020,999,10.1/nl1,TRUE,FALSE,Elsevier,Journal Z,9999-9994,NA,9999-9994,"
        "9999-9994,http://cc/by,TRUE,NA,NA,NA,NA,FALSE,NA,g3",
    ]
)

CONTRACTS_MAP = {"g2": "Wiley CA"}
# Strict: only this mapping exists; everything else resolves to None.
# (Fixture ISSNs must pass the mod-11 checksum gate in build_aggregates.)
ISSN_MAP = {"1111-1119": "3333-3335"}


async def _resolve(issn: str | None) -> str | None:
    return ISSN_MAP.get(issn or "")


def _ta_rows() -> list[dict[str, str]]:
    return parse_csv_rows(TA_CSV.encode())


@requires_db
async def test_openapc_build_aggregates_and_evidence():
    aggregates, counters = await build_aggregates(_ta_rows(), _resolve)

    by_key = {(a["issn_l"], a["period"]): a for a in aggregates}
    assert set(by_key) == {("1432-7643", 2020), ("3333-3335", 2020), ("9999-9994", 2020)}
    agg = by_key[("1432-7643", 2020)]
    assert agg["article_count"] == 2
    assert (agg["euro_min"], agg["euro_max"], agg["euro_mean"]) == (1000.0, 2000.0, 1500.0)
    # euro NA still counts as an article, but carries no euro stats.
    assert by_key[("3333-3335", 2020)]["article_count"] == 1
    assert (by_key[("3333-3335", 2020)]["euro_min"], by_key[("3333-3335", 2020)]["euro_max"]) == (
        None,
        None,
    )
    assert counters["rows"] == 5
    assert counters["unresolved_issn"] == 1  # Twente row with no ISSN at all
    assert counters["skipped"] == 0

    items, filled = await build_evidence(
        _ta_rows(), "University of Twente", _resolve, CONTRACTS_MAP
    )
    assert len(items) == 4  # the TU Delft row excluded; case-insensitive match
    assert filled == 1
    by_pk = {i["source_pk"] or f"idx:{i['fields']['doi']}": i for i in items}
    assert by_pk["g1|10.1/tw1"]["fields"] == {
        "doi": "10.1/tw1",
        "period": 2020,
        "euro": 1000.0,
        "is_hybrid": True,
        "agreement": "Springer Compact",
        "group_id": "g1",
        "issn_l": "1432-7643",
    }
    assert by_pk["g1|10.1/tw2"]["fields"]["agreement"] is None  # g1 not in contracts
    assert by_pk["g2|10.1/tw3"]["fields"]["agreement"] == "Wiley CA"  # filled
    assert by_pk["g2|10.1/tw3"]["fields"]["issn_l"] == "3333-3335"  # strict fallback
    # No ISSN and no group_id/doi -> issn_l NULL; the row-index source_pk
    # fallback is assigned later, in _body.
    fallback = items[3]
    assert fallback["source_pk"] is None
    assert fallback["fields"]["issn_l"] is None
    assert fallback["payload"] == _ta_rows()[3]  # verbatim row payload


APC_CSV = "\n".join(
    ["institution,period,euro,doi,issn,issn_l", "TU Delft,2021,900,10.1/ag1,1432-7643,1432-7643"]
)
CONTRACTS_CSV = "\n".join(["group_id,contract_name", "g1,Springer Compact"])

RERUN_BODIES = {
    "apc": APC_CSV.encode(),
    "ta": TA_CSV.encode(),
    "contracts": CONTRACTS_CSV.encode(),
    "additional_costs": b"",
    "bpc": b"",
}


async def _fake_download(session, ingest, source, entity_type, url, suffix, source_pk="", **kw):
    data = RERUN_BODIES[entity_type]
    await store_raw_file(session, source, entity_type, url, data, suffix, source_pk=source_pk)
    return data, True


@requires_db
async def test_openapc_rerun_keeps_evidence_links(db, monkeypatch, tmp_path):
    """A second OpenAPC run over unchanged files must not NULL the
    apc_evidence -> source_records provenance links."""
    monkeypatch.setenv("JB_LANDING_DIR", str(tmp_path))
    reset_settings_cache()
    monkeypatch.setattr("journal_browser.harvest.openapc.download_to_landing", _fake_download)
    try:
        for _ in range(2):  # second run: identical files -> duplicate source_records
            ingest = IngestSession(db)
            await ingest.start_run("openapc", "apc_row", "all", {})
            await _body(ingest, None)
        await db.commit()
        total, nulls = (
            await db.execute(select(func.count(), func.count(ApcEvidence.source_record_id)))
        ).one()
        assert total > 0
        assert nulls == total, f"{nulls}/{total} evidence rows lost their source_records link"
    finally:
        reset_settings_cache()


# ── JCT: parse rules + agreement storage ───────────────────────────────────

INDEX_CSV = """ESAC ID,Relationship,End Date,C/A Only,Data URL,Last Reviewed
kar2026caul,,2026-12-31,yes,https://example.com/kar.csv,2026-01-15
acm2025eifl,Consortium,2025-06-30,,https://example.com/acm.csv,2025-01-10
broken-row,,2027-01-01,,,
"""

# Journals x institutions cross product, plus one ISSN-less journal (duplicated
# across both institutions — dedupe happens first, so it counts once).
AGREEMENT_HEADER = "Journal Name,ISSN (Print),ISSN (Online),Journal First Seen,Journal Last Seen,Institution Name,ROR ID,Institution First Seen,Institution Last Seen"  # noqa: E501
AGREEMENT_CSV = (
    AGREEMENT_HEADER
    + """
Journal A,0043-1397,2049-3630,2024-01-01,2026-01-01,University of Twente,https://ror.org/006hf6230,2024-01-01,2026-01-01
Journal A,0043-1397,2049-3630,2024-01-01,2026-01-01,MIT,https://ror.org/042tr2w39,2024-01-01,2026-01-01
Journal B,1234-567X,,2025-02-01,2026-02-01,University of Twente,https://ror.org/006hf6230,2024-01-01,2026-01-01
Journal B,1234-567X,,2025-02-01,2026-02-01,MIT,https://ror.org/042tr2w39,2024-01-01,2026-01-01
Journal NoISSN,,,2025-03-01,2026-03-01,MIT,https://ror.org/042tr2w39,2024-01-01,2026-01-01
Journal NoISSN,,,2025-03-01,2026-03-01,University of Twente,https://ror.org/006hf6230,2024-01-01,2026-01-01
"""
)


def test_jct_parse_rules():
    assert split_esac_id("kar2026caul") == ("kar", 2026, "caul")
    assert split_esac_id("iop2024") == ("iop", 2024, None)
    assert split_esac_id("nodigits") == ("nodigits", None, None)
    assert split_esac_id("2026caul") == (None, 2026, "caul")
    # Online ISSN preferred; a broken online value falls back to print.
    assert row_issn({"ISSN (Online)": "2049-3630", "ISSN (Print)": "0043-1397"}) == "2049-3630"
    assert row_issn({"ISSN (Online)": "junk", "ISSN (Print)": "00431397"}) == "0043-1397"
    assert row_issn({"ISSN (Online)": "", "ISSN (Print)": ""}) is None

    agreements = parse_index(parse_csv_rows(INDEX_CSV.encode()))
    assert [a["esac_id"] for a in agreements] == ["kar2026caul", "acm2025eifl"]
    # Rows without ESAC ID + Data URL are dropped; duplicate ESAC IDs kept once.
    dupped = parse_index(
        parse_csv_rows(INDEX_CSV.replace("acm2025eifl,Consortium", "kar2026caul,Dup").encode())
    )
    assert [a["esac_id"] for a in dupped] == ["kar2026caul"]
    with pytest.raises(HarvestDataError, match="missing columns"):
        parse_index([{"ESAC ID": "x1", "Data URL": "u", "Unexpected": "y"}])

    journals, institutions, skipped = parse_agreement(parse_csv_rows(AGREEMENT_CSV.encode()))
    assert len(journals) == 2 and skipped == 1
    assert {j["Journal Name"] for j in journals} == {"Journal A", "Journal B"}
    assert {i["ROR ID"] for i in institutions} == {
        "https://ror.org/006hf6230",
        "https://ror.org/042tr2w39",
    }


@requires_db
async def test_jct_store_agreement_and_idempotency(db):
    agreement = parse_index(parse_csv_rows(INDEX_CSV.encode()))[0]
    journals, institutions, _ = parse_agreement(parse_csv_rows(AGREEMENT_CSV.encode()))
    fetched = "2026-10-22T00:00:00+00:00"
    await _store_agreement(db, agreement, journals, institutions, fetched)
    await db.commit()

    deal = await db.scalar(select(Deal).where(Deal.esac_id == "kar2026caul"))
    assert (deal.start_year, deal.end_year, deal.consortium) == (2026, 2026, "caul")
    assert deal.corresponding_authors_only is True and deal.status == "current"
    assert deal.jct_data_url == "https://example.com/kar.csv"
    assert str(deal.last_reviewed) == "2026-01-15"
    assert deal.publisher_id is not None
    assert deal.provenance == [
        {"source": "jct", "url": INDEX_URL, "fetched_at": fetched},
        {"source": "jct", "url": agreement["data_url"], "fetched_at": fetched},
    ]
    journal_rows = (
        await db.scalars(
            select(DealJournal).where(DealJournal.deal_id == deal.id).order_by(DealJournal.issn)
        )
    ).all()
    # A: online ISSN preferred; B: print fallback (online empty).
    assert [(j.issn, j.journal_name, j.source) for j in journal_rows] == [
        ("1234-567X", "Journal B", "jct"),
        ("2049-3630", "Journal A", "jct"),
    ]
    assert {j.first_seen for j in journal_rows} == {"2024-01-01", "2025-02-01"}
    links = (
        await db.scalars(select(DealInstitution).where(DealInstitution.deal_id == deal.id))
    ).all()
    assert len(links) == 2
    assert {lnk.first_seen for lnk in links} == {"2024-01-01"}

    await _store_agreement(db, agreement, journals, institutions, fetched)
    await db.commit()
    assert await db.scalar(select(func.count()).select_from(Deal)) == 1
    assert await db.scalar(select(func.count()).select_from(DealJournal)) == 2
    assert await db.scalar(select(func.count()).select_from(Institution)) == 2
    assert await db.scalar(select(func.count()).select_from(DealInstitution)) == 2

    # A rerun refreshes the jct provenance entries and keeps entries from
    # other sources (owner curation pointers survive a JCT refresh).
    refreshed = "2026-11-20T00:00:00+00:00"
    deal.provenance = [
        {"source": "owner_curation", "date": "2026-10-22"},
        {"source": "jct", "url": INDEX_URL, "fetched_at": fetched},
        {"source": "jct", "url": agreement["data_url"], "fetched_at": fetched},
    ]
    await db.flush()
    await _store_agreement(db, agreement, journals, institutions, refreshed)
    await db.commit()
    await db.refresh(deal)
    assert deal.provenance == [
        {"source": "owner_curation", "date": "2026-10-22"},
        {"source": "jct", "url": INDEX_URL, "fetched_at": refreshed},
        {"source": "jct", "url": agreement["data_url"], "fetched_at": refreshed},
    ]


# ── Coverage parity + cap-reached flags ────────────────────────────────────


async def _seed_scopes(db):
    shared = Institution(code="shared", name="S")  # journal_override = False
    override = Institution(code="override", name="O")  # journal_override = True
    db.add_all([shared, override])
    await db.flush()
    db.add_all(
        [
            Journal(issn_l="1111-111X", title="Shared covered"),
            Journal(issn_l="2222-2220", title="Shared excluded"),
            Journal(issn_l="3333-3339", title="Scoped only"),
        ]
    )
    deal = Deal(esac_id="cov2026", status="current")
    db.add(deal)
    await db.flush()
    db.add_all(
        [
            DealInstitution(deal_id=deal.id, institution_id=shared.id),
            DealInstitution(deal_id=deal.id, institution_id=override.id, journal_override=True),
            # Shared sheet rows: 1111 covered, 2222 admin-excluded.
            DealJournal(deal_id=deal.id, issn="1111-111X", issn_l="1111-111X", source="manual"),
            DealJournal(
                deal_id=deal.id,
                issn="2222-2220",
                issn_l="2222-2220",
                source="manual",
                excluded=True,
            ),
            # Override-scoped row only visible to the override institution.
            DealJournal(
                deal_id=deal.id,
                institution_id=override.id,
                issn="3333-3339",
                issn_l="3333-3339",
                source="manual",
            ),
        ]
    )
    await db.commit()
    return shared, override


async def _orm_covered(db, institution):
    rows = (
        await db.execute(
            select(DealJournal.issn_l)
            .select_from(Deal)
            .join(
                DealInstitution,
                (DealInstitution.deal_id == Deal.id)
                & (DealInstitution.institution_id == institution.id),
            )
            .join(
                DealJournal,
                (DealJournal.deal_id == Deal.id)
                & dj_scope(institution.id)
                & DealJournal.excluded.is_not(True),
            )
            .where(Deal.status == "current")
        )
    ).scalars()
    return set(rows)


async def _sql_covered(db, institution):
    for issn in ("1111-111X", "2222-2220", "3333-3339"):
        db.add(JournalFlags(institution_id=institution.id, issn_l=issn, deal_covered=False))
    await db.commit()
    await db.execute(DEAL_FLAGS_SQL, {"iid": institution.id})
    await db.commit()
    rows = await db.execute(
        select(JournalFlags.issn_l).where(
            JournalFlags.institution_id == institution.id,
            JournalFlags.deal_covered.is_(True),
        )
    )
    return set(rows.scalars())


@requires_db
async def test_orm_scope_matches_denorm_sql(db):
    """dj_scope (ORM) and DEAL_FLAGS_SQL must return the same effective
    coverage per institution on the same fixture."""
    shared, override = await _seed_scopes(db)
    for inst in (shared, override):
        assert await _orm_covered(db, inst) == await _sql_covered(db, inst), inst.code
    # Spot-check the actual expected sets, not just equality of two empties.
    assert await _orm_covered(db, shared) == {"1111-111X"}
    assert await _orm_covered(db, override) == {"3333-3339"}


async def _seed_caps(db):
    """One institution, eight journals, six current deals: reached (2026
    used=total), unreached (used<total), no cap data, latest-year-reached,
    older-year-reached, and used-never-reported."""
    inst = Institution(code="caps", name="C", active=True)
    db.add(inst)
    await db.flush()
    db.add_all(
        [
            Journal(issn_l=issn_l, title=title, type="journal", search_text=title)
            for issn_l, title in [
                ("4444-4444", "Single reached"),
                ("5555-5555", "Single unreached"),
                ("6666-6666", "No cap data"),
                ("7777-7777", "Reached plus unreached"),
                ("8888-8888", "Both reached"),
                ("9999-9999", "Only old year reached"),
                ("1212-1212", "Used never reported"),
                ("1010-1010", "Uncovered"),
            ]
        ]
    )
    usage = {
        "reached": [{"year": 2026, "total": 100, "used": 100}],
        "unreached": [{"year": 2026, "total": 100, "used": 40}],
        "nodata": None,
        "latest": [
            {"year": 2025, "total": 10, "used": 2},
            {"year": 2026, "total": 10, "used": 10},
        ],
        "oldonly": [
            {"year": 2025, "total": 5, "used": 5},
            {"year": 2026, "total": 5, "used": 1},
        ],
        "usednull": [{"year": 2026, "total": 5, "used": None}],
    }
    deals = {}
    for i, (name, cap) in enumerate(usage.items()):
        # Omit, not None: an explicit None inserts JSON null, which the
        # cap SQL's IS NOT NULL guard does not treat as "no data".
        kw = {"cap_usage": cap} if cap is not None else {}
        deals[name] = Deal(esac_id=f"cap{chr(65 + i)}", status="current", **kw)
    db.add_all(deals.values())
    await db.flush()
    db.add_all(
        [DealInstitution(deal_id=deal.id, institution_id=inst.id) for deal in deals.values()]
    )
    cover = [
        ("reached", "4444-4444"),
        ("unreached", "5555-5555"),
        ("nodata", "6666-6666"),
        ("reached", "7777-7777"),
        ("unreached", "7777-7777"),
        ("reached", "8888-8888"),
        ("latest", "8888-8888"),
        ("oldonly", "9999-9999"),
        ("usednull", "1212-1212"),
    ]
    db.add_all(
        [
            DealJournal(deal_id=deals[key].id, issn=issn_l, issn_l=issn_l, source="manual")
            for key, issn_l in cover
        ]
    )
    await db.commit()
    return inst


@requires_db
async def test_cap_reached_true_only_when_all_covering_deals_reached(db):
    inst = await _seed_caps(db)
    await refresh_deal_flags(db, inst.id)

    async def _flags():
        rows = (
            await db.execute(
                select(
                    JournalFlags.issn_l,
                    JournalFlags.deal_covered,
                    JournalFlags.deal_cap_reached,
                ).where(JournalFlags.institution_id == inst.id)
            )
        ).all()
        return {r.issn_l: (r.deal_covered, r.deal_cap_reached) for r in rows}

    got = await _flags()
    assert got["4444-4444"] == (True, True)  # one deal, latest year used >= total
    assert got["5555-5555"] == (True, False)  # one deal, used < total
    assert got["6666-6666"] == (True, False)  # covered deal without cap_usage data
    assert got["7777-7777"] == (True, False)  # one reached + one unreached
    assert got["8888-8888"] == (True, True)  # both deals reached via latest year
    assert got["9999-9999"] == (True, False)  # only an older entry year reached
    assert got["1212-1212"] == (True, False)  # used never reported
    assert got["1010-1010"] == (False, False)  # uncovered journal stays false
    # Re-refresh converges: the guarded write is idempotent.
    await refresh_deal_flags(db, inst.id)
    assert await _flags() == got


# ── Admin deal CRUD ────────────────────────────────────────────────────────


@pytest.fixture
async def admin_api(db_engine, monkeypatch):
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    reset_settings_cache()
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with maker() as session:
        session.add_all(
            [
                Institution(name="University of Twente", code="ut", active=True),
                Institution(name="RuG", code="rug", active=True),
                Publisher(name="Emerald Publishing group"),
            ]
        )
        await session.flush()
        pub_id = await session.scalar(select(Publisher.id))
        deal = Deal(
            publisher_id=pub_id,
            esac_id="em2019caul",
            status="current",
            corresponding_authors_only=False,
            cap_text="300 articles per year",
            cap_numbers={"2024": 300},
            provenance=[],
            needs_curation=True,
            needs_curation_reason="duplicate sheet",
        )
        session.add(deal)
        await session.flush()
        session.add_all(
            [
                Journal(issn_l="0000-0000", title="J Zero", type="journal"),
                Journal(issn_l="1111-1111", title="J One", type="journal"),
                IssnMap(issn="9999-8888", issn_l="0000-0000", source="test"),
                DealJournal(deal_id=deal.id, issn="0000-0000", issn_l="0000-0000", source="jct"),
                DealJournal(deal_id=deal.id, issn="1111-1111", issn_l="1111-1111", source="jct"),
            ]
        )
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.clear()
    reset_settings_cache()


async def _login(client: AsyncClient) -> dict[str, str]:
    r = await client.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def _deal_id(admin_api: AsyncClient, headers: dict[str, str]) -> int:
    listing = (await admin_api.get("/api/v1/admin/deals", headers=headers)).json()
    return listing[0]["id"]


@requires_db
async def test_admin_deal_list_create_and_detail(admin_api):
    headers = await _login(admin_api)
    deals = (await admin_api.get("/api/v1/admin/deals", headers=headers)).json()
    assert len(deals) == 1
    d = deals[0]
    assert d["publisher"] == "Emerald Publishing group"
    assert d["esac_id"] == "em2019caul"
    assert d["capped"] is True and d["cap_numbers"] == {"2024": 300}
    assert d["journal_count"] == 2
    assert d["participations"] == []
    assert d["needs_curation"] is True

    detail = (await admin_api.get(f"/api/v1/admin/deals/{d['id']}", headers=headers)).json()
    assert {(j["issn"], j["source"], j["excluded"]) for j in detail["journals"]} == {
        ("0000-0000", "jct", False),
        ("1111-1111", "jct", False),
    }
    r = await admin_api.get("/api/v1/admin/deals/99999", headers=headers)
    assert r.status_code == 404

    r = await admin_api.post(
        "/api/v1/admin/deals",
        headers=headers,
        json={"publisher_name": "Wiley", "esac_id": "wiley2026nl", "start_year": 2026},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["publisher"] == "Wiley" and body["status"] == "current"
    # Duplicate esac_id -> 409; missing publisher -> 422.
    r = await admin_api.post(
        "/api/v1/admin/deals",
        headers=headers,
        json={"publisher_name": "X", "esac_id": "em2019caul"},
    )
    assert r.status_code == 409
    r = await admin_api.post("/api/v1/admin/deals", headers=headers, json={"esac_id": "x2026"})
    assert r.status_code == 422


@requires_db
async def test_admin_deal_update_records_overrides(admin_api, db_engine):
    headers = await _login(admin_api)
    deal_id = await _deal_id(admin_api, headers)
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}",
        headers=headers,
        json={"summary": "Hand-fixed summary", "cap_numbers": None, "status": "archive"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "archive" and body["summary"] == "Hand-fixed summary"
    assert body["cap_numbers"] is None and body["capped"] is False
    assert body["needs_curation"] is False and body["needs_curation_reason"] is None
    # The dismissal records WHAT was reviewed, for reason-aware suppression.
    assert body["curation_resolved_reason"] == "duplicate sheet"

    async with async_sessionmaker(db_engine)() as session:
        deal = await session.get(Deal, deal_id)
        assert deal is not None
        assert str(deal.last_reviewed) == date.today().isoformat()
        assert deal.curation_resolved_reason == "duplicate sheet"
        fields = set(
            await session.scalars(
                select(ManualOverride.field).where(
                    ManualOverride.table_name == "deals",
                    ManualOverride.row_key == str(deal_id),
                )
            )
        )
        # Curation columns are harvest-owned: no override rows for them, so
        # no stale override can suppress future curation reasons.
        assert fields == {"summary", "cap_numbers", "status"}

    # Validation: bad status / bad cap_numbers key / unknown field / esac clash.
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}", headers=headers, json={"status": "bogus"}
    )
    assert r.status_code == 422
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}", headers=headers, json={"cap_numbers": {"20x4": 1}}
    )
    assert r.status_code == 422
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}", headers=headers, json={"consortium": "nope"}
    )
    assert r.status_code == 422
    r = await admin_api.post(
        "/api/v1/admin/deals", headers=headers, json={"publisher_name": "Other", "esac_id": "zz"}
    )
    other_id = r.json()["id"]
    r = await admin_api.put(
        f"/api/v1/admin/deals/{other_id}", headers=headers, json={"esac_id": "em2019caul"}
    )
    assert r.status_code == 409


@requires_db
async def test_admin_deal_cap_usage_and_nullable_clears(admin_api, db_engine):
    headers = await _login(admin_api)
    deal_id = await _deal_id(admin_api, headers)
    usage = [
        {
            "year": 2026,
            "pool": "hybrid",
            "total": 300,
            "used": 261,
            "as_of": "October 2026",
            "note": "library email, OUP hybrid pool",
        },
        {"year": 2026, "total": 150, "used": 150},
    ]
    # Responses normalize omitted optional fields to explicit nulls.
    expected = [
        dict(usage[0]),
        {"year": 2026, "pool": None, "total": 150, "used": 150, "as_of": None, "note": None},
    ]
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}", headers=headers, json={"cap_usage": usage}
    )
    assert r.status_code == 200
    assert r.json()["cap_usage"] == expected
    detail = (await admin_api.get(f"/api/v1/admin/deals/{deal_id}", headers=headers)).json()
    assert detail["cap_usage"] == expected

    async with async_sessionmaker(db_engine)() as session:
        deal = await session.get(Deal, deal_id)
        assert deal is not None
        assert deal.cap_usage == usage
        override = await session.scalar(
            select(ManualOverride).where(
                ManualOverride.table_name == "deals",
                ManualOverride.row_key == str(deal_id),
                ManualOverride.field == "cap_usage",
            )
        )
        assert override is not None

    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}",
        headers=headers,
        json={"cap_usage": [{"year": 2026, "total": 10, "used": -1}]},
    )
    assert r.status_code == 422
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}",
        headers=headers,
        json={"cap_usage": [{"year": 1800, "total": 10}]},
    )
    assert r.status_code == 422

    # Explicit null clears nullable fields; non-nullable ones reject null.
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}", headers=headers, json={"cap_usage": None}
    )
    assert r.status_code == 200
    assert r.json()["cap_usage"] is None
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}", headers=headers, json={"cap_text": None, "summary": None}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["cap_text"] is None and body["summary"] is None
    for key in ("status", "start_year", "end_year", "corresponding_authors_only", "publisher_id"):
        r = await admin_api.put(f"/api/v1/admin/deals/{deal_id}", headers=headers, json={key: None})
        assert r.status_code == 422, key


@requires_db
async def test_admin_deal_journals_and_participation_tombstones(admin_api, db_engine):
    headers = await _login(admin_api)
    deal_id = await _deal_id(admin_api, headers)

    # Remove: flagged excluded, not deleted; the count drops and the public
    # register follows.
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/journals", headers=headers, json={"remove": ["0000-0000"]}
    )
    assert r.status_code == 200
    detail = r.json()
    assert detail["journal_count"] == 1
    assert [(j["excluded"]) for j in detail["journals"] if j["issn"] == "0000-0000"] == [True]
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/participations", headers=headers, json={"add": ["ut"]}
    )
    assert r.status_code == 200
    public = await admin_api.get("/api/v1/ut/deals")
    assert next(d for d in public.json() if d["id"] == deal_id)["journal_count"] == 1

    # Add: a variant ISSN resolves through issn_map, re-adding a removed
    # ISSN clears the excluded flag, and an ISSN that resolves to no
    # ISSN-L is rejected with 400 (it could never match a work).
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/journals",
        headers=headers,
        json={
            "add": [
                {"issn": "9999-8888", "journal_name": "J Zero"},
                {"issn": "0000-0000"},
            ],
            "remove": ["1111-1111"],
        },
    )
    assert r.status_code == 200
    rows = {j["issn"]: j for j in r.json()["journals"]}
    assert rows["9999-8888"]["issn_l"] == "0000-0000"
    assert rows["0000-0000"]["excluded"] is False
    assert rows["1111-1111"]["excluded"] is True
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/journals",
        headers=headers,
        json={"add": [{"issn": "8888-7777"}]},
    )
    assert r.status_code == 400
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/journals", headers=headers, json={"add": [{"issn": "nope"}]}
    )
    assert r.status_code == 400

    # A curated cap_text sticks through a JCT re-upsert of the same deal,
    # and a removed journal is not resurrected by it.
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}", headers=headers, json={"cap_text": "Curated cap"}
    )
    assert r.status_code == 200
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/journals", headers=headers, json={"remove": ["0000-0000"]}
    )
    assert r.status_code == 200
    async with async_sessionmaker(db_engine)() as session:
        await _store_agreement(
            session, EM_AGREEMENT, EM_JOURNALS, [], fetched_at="2026-10-26T00:00:00+00:00"
        )
        await session.commit()
        row = await session.scalar(
            select(DealJournal).where(
                DealJournal.deal_id == deal_id, DealJournal.issn == "0000-0000"
            )
        )
        assert row is not None and row.excluded is True
        deal = await session.get(Deal, deal_id)
        assert deal is not None
        assert deal.cap_text == "Curated cap"

    # Participations: sorted codes, unknown code 404.
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/participations",
        headers=headers,
        json={"add": ["rug", "ut"]},
    )
    assert r.status_code == 200 and r.json()["participations"] == ["rug", "ut"]
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/participations", headers=headers, json={"add": ["nope"]}
    )
    assert r.status_code == 404

    # Removing a participation records a tombstone the JCT harvester
    # respects; re-adding clears it.
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/participations", headers=headers, json={"remove": ["ut"]}
    )
    assert r.status_code == 200 and r.json()["participations"] == ["rug"]
    async with async_sessionmaker(db_engine)() as session:
        inst = await session.scalar(select(Institution).where(Institution.code == "ut"))
        assert inst is not None
        inst_id = inst.id  # commit below expires the instance; capture now
        tombstone_key = f"{deal_id}:{inst_id}"
        await _store_agreement(
            session,
            EM_TOMBSTONE_AGREEMENT,
            journals=[],
            institutions=EM_TOMBSTONE_INSTITUTIONS,
            fetched_at="2026-10-26T00:00:00+00:00",
        )
        await session.commit()
        assert (
            await session.scalar(
                select(DealInstitution).where(
                    DealInstitution.deal_id == deal_id,
                    DealInstitution.institution_id == inst_id,
                )
            )
            is None
        )
        assert (
            await session.scalar(
                select(ManualOverride).where(
                    ManualOverride.table_name == "deal_institutions",
                    ManualOverride.row_key == tombstone_key,
                )
            )
            is not None
        )

    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/participations", headers=headers, json={"add": ["ut"]}
    )
    assert r.status_code == 200 and r.json()["participations"] == ["rug", "ut"]
    async with async_sessionmaker(db_engine)() as session:
        assert (
            await session.scalar(
                select(ManualOverride).where(
                    ManualOverride.table_name == "deal_institutions",
                    ManualOverride.row_key == tombstone_key,
                )
            )
            is None
        )


# ── Funder UT-works counts (folded from test_correct_funder_metrics.py) ───


@pytest.fixture
async def funders_fixture(db, institution_factory):
    """Two linked funders (one with two OpenAlex twin ids) and works that
    exercise the gates: a retired work, a preprint, a pre-window work, and
    one live work crediting both twins of funder 1."""
    ut = await institution_factory(code="ut", data_window_start=2020)
    for issn in ("1234-5678", "2345-6789"):
        db.add(journal_factory(issn))
    db.add_all(
        [
            JiscFunder(
                id=1,
                name="Alpha Council",
                country="nl",
                publications_policy={
                    "publishing_policy": {"requirement": "requires"},
                    "archiving_policy": {"requirement": "requires"},
                },
                data_archiving_policy={"requirement": "encourages"},
            ),
            JiscFunder(
                id=2,
                name="Beta Fund",
                country="nl",
                publications_policy={
                    "publishing_policy": {"requirement": "encourages"},
                    "archiving_policy": {"requirement": "no_policy_for"},
                },
                data_archiving_policy=None,
            ),
        ]
    )
    await db.flush()
    db.add_all(
        [
            FunderLink(funder_id=1, source="openalex", source_id="F-A", via="ror"),
            FunderLink(funder_id=1, source="openalex", source_id="F-B", via="ror"),
            # One link stored before ids were normalised to bare.
            FunderLink(
                funder_id=2, source="openalex", source_id="https://openalex.org/F-C", via="ror"
            ),
        ]
    )
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()
    works = [
        # (pure_uuid, year, work_type, doi, issn, retired_at)
        ("w-live", 2023, "article", "10.0.0/1", "1234-5678", None),
        ("w-retired", 2023, "article", "10.0.0/2", "1234-5678", datetime.now(UTC)),
        ("w-preprint", 2023, "preprint", None, "1234-5678", None),
        ("w-old", 2019, "article", None, "1234-5678", None),
        ("w-beta1", 2023, "article", None, "2345-6789", None),
        ("w-beta2", 2023, "article", None, "2345-6789", None),
    ]
    db.add_all(
        Work(
            institution_id=ut.id,
            pure_uuid=u,
            title=u,
            norm_title=u,
            year=y,
            work_type=t,
            doi_normalized=doi,
            journal_issn_l=issn,
            retired_at=retired,
            first_seen_run=run.id,
            last_seen_run=run.id,
        )
        for (u, y, t, doi, issn, retired) in works
    )
    await db.flush()
    db.add_all(
        [
            WorkFunder(institution_id=ut.id, pure_uuid="w-live", funder_openalex_id="F-A"),
            WorkFunder(institution_id=ut.id, pure_uuid="w-live", funder_openalex_id="F-B"),
            WorkFunder(institution_id=ut.id, pure_uuid="w-retired", funder_openalex_id="F-A"),
            WorkFunder(institution_id=ut.id, pure_uuid="w-preprint", funder_openalex_id="F-A"),
            WorkFunder(institution_id=ut.id, pure_uuid="w-old", funder_openalex_id="F-A"),
            WorkFunder(institution_id=ut.id, pure_uuid="w-beta1", funder_openalex_id="F-C"),
            WorkFunder(institution_id=ut.id, pure_uuid="w-beta2", funder_openalex_id="F-C"),
        ]
    )
    await db.commit()
    return ut


@requires_db
async def test_funder_counts_gate_dedupe_and_sort(db, client, funders_fixture):
    per_bare = await funders_service.ut_work_counts(db, funders_fixture)
    # Gates drop the retired, excluded-type and out-of-window works; the
    # per-id counts stay per id (the display-twin pick uses them).
    assert per_bare == {"F-A": 1, "F-B": 1, "F-C": 2}
    union = await funders_service.ut_funder_work_counts(
        db, funders_fixture, {1: {"F-A", "F-B"}, 2: {"F-C"}}
    )
    # The twin-deduped union: funder 1's double-credited work counts once.
    assert union == {1: 1, 2: 2}

    items = (await client.get("/api/v1/ut/funders")).json()["items"]
    by_id = {i["id"]: i for i in items}
    assert by_id[1]["n_ut_works"] == 1 and by_id[2]["n_ut_works"] == 2
    # Re-sorted by the corrected counts (2 before 1), name breaks ties.
    assert [i["id"] for i in items[:2]] == [2, 1]

    body = (await client.get("/api/v1/ut/funders/1")).json()
    assert body["n_ut_works"] == 1
    # Only the live work's journal survives the gates.
    assert [(j["issn_l"], j["n_works"]) for j in body["top_journals"]] == [("1234-5678", 1)]
    assert len(body["works_by_year"]) == 1
    assert body["works_by_year"][0]["year"] == 2023
    assert body["works_by_year"][0]["works_count"] == 1

    # Facets, country/policy/works filtering, and sorting on /funders.
    root = (await client.get("/api/v1/ut/funders")).json()
    assert root["facets"]["country"] == {"NL": 2}
    assert root["facets"]["policy_structured"] == {"true": 2, "false": 0}
    assert root["facets"]["has_works"] == {"true": 2, "false": 0}
    assert root["facets"]["oa_publishing"] == {"requires": 1, "encourages": 1}
    assert root["facets"]["green_archiving"] == {"requires": 1, "no_policy_for": 1}
    assert root["facets"]["data_policy"] == {"encourages": 1, "none": 1}
    assert by_id[1]["oa_publishing_req"] == "requires"
    assert by_id[1]["green_archiving_req"] == "requires"
    assert by_id[1]["data_policy_req"] == "encourages"
    assert by_id[2]["data_policy_req"] is None

    by_name_desc = (await client.get("/api/v1/ut/funders?sort=name&dir=desc")).json()["items"]
    assert [i["id"] for i in by_name_desc[:2]] == [2, 1]
    by_name_asc = (await client.get("/api/v1/ut/funders?sort=name&dir=asc")).json()["items"]
    assert [i["id"] for i in by_name_asc[:2]] == [1, 2]

    only_nl = (await client.get("/api/v1/ut/funders?country=NL")).json()
    assert only_nl["total"] == 2
    only_gb = (await client.get("/api/v1/ut/funders?country=GB")).json()
    assert only_gb["total"] == 0
    only_struct = (await client.get("/api/v1/ut/funders?policy_structured=true")).json()
    assert only_struct["total"] == 2
    only_unstruct = (await client.get("/api/v1/ut/funders?policy_structured=false")).json()
    assert only_unstruct["total"] == 0
    only_works = (await client.get("/api/v1/ut/funders?has_works=true")).json()
    assert only_works["total"] == 2
    no_works = (await client.get("/api/v1/ut/funders?has_works=false")).json()
    assert no_works["total"] == 0
    only_oa_req = (await client.get("/api/v1/ut/funders?oa_publishing=requires")).json()
    assert [i["id"] for i in only_oa_req["items"]] == [1]
    only_green = (await client.get("/api/v1/ut/funders?green_archiving=no_policy_for")).json()
    assert [i["id"] for i in only_green["items"]] == [2]
    only_data = (await client.get("/api/v1/ut/funders?data_policy=encourages")).json()
    assert [i["id"] for i in only_data["items"]] == [1]


@requires_db
async def test_journals_filter_by_deal_id(db, client, deals_api):
    """?deal_id= restricts journal search to venues covered by that specific deal."""
    _, (twente_id, foreign_id, issn) = deals_api
    inst = (await db.execute(select(Institution).where(Institution.code == "ut"))).scalar_one()
    db.add(
        JournalFlags(institution_id=inst.id, issn_l=issn, deal_covered=True, works_window_plus=10)
    )
    db.add(
        # Active + Scimago-listed so the default eligibility toggles keep it
        # browsable; this test is about the deal_id cut, not the toggles.
        journal_factory("2222-2222", title="Other")
    )
    db.add(
        JournalFlags(
            institution_id=inst.id, issn_l="2222-2222", deal_covered=False, works_window_plus=10
        )
    )
    await db.commit()

    matching = (await client.get(f"/api/v1/ut/journals?deal_id={twente_id}")).json()
    assert [i["issn_l"] for i in matching["items"]] == [issn]
    foreign = (await client.get(f"/api/v1/ut/journals?deal_id={foreign_id}")).json()
    assert foreign["items"] == []


# ── Owner-curation provenance restore (scripts/restore_deal_curation.py) ───


def _load_restore_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "restore_deal_curation.py"
    spec = importlib.util.spec_from_file_location("restore_deal_curation", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_restore_curation_provenance_merge():
    mod = _load_restore_script()
    restored = mod.RESTORED_ENTRY
    jct_pair = [
        {"source": "jct", "url": "https://example.com/index", "fetched_at": "2026-11-19"},
        {"source": "jct", "url": "https://example.com/kar.csv", "fetched_at": "2026-11-19"},
    ]
    # Missing: the wiped pointer is appended behind the surviving entries.
    provenance, changed = mod.merge_curation_provenance(jct_pair, restored)
    assert changed and provenance == [*jct_pair, restored]
    # None stored: same outcome.
    provenance, changed = mod.merge_curation_provenance(None, restored)
    assert changed and provenance == [restored]
    # Already restored: idempotent, no duplicate.
    provenance, changed = mod.merge_curation_provenance([*jct_pair, restored], restored)
    assert not changed and provenance == [*jct_pair, restored]
    # A different (e.g. newer) owner_curation entry is never overwritten.
    newer = {"source": "owner_curation", "date": "2026-11-06", "doc": "decision-13.md"}
    provenance, changed = mod.merge_curation_provenance([*jct_pair, newer], restored)
    assert not changed and provenance == [*jct_pair, newer]
    # Other-source entries never block the restore (deal 48's openaccess.nl).
    provenance, changed = mod.merge_curation_provenance(
        [{"source": "openaccess.nl", "url": "https://x", "fetched_at": "2026-11-20"}],
        restored,
    )
    assert changed and provenance[-1] == restored
