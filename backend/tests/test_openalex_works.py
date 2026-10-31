"""openalex_works projection: latest payload wins per W-id, excluded work
types, author-sweep provenance (via HarvestState.filter_set), venue map,
and the journal works-tab local rows."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from conftest import journal_factory, requires_db
from journal_browser.harvest.openalex_works import rebuild_openalex_works, work_row
from journal_browser.models import (
    HarvestRun,
    HarvestState,
    OpenalexWork,
    SourceRecord,
)


def _payload(
    w_id: str = "W1",
    *,
    type_: str = "article",
    doi: str | None = "10.1234/abc",
    title: str = "Work One",
    year: int | None = 2023,
    oa: str | None = "gold",
    source_id: str | None = "S123",
    source_name: str | None = "Journal One",
    authorships: list[dict] | None = None,
    cited: int = 5,
    fwci: float | None = 1.2,
    retracted: bool = False,
) -> dict:
    authorships = (
        authorships
        if authorships is not None
        else [
            {
                "author": {
                    "id": f"https://openalex.org/{a}",
                    "display_name": f"Author {a}",
                    "orcid": f"https://orcid.org/0000-0002-1825-009{x}" if orc else None,
                }
            }
            for a, x, orc in (("A1", "7", True), ("A2", "8", False))
        ]
    )
    primary = {"source": {"id": f"https://openalex.org/{source_id}", "display_name": source_name}}
    if source_id is None:
        primary = {"source": None}
    return {
        "id": f"https://openalex.org/{w_id}",
        "doi": doi and f"https://doi.org/{doi}",
        "display_name": title,
        "publication_year": year,
        "type": type_,
        "open_access": {"oa_status": oa},
        "primary_location": primary,
        "authorships": authorships,
        "cited_by_count": cited,
        "fwci": fwci,
        "is_retracted": retracted,
    }


def test_work_row_shape():
    row = work_row(_payload(), {"S123": "1234-5678"})
    assert row["w_id"] == "W1"
    assert row["doi_normalized"] == "10.1234/abc"
    assert row["venue_issn_l"] == "1234-5678"
    assert row["venue_name"] == "Journal One"
    assert row["oa_status"] == "gold"
    assert row["source"] == "works_stats"
    # compact authorships: bare ids, lower-cased bare orcids, name kept
    assert row["authorships"] == [
        {"a": "A1", "n": "Author A1", "o": "0000-0002-1825-0097"},
        {"a": "A2", "n": "Author A2", "o": None},
    ]


def test_work_row_gates():
    # no usable W-id
    assert work_row(_payload(w_id=""), {"S123": "1234-5678"}) is None
    # excluded work type (preprint/book never enter journal views)
    assert work_row(_payload(type_="preprint"), {"S123": "x"}) is None
    # unmapped venue keeps the name, loses the issn; unknown oa folds to closed
    row = work_row(_payload(oa="archive"), {})
    assert row["venue_issn_l"] is None and row["venue_name"] == "Journal One"
    assert row["oa_status"] == "closed"


async def _seed_sweep(
    db, inst, records: list[tuple[str, dict]], *, filter_set: str, run: HarvestRun | None = None
) -> HarvestRun:
    """One completed openalex/works_stats run + state + stored payloads."""
    if run is None:
        run = HarvestRun(
            source="openalex",
            entity_type="works_stats",
            institution_id=inst.id,
            status="completed",
            config_fingerprint="t",
        )
    if run.id is None:
        db.add(run)
        await db.flush()
    db.add(
        HarvestState(
            source="openalex",
            entity_type="works_stats",
            filter_set=filter_set,
            institution_id=inst.id,
            last_run_id=run.id,
        )
    )
    base = datetime.now(UTC) - timedelta(hours=24)
    for i, (pk, payload) in enumerate(records):
        year = payload.get("publication_year")
        db.add(
            SourceRecord(
                source="openalex",
                entity_type="works_stats",
                source_pk=pk,
                payload=payload,
                publication_year=year if isinstance(year, int) else None,
                content_hash=f"h-{pk}-{i}-{filter_set}",
                harvested_at=base + timedelta(minutes=i),
                harvest_run_id=run.id,
            )
        )
    await db.flush()
    return run


@requires_db
async def test_rebuild_latest_wins_and_sweep_marking(db, institution_factory):
    inst = await institution_factory(code="ut")
    db.add(journal_factory("1234-5678", openalex_id="S123"))
    await db.flush()
    # W1 twice (older first), W2 from the author sweep, W3 a preprint.
    old = _payload(title="Old Title")
    new = _payload(title="New Title", cited=9)
    await _seed_sweep(db, inst, [("W1", old), ("W1", new)], filter_set="institutions.id=I1")
    sweep_run = HarvestRun(
        source="openalex",
        entity_type="works_stats",
        institution_id=inst.id,
        status="completed",
        config_fingerprint="s",
    )
    await _seed_sweep(
        db, inst, [("W2", _payload(w_id="W2"))], filter_set="author-sweep:0", run=sweep_run
    )
    pre_run = HarvestRun(
        source="openalex",
        entity_type="works_stats",
        institution_id=inst.id,
        status="completed",
        config_fingerprint="p",
    )
    await _seed_sweep(
        db,
        inst,
        [("W3", _payload(w_id="W3", type_="preprint"))],
        filter_set="author-sweep:1",
        run=pre_run,
    )

    stats = await rebuild_openalex_works(db, inst)
    assert stats["works"] == 2  # W1 + W2; the preprint never lands
    assert stats["excluded_types"] == 1
    assert stats["parse_failures"] == 0
    assert stats["author_sweep_rows"] == 1
    rows = {r.w_id: r for r in (await db.execute(select(OpenalexWork))).scalars()}
    assert rows["W1"].title == "New Title"  # latest payload wins
    assert rows["W1"].cited_by_count == 9
    assert rows["W1"].source == "works_stats"
    assert rows["W2"].source == "author-sweep"
    assert rows["W1"].venue_issn_l == "1234-5678"

    # Re-run folds into the same rows (deterministic full-replace).
    stats2 = await rebuild_openalex_works(db, inst)
    assert stats2["works"] == 2
    assert len((await db.execute(select(OpenalexWork))).scalars().all()) == 2


@requires_db
async def test_rebuild_scoped_to_institution(db, institution_factory):
    ut = await institution_factory(code="ut")
    rug = await institution_factory(code="rug")
    await _seed_sweep(db, ut, [("W1", _payload())], filter_set="institutions.id=UT")
    stats = await rebuild_openalex_works(db, rug)
    assert stats["works"] == 0
    rows = (await db.execute(select(OpenalexWork))).scalars().all()
    assert rows == []
