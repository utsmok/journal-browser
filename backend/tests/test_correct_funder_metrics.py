"""Funder UT-works counts must join works with the shared gates (not
retired, journal-output types, data window) and dedupe pure_uuid across a
funder's twin-id set; the list sorts by the corrected count."""

from datetime import UTC, datetime

import pytest

from conftest import journal_factory, requires_db
from journal_browser.models import (
    FunderLink,
    HarvestRun,
    JiscFunder,
    Work,
    WorkFunder,
)
from journal_browser.services import funders as funders_service


@pytest.fixture
async def funders_fixture(db, institution_factory):
    ut = await institution_factory(code="ut", data_window_start=2020)
    for issn in ("1234-5678", "2345-6789"):
        db.add(journal_factory(issn))
    db.add_all(
        [
            JiscFunder(id=1, name="Alpha Council", country="nl"),
            JiscFunder(id=2, name="Beta Fund", country="nl"),
        ]
    )
    await db.flush()
    db.add_all(
        [
            FunderLink(
                funder_id=1, source="openalex", source_id="https://openalex.org/F-A", via="ror"
            ),
            FunderLink(
                funder_id=1, source="openalex", source_id="https://openalex.org/F-B", via="ror"
            ),
            FunderLink(
                funder_id=2, source="openalex", source_id="https://openalex.org/F-C", via="ror"
            ),
        ]
    )
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()
    retired_at = datetime.now(UTC)
    db.add_all(
        [
            Work(
                institution_id=ut.id,
                pure_uuid="w-live",
                title="w-live",
                norm_title="w-live",
                year=2023,
                work_type="article",
                doi_normalized="10.0.0/1",
                journal_issn_l="1234-5678",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            Work(
                institution_id=ut.id,
                pure_uuid="w-retired",
                title="w-retired",
                norm_title="w-retired",
                year=2023,
                work_type="article",
                doi_normalized="10.0.0/2",
                journal_issn_l="1234-5678",
                retired_at=retired_at,
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            Work(
                institution_id=ut.id,
                pure_uuid="w-preprint",
                title="w-preprint",
                norm_title="w-preprint",
                year=2023,
                work_type="preprint",
                journal_issn_l="1234-5678",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            Work(
                institution_id=ut.id,
                pure_uuid="w-old",
                title="w-old",
                norm_title="w-old",
                year=2019,
                work_type="article",
                journal_issn_l="1234-5678",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            Work(
                institution_id=ut.id,
                pure_uuid="w-beta1",
                title="w-beta1",
                norm_title="w-beta1",
                year=2023,
                work_type="article",
                journal_issn_l="2345-6789",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            Work(
                institution_id=ut.id,
                pure_uuid="w-beta2",
                title="w-beta2",
                norm_title="w-beta2",
                year=2023,
                work_type="article",
                journal_issn_l="2345-6789",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
        ]
    )
    await db.flush()
    db.add_all(
        [
            # One work crediting both twins of funder 1: must count once.
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
async def test_service_counts_gate_and_dedupe(db, funders_fixture):
    per_bare = await funders_service.ut_work_counts(db, funders_fixture)
    # Gates drop the retired, excluded-type and out-of-window works; the
    # per-id counts stay per id (the display-twin pick uses them).
    assert per_bare == {"F-A": 1, "F-B": 1, "F-C": 2}
    union = await funders_service.ut_funder_work_counts(
        db, funders_fixture, {1: {"F-A", "F-B"}, 2: {"F-C"}}
    )
    # The twin-deduped union: funder 1's double-credited work counts once.
    assert union == {1: 1, 2: 2}


@requires_db
async def test_list_sorts_by_corrected_count(client, funders_fixture):
    r = await client.get("/api/v1/ut/funders")
    assert r.status_code == 200
    items = r.json()["items"]
    by_id = {i["id"]: i for i in items}
    assert by_id[1]["n_ut_works"] == 1
    assert by_id[2]["n_ut_works"] == 2
    # Re-sorted by the corrected counts (2 before 1), name breaks ties.
    assert [i["id"] for i in items[:2]] == [2, 1]


@requires_db
async def test_detail_top_journals_respect_gates(client, funders_fixture):
    r = await client.get("/api/v1/ut/funders/1")
    assert r.status_code == 200
    body = r.json()
    assert body["n_ut_works"] == 1
    # Only the live work's journal survives the gates.
    assert [(j["issn_l"], j["n_works"]) for j in body["top_journals"]] == [("1234-5678", 1)]
