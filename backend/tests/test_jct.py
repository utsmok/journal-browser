"""Unit tests for the JCT dump parsers (fixtures inline, no network)."""

import httpx
from sqlalchemy import func, select

from conftest import requires_db
from journal_browser.harvest.common import parse_csv_rows
from journal_browser.harvest.jct import (
    INDEX_URL,
    _download_failure,
    _store_agreement,
    parse_agreement,
    parse_index,
    row_issn,
    split_esac_id,
)
from journal_browser.models import Deal, DealInstitution, DealJournal, Institution

INDEX_CSV = """ESAC ID,Relationship,End Date,C/A Only,Data URL,Last Reviewed
kar2026caul,,2026-12-31,yes,https://example.com/kar.csv,2026-01-15
acm2025eifl,Consortium,2025-06-30,,https://example.com/acm.csv,2025-01-10
broken-row,,2027-01-01,,,
"""

# journals x institutions cross product, plus one ISSN-less journal (duplicated
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


def test_split_esac_id():
    assert split_esac_id("kar2026caul") == ("kar", 2026, "caul")
    assert split_esac_id("acm2025eifl") == ("acm", 2025, "eifl")
    assert split_esac_id("iop2024") == ("iop", 2024, None)
    assert split_esac_id("nodigits") == ("nodigits", None, None)
    assert split_esac_id("2026caul") == (None, 2026, "caul")


def test_parse_index():
    agreements = parse_index(parse_csv_rows(INDEX_CSV.encode()))
    assert [a["esac_id"] for a in agreements] == ["kar2026caul", "acm2025eifl"]
    # duplicate ESAC rows in the sheet are kept once
    dupped = parse_index(
        parse_csv_rows(INDEX_CSV.replace("acm2025eifl,Consortium", "kar2026caul,Dup").encode())
    )
    assert [a["esac_id"] for a in dupped] == ["kar2026caul"]
    kar = agreements[0]
    assert kar["end_date"] == "2026-12-31"
    assert kar["ca_only"] == "yes"
    assert kar["data_url"] == "https://example.com/kar.csv"
    assert kar["last_reviewed"] == "2026-01-15"
    assert agreements[1]["ca_only"] == ""
    assert agreements[1]["raw"]["Relationship"] == "Consortium"


def test_parse_agreement_dedupe_issn_skip():
    journals, institutions, skipped = parse_agreement(parse_csv_rows(AGREEMENT_CSV.encode()))
    # 3 unique journals; the ISSN-less one is skipped and counted once
    assert len(journals) == 2
    assert skipped == 1
    names = {j["Journal Name"] for j in journals}
    assert names == {"Journal A", "Journal B"}
    # 2 unique institutions despite the cross product
    assert {i["ROR ID"] for i in institutions} == {
        "https://ror.org/006hf6230",
        "https://ror.org/042tr2w39",
    }


def test_row_issn_prefers_online():
    assert row_issn({"ISSN (Online)": "2049-3630", "ISSN (Print)": "0043-1397"}) == "2049-3630"
    # broken online falls back to print
    assert row_issn({"ISSN (Online)": "junk", "ISSN (Print)": "00431397"}) == "0043-1397"
    assert row_issn({"ISSN (Online)": "", "ISSN (Print)": ""}) is None


def test_download_failure_details():
    request = httpx.Request("GET", "https://example.com/kar.csv")
    response = httpx.Response(403, text="Forbidden: quota exceeded", request=request)
    exc = httpx.HTTPStatusError("403", request=request, response=response)
    assert _download_failure("kar2026caul", "https://example.com/kar.csv", exc) == {
        "esac_id": "kar2026caul",
        "url": "https://example.com/kar.csv",
        "status": 403,
        "body_snippet": "Forbidden: quota exceeded",
    }


def test_download_failure_transport_error_has_no_status():
    failure = _download_failure("x2026", "https://example.com/x.csv", httpx.ConnectError("boom"))
    assert failure["status"] is None
    assert "boom" in failure["body_snippet"]


