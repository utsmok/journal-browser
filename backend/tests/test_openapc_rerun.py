"""Regression: a second OpenAPC run must keep apc_evidence -> source_records
provenance links even when every TA row is an unchanged duplicate."""

from sqlalchemy import func, select

from conftest import requires_db
from journal_browser.config import get_settings
from journal_browser.harvest.common import store_raw_file
from journal_browser.harvest.openapc import _body
from journal_browser.ingest import IngestSession
from journal_browser.models import ApcEvidence

APC_CSV = "\n".join(
    [
        "institution,period,euro,doi,issn,issn_l",
        "TU Delft,2021,900,10.1/ag1,1432-7643,1432-7643",
    ]
)

TA_HEADER = (
    "institution,period,euro,doi,is_hybrid,opt_out,publisher,journal_full_title,issn,"
    "issn_print,issn_electronic,issn_l,license_ref,indexed_in_crossref,pmid,pmcid,ut,url,"
    "doaj,agreement,group_id"
)
TA_CSV = "\n".join(
    [
        TA_HEADER,
        "University of Twente,2020,1000,10.1/tw1,TRUE,FALSE,Springer Nature,Soft Computing,"
        "1432-7643,1432-7643,1433-7479,1432-7643,http://cc/by,TRUE,NA,NA,NA,NA,TRUE,NA,g1",
    ]
)

CONTRACTS_CSV = "\n".join(["group_id,contract_name", "g1,Springer Compact"])

BODIES = {
    "apc": APC_CSV.encode(),
    "ta": TA_CSV.encode(),
    "contracts": CONTRACTS_CSV.encode(),
    "additional_costs": b"",
    "bpc": b"",
}


async def _fake_download(session, ingest, source, entity_type, url, suffix, source_pk="", **kw):
    data = BODIES[entity_type]
    await store_raw_file(session, source, entity_type, url, data, suffix, source_pk=source_pk)
    return data, True


@requires_db
async def test_rerun_keeps_evidence_source_record_link(db, monkeypatch, tmp_path):
    monkeypatch.setenv("JB_LANDING_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("journal_browser.harvest.openapc.download_to_landing", _fake_download)
    try:
        for _ in range(2):  # second run: identical files -> duplicate source_records
            ingest = IngestSession(db)
            await ingest.start_run("openapc", "apc_row", "all", {})
            await _body(ingest, None)
        await db.commit()
        total, nulls = (
            await db.execute(
                select(
                    func.count(),
                    func.count(ApcEvidence.source_record_id),
                )
            )
        ).one()
        assert total > 0
        assert nulls == total, f"{nulls}/{total} evidence rows lost their source_records link"
    finally:
        get_settings.cache_clear()
