"""The FWCI/retracted tiles ride the canonical UT works population
(decision 22); the OpenAlex-venue numbers stay as separately named
cross-check fields."""

import pytest

from conftest import journal_factory, requires_db
from journal_browser.models import HarvestRun, OpenalexWork, Work
from journal_browser.services.detail_enrichment import institution_metrics


@pytest.fixture
async def metrics_fixture(db, institution_factory):
    """One journal with two canonical works: one store-matched (fwci 2.0,
    retracted) plus one without a store row, and a third store row that
    only the venue side sees (a mixed-population author-sweep row)."""
    ut = await institution_factory(code="ut", data_window_start=2020)
    db.add(journal_factory("1234-5678"))
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()
    db.add_all(
        [
            Work(
                institution_id=ut.id,
                pure_uuid="w-a",
                title="w-a",
                norm_title="w-a",
                year=2023,
                doi_normalized="10.0.0/a",
                journal_issn_l="1234-5678",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            Work(
                institution_id=ut.id,
                pure_uuid="w-b",
                title="w-b",
                norm_title="w-b",
                year=2022,
                journal_issn_l="1234-5678",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            # Venue-side only: not a works-table row (author sweep row of
            # the same venue).
            OpenalexWork(
                institution_id=ut.id,
                w_id="W-sweep",
                title="sweep-only",
                year=2023,
                fwci=0.5,
                authorships=[],
                venue_issn_l="1234-5678",
                venue_name="Journal 1234-5678",
                source="author-sweep:1",
            ),
        ]
    )
    db.add(
        OpenalexWork(
            institution_id=ut.id,
            w_id="W-a",
            title="w-a",
            year=2023,
            doi_normalized="10.0.0/a",
            fwci=2.0,
            is_retracted=True,
            cited_by_count=4,
            authorships=[],
            venue_issn_l="1234-5678",
            venue_name="Journal 1234-5678",
            source="works_stats",
        )
    )
    await db.commit()
    return ut


@requires_db
async def test_tiles_canonical_venue_cross_check(db, metrics_fixture):
    m = await institution_metrics(db, "1234-5678", metrics_fixture)
    # Canonical tiles: one store-matched work with fwci 2.0, retracted.
    assert m["canonical_total"] == 2
    assert m["fwci_n"] == 1 and m["fwci_avg"] == 2.0
    assert m["retracted"] == 1 == m["canonical_retracted"]
    # Venue cross-check keeps its own numbers (2 venue rows, fwci 0.5+2.0).
    assert m["openalex_matched"] == 2
    assert m["venue_fwci_n"] == 2
    assert m["venue_fwci_avg"] == pytest.approx(1.25)
    assert m["venue_retracted"] == 1
    assert m["cited_total"] == 4
