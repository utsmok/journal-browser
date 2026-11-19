"""The author gap card and the missed-works CSV must quote one population
(author_gap_works): headline total = gated rows, likely_missing = the
subset tag_pure_matches cannot explain with a Pure record, and the CSV
lists exactly the missing rows — never the wider raw not_in_pure set."""

import csv
import io

import pytest

from conftest import requires_db
from journal_browser.models import (
    Author,
    AuthorWork,
    HarvestRun,
    Work,
    WorkPureAuthor,
)
from journal_browser.services.authors import author_gap_works


def _store_row(w_id, title, year, doi, work_type="article", issn_l=None):
    return {
        "title": title,
        "year": year,
        "doi": doi,
        "oa_status": "gold",
        "work_type": work_type,
        "venue_name": "Venue",
        "issn_l": issn_l,
        "openalex_id": w_id,
        "authorships": None,
        "parent_works": [],
        "is_part": False,
    }


@pytest.fixture
async def gap_fixture(db, institution_factory):
    """ut with alice holding one DOI-carrying Pure work and two further
    Pure records (a DOI-only record, a same-title record) that the store
    rows must be tagged against."""
    ut = await institution_factory(code="ut", data_window_start=2020)
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()
    db.add_all(
        [
            Work(
                institution_id=ut.id,
                pure_uuid="w-own",
                title="Own Work",
                norm_title="own work",
                year=2023,
                doi_normalized="10.0.0/own",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            Work(
                institution_id=ut.id,
                pure_uuid="w-unlinked",
                title="Unlinked Record",
                norm_title="unlinked record",
                year=2022,
                doi_normalized="10.0.0/unlinked",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            Work(
                institution_id=ut.id,
                pure_uuid="w-sametitle",
                title="Shared Title Study",
                norm_title="shared title study",
                year=2021,
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
        ]
    )
    db.add(
        Author(
            institution_id=ut.id,
            pure_uuid="alice-uuid",
            name="Alice Author",
            openalex_ids=["a-alice"],
            n_works=1,
            confirmed=True,
        )
    )
    await db.flush()
    db.add(AuthorWork(institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid="w-own"))
    # The same-title Pure record shares the author: tagging needs the edge.
    db.add(
        WorkPureAuthor(institution_id=ut.id, work_pure_uuid="w-sametitle", person_uuid="alice-uuid")
    )
    await db.commit()
    return ut


async def _with_store_rows(db, gap_fixture, rows, monkeypatch):
    async def _fake(_session, _institution, _author):
        return rows

    monkeypatch.setattr("journal_browser.services.authors.openalex_only_works_for_author", _fake)
    from sqlalchemy import select

    author = (
        await db.execute(
            select(Author).where(
                Author.institution_id == gap_fixture.id, Author.pure_uuid == "alice-uuid"
            )
        )
    ).scalar_one()
    return await author_gap_works(db, gap_fixture, author)


@requires_db
async def test_gap_counts_share_one_definition(db, gap_fixture, monkeypatch):
    gated, missing = await _with_store_rows(
        db,
        gap_fixture,
        [
            # Own Pure work's DOI: skips entirely (not in gated).
            _store_row("W-OWN", "Dup Of Own", 2024, "https://doi.org/10.0.0/OWN"),
            # A Pure record outside the author's list: tagged, kept in gated.
            _store_row("W-TAG-DOI", "Unlinked Twin", 2023, "10.0.0/unlinked"),
            # Same normalized title sharing the author: tagged.
            _store_row("W-TAG-TITLE", "Shared Title Study", 2021, None),
            # The one real miss.
            _store_row("W-GAP", "Real Gap Work", 2023, "10.9.9/gap"),
            # Gates: out-of-window year and excluded type drop out.
            _store_row("W-OLD", "Old", 2019, "10.9.9/old"),
            _store_row("W-PRE", "Pre", 2023, "10.9.9/pre", work_type="preprint"),
        ],
        monkeypatch,
    )
    assert [g["openalex_id"] for g in gated] == ["W-GAP", "W-TAG-DOI", "W-TAG-TITLE"]
    assert [g["openalex_id"] for g in missing] == ["W-GAP"]


@requires_db
async def test_profile_and_missed_csv_agree(client, db, gap_fixture, monkeypatch):
    rows = [
        _store_row("W-TAG-DOI", "Unlinked Twin", 2023, "10.0.0/unlinked"),
        _store_row("W-TAG-TITLE", "Shared Title Study", 2021, None),
        _store_row("W-GAP", "Real Gap Work", 2023, "10.9.9/gap", issn_l="1234-5678"),
    ]

    async def _fake(_session, _institution, _author):
        return rows

    monkeypatch.setattr("journal_browser.services.authors.openalex_only_works_for_author", _fake)
    r = await client.get("/api/v1/ut/authors/alice-uuid")
    assert r.status_code == 200
    section = r.json()["openalex_only"]
    assert section["available"] is True
    assert section["total"] == 3
    assert section["likely_missing"] == 1

    csv_r = await client.get("/api/v1/ut/authors/alice-uuid/works.csv", params={"scope": "missed"})
    assert csv_r.status_code == 200
    rows_out = list(csv.DictReader(io.StringIO(csv_r.text)))
    # The CSV lists exactly the likely-missing rows — not the tagged ones,
    # not the pre-refinement anti-join set.
    assert [row["title"] for row in rows_out] == ["Real Gap Work"]
    assert rows_out[0]["openalex_id"] == "W-GAP"
    assert rows_out[0]["in_pure"] == "false"
