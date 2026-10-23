"""Unit tests for the OpenAPC harvest: aggregates + evidence from fixture CSV strings."""

from journal_browser.harvest.common import parse_csv_rows
from journal_browser.harvest.openapc import build_aggregates, build_evidence

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
        # Twente, no ISSN at all and no group_id/doi -> source_pk falls back to row index
        "University of Twente,2021,500,NA,FALSE,FALSE,Elsevier,Journal Y,NA,NA,NA,NA,"
        "http://cc/by,FALSE,NA,NA,NA,NA,FALSE,NA,NA",
        # Other institution: aggregates only, never evidence
        "TU Delft,2020,999,10.1/nl1,TRUE,FALSE,Elsevier,Journal Z,9999-9994,NA,9999-9994,"
        "9999-9994,http://cc/by,TRUE,NA,NA,NA,NA,FALSE,NA,g3",
        # No ISSN at all: aggregate-unresolved
        "No Issn Uni,2019,100,10.1/x1,TRUE,FALSE,MDPI,Journal W,NA,NA,NA,NA,http://cc/by,"
        "TRUE,NA,NA,NA,NA,FALSE,NA,NA",
    ]
)

CONTRACTS_MAP = {"g2": "Wiley CA"}

# Strict: only this mapping exists; everything else resolves to None.
# (Fixture ISSNs must pass the mod-11 checksum gate in build_aggregates.)
ISSN_MAP = {"1111-1119": "3333-3335"}


async def resolve(issn: str | None) -> str | None:
    return ISSN_MAP.get(issn or "")


def _rows() -> list[dict[str, str]]:
    return parse_csv_rows(TA_CSV.encode())


async def test_build_aggregates_min_max_mean_and_issn_resolution():
    aggregates, counters = await build_aggregates(_rows(), resolve)

    by_key = {(a["issn_l"], a["period"]): a for a in aggregates}
    assert set(by_key) == {("1432-7643", 2020), ("3333-3335", 2020), ("9999-9994", 2020)}

    agg = by_key[("1432-7643", 2020)]
    assert agg["article_count"] == 2
    assert (agg["euro_min"], agg["euro_max"], agg["euro_mean"]) == (1000.0, 2000.0, 1500.0)

    # euro NA still counts as an article, but no euro stats
    agg = by_key[("3333-3335", 2020)]
    assert agg["article_count"] == 1
    assert (agg["euro_min"], agg["euro_max"], agg["euro_mean"]) == (None, None, None)

    assert counters["rows"] == 6
    assert counters["unresolved_issn"] == 2  # Twente row 4 + No Issn Uni
    assert counters["skipped"] == 0


async def test_build_evidence_institution_filter_and_contracts_fill():
    items, filled = await build_evidence(_rows(), "University of Twente", resolve, CONTRACTS_MAP)

    assert len(items) == 4  # TU Delft + No Issn Uni excluded; case-insensitive match
    assert filled == 1

    by_pk = {i["source_pk"] or f"idx{i['fields']['doi']}": i for i in items}
    tw1 = by_pk["g1|10.1/tw1"]
    assert tw1["fields"] == {
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

    # No ISSN and no group_id/doi -> issn_l NULL; source_pk stays None here
    # (the row-index fallback "3" is assigned in _body).
    fallback = items[3]
    assert fallback["source_pk"] is None
    assert fallback["fields"]["issn_l"] is None
    assert fallback["payload"] == _rows()[3]  # verbatim row payload
