"""Unit tests for conservative partner roll-up and searchable alias extraction."""

from journal_browser.harvest.partner_rollup import build_search_fields, compute_rollup_map


def test_build_search_fields_extracts_ror_names_acronyms_city_and_curated_extras():
    text, acronyms = build_search_fields(
        ror="02e2c7k09",
        name="Delft University of Technology",
        city="Delft",
        payload={
            "names": [
                {"value": "Delft University of Technology", "types": ["ror_display"]},
                {"value": "TU Delft", "types": ["alias"]},
                {"value": "Technische Universiteit Delft", "types": ["label"]},
            ]
        },
    )
    assert "tu delft" in text
    assert "technische universiteit delft" in text
    assert "delft" in text
    assert "tu delft" in acronyms
    assert "tud" in acronyms


def test_compute_rollup_map_merges_subunits_and_successors_but_keeps_distinct_unis_separate():
    records = [
        # Amsterdam UMC + two same-city hospital site children -> roll up
        {
            "ror": "05grdyy37",
            "name": "Amsterdam UMC",
            "org_type": "healthcare",
            "country_code": "NL",
            "city": "Amsterdam",
            "parent_ror": None,
            "status": "active",
            "payload": {},
        },
        {
            "ror": "03t4gr691",
            "name": "Amsterdam UMC Location University of Amsterdam",
            "org_type": "healthcare",
            "country_code": "NL",
            "city": "Amsterdam",
            "parent_ror": "05grdyy37",
            "status": "active",
            "payload": {},
        },
        # Facility embedded at same-city university -> roll up
        {
            "ror": "016xsfp80",
            "name": "Radboud University Nijmegen",
            "org_type": "education",
            "country_code": "NL",
            "city": "Nijmegen",
            "parent_ror": None,
            "status": "active",
            "payload": {},
        },
        {
            "ror": "053sba816",
            "name": "Donders Institute for Brain, Cognition and Behaviour",
            "org_type": "facility",
            "country_code": "NL",
            "city": "Nijmegen",
            "parent_ror": "016xsfp80",
            "status": "active",
            "payload": {},
        },
        # Federated university system: UCL & QMUL stay separate from University of London!
        {
            "ror": "04cw6st05",
            "name": "University of London",
            "org_type": "education",
            "country_code": "GB",
            "city": "London",
            "parent_ror": None,
            "status": "active",
            "payload": {},
        },
        {
            "ror": "02jx3x895",
            "name": "University College London",
            "org_type": "education",
            "country_code": "GB",
            "city": "London",
            "parent_ror": "04cw6st05",
            "status": "active",
            "payload": {},
        },
        {
            "ror": "026zzn846",
            "name": "Queen Mary University of London",
            "org_type": "education",
            "country_code": "GB",
            "city": "London",
            "parent_ror": "04cw6st05",
            "status": "active",
            "payload": {},
        },
        # Multi-institute society (Max Planck): distinct institutes stay separate!
        {
            "ror": "01hhn8329",
            "name": "Max Planck Society",
            "org_type": "nonprofit",
            "country_code": "DE",
            "city": "Munich",
            "parent_ror": None,
            "status": "active",
            "payload": {},
        },
        {
            "ror": "0087djs12",
            "name": "Max Planck Institute for Dynamics and Self-Organization",
            "org_type": "facility",
            "country_code": "DE",
            "city": "Göttingen",
            "parent_ror": "01hhn8329",
            "status": "active",
            "payload": {},
        },
        # Inactive ROR with single active successor -> roll up
        {
            "ror": "033003e23",
            "name": "Tampere University",
            "org_type": "education",
            "country_code": "FI",
            "city": "Tampere",
            "parent_ror": None,
            "status": "active",
            "payload": {},
        },
        {
            "ror": "05p6qqk79",
            "name": "University of Tampere",
            "org_type": "education",
            "country_code": "FI",
            "city": "Tampere",
            "parent_ror": None,
            "status": "inactive",
            "payload": {
                "relationships": [
                    {"type": "successor", "id": "https://ror.org/033003e23", "label": "Tampere"}
                ]
            },
        },
    ]

    rollups = compute_rollup_map(records)

    assert rollups["03t4gr691"] == "05grdyy37"
    assert rollups["053sba816"] == "016xsfp80"
    assert rollups["05p6qqk79"] == "033003e23"
    # Distinct universities and society institutes stay separate
    assert rollups["02jx3x895"] is None
    assert rollups["026zzn846"] is None
    assert rollups["0087djs12"] is None
