"""venue_authorship single-pass rewrite: the four aggregates (works total,
faculty buckets, research-group buckets, top authors) come from one
UNION ALL over one materialized pairs CTE. Pins values, ordering and the
missing-attribute rule (rows without faculty/group stay in the total but
form no bucket)."""

import pytest

from conftest import journal_factory, requires_db
from journal_browser.models import Author, HarvestRun, Work, WorkPureAuthor
from journal_browser.services.authorship import venue_authorship


async def _seed(db, institution_factory):
    inst = await institution_factory(code="ut")
    run = HarvestRun(
        source="test", entity_type="works", institution_id=inst.id,
        status="completed", config_fingerprint="t",
    )
    db.add(run)
    await db.flush()  # run.id needed by the work rows
    db.add(journal_factory("aaaa-0001", title="Venue journal", search_text="Venue"))
    db.add(journal_factory("zzzz-9999", title="Empty venue", search_text="Empty"))
    authors = [
        Author(
            institution_id=inst.id, pure_uuid="a1", name="Ann A",
            faculty="Science", research_group="Group X",
        ),
        Author(
            institution_id=inst.id, pure_uuid="a2", name="Bob B",
            faculty="Science", research_group=None,
        ),
        Author(
            institution_id=inst.id, pure_uuid="a3", name="Cara C",
            faculty=None, research_group=None,
        ),
    ]
    db.add_all(authors)

    def work(uuid, wtype="article"):
        return Work(
            institution_id=inst.id, pure_uuid=uuid, journal_issn_l="aaaa-0001",
            title=f"Work {uuid}", norm_title=f"work {uuid}", year=2022,
            work_type=wtype, first_seen_run=run.id, last_seen_run=run.id,
        )

    db.add_all([work(f"w{i}") for i in (1, 2, 3)])
    db.add(work("w4", wtype="dataset"))
    await db.flush()  # works must exist before the edge rows (FK order)
    db.add_all(
        [
            WorkPureAuthor(institution_id=inst.id, work_pure_uuid="w1", person_uuid="a1"),
            WorkPureAuthor(institution_id=inst.id, work_pure_uuid="w1", person_uuid="a2"),
            WorkPureAuthor(institution_id=inst.id, work_pure_uuid="w2", person_uuid="a1"),
            WorkPureAuthor(institution_id=inst.id, work_pure_uuid="w2", person_uuid="a2"),
            WorkPureAuthor(institution_id=inst.id, work_pure_uuid="w3", person_uuid="a3"),
            # Excluded type: edge exists but the work leaves the population.
            WorkPureAuthor(institution_id=inst.id, work_pure_uuid="w4", person_uuid="a1"),
            # Outside the venue set.
            Work(
                institution_id=inst.id, pure_uuid="w5", journal_issn_l="zzzz-9999",
                title="Work w5", norm_title="work w5", year=2022, work_type="article",
                first_seen_run=run.id, last_seen_run=run.id,
            ),
        ]
    )
    await db.commit()
    return inst


@requires_db
async def test_aggregates_match_two_pass_semantics(db, institution_factory):
    inst = await _seed(db, institution_factory)
    out = await venue_authorship(db, inst, issn_l="aaaa-0001")
    # Distinct works with an edge and a served type: w1-w3 (w4 dataset
    # excluded, w5 other venue).
    assert out["n_ut_works"] == 3
    # Faculty buckets: count(distinct works) desc, name asc; Cara stays in
    # the total but forms no bucket (faculty missing).
    assert out["faculties"] == [{"name": "Science", "works": 2}]
    assert out["research_groups"] == [{"name": "Group X", "works": 2}]
    # Top authors: works desc, lower(name) asc.
    assert [(t["pure_uuid"], t["works"]) for t in out["top_authors"]] == [
        ("a1", 2),
        ("a2", 2),
        ("a3", 1),
    ]
    assert all(
        set(t) == {"pure_uuid", "name", "faculty", "research_group", "works"}
        for t in out["top_authors"]
    )


@requires_db
async def test_empty_venue_and_issn_set(db, institution_factory):
    inst = await _seed(db, institution_factory)
    assert await venue_authorship(db, inst, issns=[]) == {
        "n_ut_works": 0,
        "faculties": [],
        "research_groups": [],
        "top_authors": [],
    }
    out = await venue_authorship(db, inst, issns=["9999-x999"])
    assert out["n_ut_works"] == 0
    assert out["faculties"] == []


@requires_db
async def test_group_by_key_not_authors(db, institution_factory):
    """A name shared by two author uuids stays two top-author rows
    (grouping is per author_uuid, not per name)."""
    inst = await _seed(db, institution_factory)
    db.add(
        Author(
            institution_id=inst.id, pure_uuid="a4", name="Ann A",
            faculty="Other", research_group=None,
        )
    )
    db.add(
        WorkPureAuthor(institution_id=inst.id, work_pure_uuid="w5", person_uuid="a4")
    )
    await db.commit()
    out = await venue_authorship(db, inst, issn_l="aaaa-0001")
    names = [(t["pure_uuid"], t["name"]) for t in out["top_authors"]]
    assert names == [("a1", "Ann A"), ("a2", "Bob B"), ("a3", "Cara C")]
    # a4's edge is on w5, a different venue: not counted here.
    assert out["n_ut_works"] == 3
