"""Outcome tests for the ROR gap-fill (jobs/harvest_ror.py): the record
to row mapping and the fetch-and-mark loop, with the network faked."""

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update

from conftest import requires_db
from journal_browser.harvest import ror
from journal_browser.harvest.ror import TTL_DAYS, harvest_ror, ror_row
from journal_browser.models import PartnerInstitution


def test_ror_row_prefers_display_name_and_first_located_place():
    record = {
        "id": "https://ror.org/038v7xb98",
        "types": ["education", "funder"],
        "status": "active",
        "names": [
            {"types": ["alias"], "value": "Alias"},
            {"types": ["label", "ror_display"], "value": "Display"},
        ],
        "locations": [
            {"geonames_details": {"city": None, "country_code": "NL"}},
            {
                "geonames_details": {
                    "city": "Delft",
                    "name": "Delft",
                    "country_code": "NL",
                    "lat": 52.0,
                    "lng": 4.3,
                }
            },
        ],
        "relationships": [
            {"type": "Child", "label": "Kid", "id": "https://ror.org/02e2c7k09"},
            {"type": "parent", "label": "Parent Org", "id": "https://ror.org/006hf6230"},
        ],
    }

    row = ror_row(record, "038v7xb98")

    assert (row["name"], row["org_type"], row["status"]) == ("Display", "education", "active")
    assert (row["country_code"], row["city"], row["lat"], row["lng"]) == ("NL", "Delft", 52.0, 4.3)
    assert (row["parent_ror"], row["parent_name"]) == ("006hf6230", "Parent Org")
    assert row["payload"] is record


def test_ror_row_falls_back_to_acronym_and_place_name():
    record = {
        "names": [{"types": ["acronym"], "value": "TNO"}],
        "types": [],
        "locations": [{"geonames_details": {"name": "Leiden", "lat": 1, "lng": 2}}],
    }

    row = ror_row(record, "013aaaaaa")

    assert (row["name"], row["city"], row["org_type"], row["parent_ror"]) == (
        "TNO",
        "Leiden",
        None,
        None,
    )


def test_ror_row_groups_by_what_an_organisation_is_not_by_its_funder_role():
    # ROR lists a teaching hospital's funder role before healthcare.
    row = ror_row({"names": [], "types": ["funder", "healthcare"]}, "018906e22")

    assert row["org_type"] == "healthcare"


@requires_db
async def test_harvest_ror_fills_stubs_marks_missing_and_resumes(db, monkeypatch):
    db.add_all(
        [
            PartnerInstitution(ror="01x000001", name="Stub one", openalex_id="I1"),
            PartnerInstitution(ror="01x000002", name="Stub two", openalex_id="I2"),
            PartnerInstitution(ror="01x000003", name="Already in ROR", payload={"id": "r3"}),
        ]
    )
    await db.flush()
    records: dict[str, dict[str, Any]] = {
        "01x000001": {
            "id": "https://ror.org/01x000001",
            "names": [{"types": ["ror_display"], "value": "One"}],
            "types": ["education"],
            "status": "active",
            "locations": [{"geonames_details": {"city": "Oslo", "lat": 59.9, "lng": 10.7}}],
        }
    }
    fetched: list[list[str]] = []

    async def fake_paced_gets(get, ids, *, concurrency, min_interval_s):
        fetched.append(list(ids))
        return {iid: records.get(iid) for iid in ids}, {}

    monkeypatch.setattr(ror, "paced_single_gets", fake_paced_gets)

    stats = await harvest_ror(db)

    assert stats == {"selected": 2, "fetched": 1, "not_found": 1, "failed": 0}
    # Only the rows without a record are selected, in ROR id order.
    assert fetched == [["01x000001", "01x000002"]]
    db.expire_all()
    partners = {p.ror: p for p in (await db.execute(select(PartnerInstitution))).scalars().all()}
    one = partners["01x000001"]
    # ROR supplies the record; the stub's OpenAlex id stays.
    assert (one.name, one.city, one.org_type, one.status) == ("One", "Oslo", "education", "active")
    assert (one.openalex_id, one.payload["id"]) == ("I1", "https://ror.org/01x000001")
    two = partners["01x000002"]
    # An id ROR lacks is marked and keeps the stub's name.
    assert (two.status, two.payload, two.name) == ("not_found", None, "Stub two")

    # The next run asks for nothing. The missing id is asked again once its
    # mark is a month old, and a record is fetched again at the same age.
    stats = await harvest_ror(db)

    assert stats == {"selected": 0, "fetched": 0, "not_found": 0, "failed": 0}
    assert len(fetched) == 1
    stale = func.now() - timedelta(days=TTL_DAYS + 1)
    await db.execute(
        update(PartnerInstitution)
        .where(PartnerInstitution.ror == "01x000002")
        .values(updated_at=stale)
    )
    stats = await harvest_ror(db)

    assert stats == {"selected": 1, "fetched": 0, "not_found": 1, "failed": 0}
    assert fetched[-1] == ["01x000002"]
    # ROR registered the id in the meantime, and both rows are a month old.
    records["01x000002"] = {
        "id": "https://ror.org/01x000002",
        "names": [{"types": ["ror_display"], "value": "Two"}],
        "types": ["company"],
        "status": "active",
    }
    await db.execute(
        update(PartnerInstitution)
        .where(PartnerInstitution.ror.in_(["01x000001", "01x000002"]))
        .values(updated_at=stale)
    )
    stats = await harvest_ror(db)

    assert stats == {"selected": 2, "fetched": 2, "not_found": 0, "failed": 0}
    assert fetched[-1] == ["01x000001", "01x000002"]