@requires_db
async def test_store_agreement_models_the_deal(db):
    agreement = parse_index(parse_csv_rows(INDEX_CSV.encode()))[0]
    journals, institutions, _ = parse_agreement(parse_csv_rows(AGREEMENT_CSV.encode()))
    await _store_agreement(db, agreement, journals, institutions, "2026-10-22T00:00:00+00:00")
    await db.commit()

    deal = await db.scalar(select(Deal).where(Deal.esac_id == "kar2026caul"))
    assert deal.start_year == 2026
    assert deal.end_year == 2026
    assert deal.consortium == "caul"
    assert deal.corresponding_authors_only is True
    assert deal.status == "current"
    assert deal.jct_data_url == "https://example.com/kar.csv"
    assert str(deal.last_reviewed) == "2026-01-15"
    assert deal.provenance == [
        {"source": "jct", "url": INDEX_URL, "fetched_at": "2026-10-22T00:00:00+00:00"},
        {"source": "jct", "url": agreement["data_url"], "fetched_at": "2026-10-22T00:00:00+00:00"},
    ]
    assert deal.publisher_id is not None

    journal_rows = (
        await db.scalars(
            select(DealJournal).where(DealJournal.deal_id == deal.id).order_by(DealJournal.issn)
        )
    ).all()
    # A: online ISSN preferred; B: print fallback (online empty)
    assert [(j.issn, j.journal_name, j.source) for j in journal_rows] == [
        ("1234-567X", "Journal B", "jct"),
        ("2049-3630", "Journal A", "jct"),
    ]
    assert {j.first_seen for j in journal_rows} == {"2024-01-01", "2025-02-01"}

    inst_rows = (
        await db.scalars(select(Institution).where(Institution.ror == "https://ror.org/006hf6230"))
    ).all()
    assert len(inst_rows) == 1
    assert inst_rows[0].name == "University of Twente"
    assert inst_rows[0].is_home is False
    links = (
        await db.scalars(select(DealInstitution).where(DealInstitution.deal_id == deal.id))
    ).all()
    assert len(links) == 2
    assert {lnk.first_seen for lnk in links} == {"2024-01-01"}


@requires_db
async def test_store_agreement_is_idempotent(db):
    agreement = parse_index(parse_csv_rows(INDEX_CSV.encode()))[0]
    journals, institutions, _ = parse_agreement(parse_csv_rows(AGREEMENT_CSV.encode()))
    await _store_agreement(db, agreement, journals, institutions, "2026-10-22T00:00:00+00:00")
    await db.commit()
    await _store_agreement(db, agreement, journals, institutions, "2026-10-22T00:00:00+00:00")
    await db.commit()

    assert await db.scalar(select(func.count()).select_from(Deal)) == 1
    assert await db.scalar(select(func.count()).select_from(DealJournal)) == 2
    assert await db.scalar(select(func.count()).select_from(Institution)) == 2
    assert await db.scalar(select(func.count()).select_from(DealInstitution)) == 2


@requires_db
async def test_institution_name_collision_gets_ror_suffix(db):
    # a different ROR already owns the display name 'MIT'; Twente's ROR row is
    # already reconciled under a different name
    db.add(Institution(name="MIT", ror="https://ror.org/00000000"))
    db.add(Institution(name="Twente (reconciled)", ror="https://ror.org/006hf6230"))
    await db.flush()
    agreement = parse_index(parse_csv_rows(INDEX_CSV.encode()))[0]
    journals, institutions, _ = parse_agreement(parse_csv_rows(AGREEMENT_CSV.encode()))
    await _store_agreement(db, agreement, journals, institutions, "2026-10-22T00:00:00+00:00")
    await db.commit()

    rows = {
        r.ror: r.name
        for r in (await db.scalars(select(Institution).where(Institution.name.like("MIT%")))).all()
    }
    assert rows["https://ror.org/00000000"] == "MIT"
    # the JCT 'MIT' keeps its verbatim name plus a ROR discriminator
    assert rows["https://ror.org/042tr2w39"] == "MIT [042tr2w39]"
    # existing row by ROR is left untouched (reconciled name survives)
    twente = await db.scalar(
        select(Institution).where(Institution.ror == "https://ror.org/006hf6230")
    )
    assert twente.name == "Twente (reconciled)"
