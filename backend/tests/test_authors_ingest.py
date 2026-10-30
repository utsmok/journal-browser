"""Author ingest: pure transforms (faculty/group/org derivation, edge join,
affiliation confirmation, primary topic) and an end-to-end idempotency run
against the local DB with a fake source."""

from conftest import journal_factory, requires_db
from journal_browser.harvest.authors import (
    SourceData,
    augment_faculty,
    author_id_index,
    build_edge_map,
    derive_identity,
    is_confirmed,
    primary_topic_from_venues,
)
from journal_browser.harvest.authors import ingest_authors as run_ingest
from journal_browser.models import Author, AuthorWork, HarvestRun, Work

UT_UUID = "ut-root-uuid"
UT_ROR = "https://ror.org/006hf6230"
TNW = "Faculty of Science and Technology"
DEPT = "Quantum Transport in Matter"


def _orgs() -> dict[int, tuple[str, str]]:
    return {
        1: (UT_UUID, "University of Twente"),
        2: ("tnw-uuid", TNW),
        3: ("dept-uuid", DEPT),
        4: ("delft-uuid", "Delft University of Technology"),
    }


def _tree() -> dict[int, list[tuple[int, int]]]:
    return {
        1: [(0, 1)],
        2: [(0, 2), (1, 1)],
        3: [(0, 3), (1, 2), (2, 1)],
        4: [(0, 4)],
    }


def _payload(*affiliation_org_uuids: str) -> dict:
    return {
        "cerif": {
            "affiliations": [
                {"affiliation_id": uuid, "affiliation_name": f"name-{uuid}"}
                for uuid in affiliation_org_uuids
            ]
        }
    }


def _data() -> SourceData:
    data = SourceData()
    data.orgs = _orgs()
    # Source org.ror: bare ROR ids; UT root has one, faculty/dept/Delft none.
    data.org_rors = {1: "006hf6230", 2: None, 3: None, 4: "012p63287"}
    data.tree = _tree()
    return data


def test_derive_identity_faculty_group_orgs():
    data = _data()
    payload = _payload("dept-uuid", UT_UUID)
    faculty, group, orgs = derive_identity(payload, data)
    assert faculty == TNW  # canonicalized full name
    assert group == DEPT  # self org, not faculty/root, chain reaches TNW
    # Most specific first (largest closure depth), root last.
    assert orgs == [DEPT, "University of Twente"]


def test_derive_identity_short_code_canonicalized():
    data = _data()
    data.orgs[5] = ("eemcs-uuid", "EEMCS")
    data.tree[5] = [(0, 5), (1, 1)]
    faculty, _group, _orgs = derive_identity(_payload("eemcs-uuid"), data)
    assert faculty == (
        "Faculty of Electrical Engineering, Mathematics and Computer Science"
    )


def test_derive_identity_without_faculty_chain():
    data = _data()
    faculty, group, orgs = derive_identity(_payload("delft-uuid"), data)
    assert faculty is None
    assert group is None
    assert orgs == ["Delft University of Technology"]


def test_derive_identity_empty_affiliations():
    faculty, group, orgs = derive_identity(_payload(), _data())
    assert faculty is None and group is None and orgs == []


def test_augment_faculty_via_canonical_person():
    data = _data()
    author = {"pure_uuid": "b-uuid", "orcid": "0000-0002-1234", "openalex_author_id": "a5038098443"}
    data.person_orcids = {"0000-0002-1234": 11}
    data.person_by_openalex = {"a5038098443": 12}
    data.person_orgs = {11: [2], 12: [4]}  # orcid branch wins, chain hits TNW
    assert augment_faculty(author, data) == TNW


def test_augment_faculty_openalex_branch():
    data = _data()
    author = {"pure_uuid": "b-uuid", "orcid": None, "openalex_author_id": "A5038098443"}
    data.person_by_openalex = {"a5038098443": 12}  # lower-cased on both sides
    data.person_orgs = {12: [3]}
    assert augment_faculty(author, data) == TNW


def test_augment_faculty_no_path():
    data = _data()
    author = {"pure_uuid": "b-uuid", "orcid": None, "openalex_author_id": None}
    assert augment_faculty(author, data) is None


def test_is_confirmed_branches():
    data = _data()
    # Child-of-faculty (dept -> TNW -> UT root) and the UT root affiliation
    # itself (depth 0) both resolve to the institution ROR; URL form.
    assert is_confirmed(_payload("dept-uuid"), data, UT_ROR) is True
    assert is_confirmed(_payload("ut-root-uuid"), data, UT_ROR) is True
    assert is_confirmed(_payload("tnw-uuid"), data, UT_ROR) is True
    # Sibling org not under the ROR org; missing payload; no institution ROR.
    assert is_confirmed(_payload("delft-uuid"), data, UT_ROR) is False
    assert is_confirmed({}, data, UT_ROR) is False
    assert is_confirmed(_payload("dept-uuid"), data, None) is False


def test_primary_topic_weighting_and_ties():
    topics = {"j1": [{"id": "T1", "display_name": "Physics"},
                     {"id": "T2", "display_name": "Chemistry"}],
              "j2": [{"id": "T2", "display_name": "Chemistry"}]}
    # Without stored counts a venue contributes to its primary topic only:
    # Physics 3 beats Chemistry 1.
    assert primary_topic_from_venues({"j1": 3, "j2": 1}, topics) == "Physics"
    # With counts, venue mass splits by the per-source topic share: j1
    # spreads 3 works 1.5/1.5, j2 adds 1 -> Chemistry 2.5 beats Physics 1.5.
    counted = {"j1": [{"id": "T1", "display_name": "Physics", "count": 1},
                      {"id": "T2", "display_name": "Chemistry", "count": 1}],
               "j2": [{"id": "T2", "display_name": "Chemistry", "count": 1}]}
    assert primary_topic_from_venues({"j1": 3, "j2": 1}, counted) == "Chemistry"
    # A 1:1 count split inside one venue ties; alphabetical wins.
    assert primary_topic_from_venues({"j1": 1}, counted) == "Chemistry"
    # Entries with a subfield are labelled by subfield, split by count.
    sub = {"j1": [{"display_name": "T-a", "count": 3, "subfield": "Materials"},
                  {"display_name": "T-b", "count": 1, "subfield": "Optics"}]}
    assert primary_topic_from_venues({"j1": 4}, sub) == "Materials"
    both = {"j1": [{"id": "T1", "display_name": "Zeta"}],
            "j2": [{"id": "T1", "display_name": "Alpha"}]}
    assert primary_topic_from_venues({"j1": 1, "j2": 1}, both) == "Alpha"
    # No venues / no topics / malformed entries -> None.
    assert primary_topic_from_venues({}, topics) is None
    assert primary_topic_from_venues({"j9": 2}, topics) is None
    assert primary_topic_from_venues({"j1": 2}, {"j1": [None, "x", {"display_name": None}]}) is None


def test_edge_map_lowercase_and_alt_ids():
    authors = [
        {"pure_uuid": "a-uuid", "openalex_author_id": "A5038098443", "openalex_alt_ids": ["A999"]},
        {"pure_uuid": "b-uuid", "openalex_author_id": None, "openalex_alt_ids": []},
    ]
    index = author_id_index(authors)
    assert index["a5038098443"] == "a-uuid"
    assert index["a999"] == "a-uuid"
    edges = [
        ("a5038098443", "w1"),  # lower-cased source form
        ("A5038098443", "w2"),  # mixed-case input still matches
        ("a999", "w3"),  # alt id
        ("unknown", "w1"),  # no author: dropped
        ("a5038098443", "w9"),  # work not held locally: dropped
    ]
    mapping = build_edge_map(edges, index, {"w1", "w2", "w3"})
    assert mapping == {"a-uuid": {"w1", "w2", "w3"}}


def _fixture_source() -> SourceData:
    data = _data()
    data.authors = [
        {
            "pure_uuid": "a-uuid",
            "orcid": "0000-0002-0001",
            "name": "Alice Author",
            "openalex_author_id": "A5038098443",
            "openaire_person_id": None,
            "crossref_orcid": None,
            "openalex_alt_ids": ["A999"],
        },
        {
            "pure_uuid": "b-uuid",
            "orcid": None,
            "name": "Bob Noafilliation",
            "openalex_author_id": "A111",
            "openaire_person_id": None,
            "crossref_orcid": None,
            "openalex_alt_ids": [],
        },
    ]
    data.persons = {
        "a-uuid": _payload("dept-uuid", UT_UUID),
        "b-uuid": _payload(),
    }
    data.person_orcids = {"0000-0002-0001": 11}
    # Bob (empty CERIF payload) reaches a faculty only via his OpenAlex id.
    data.person_by_openalex = {"a111": 12}
    data.person_orgs = {11: [2], 12: [2]}
    data.edges = [
        ("a5038098443", "w1"),
        ("a999", "w2"),
        ("a111", "w1"),  # b: empty payload, faculty via canonical person
        ("ghost", "w1"),
    ]
    return data


@requires_db
async def test_ingest_idempotent(db, institution_factory, monkeypatch):
    from datetime import UTC, datetime

    from sqlalchemy import select

    async def _source(_engine):
        return _fixture_source()

    monkeypatch.setattr("journal_browser.harvest.authors.fetch_source", _source)

    inst = await institution_factory(code="ut", ror=UT_ROR)
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()
    db.add_all(
        [
            journal_factory("1111-1111", topics=[{"id": "T1", "display_name": "Physics"}]),
            journal_factory("2222-2221", topics=[{"id": "T2", "display_name": "Chemistry"}]),
            Work(
                institution_id=inst.id,
                pure_uuid="w1",
                title="Work One",
                norm_title="work one",
                year=2023,
                oa_status="gold",
                journal_issn_l="1111-1111",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            Work(
                institution_id=inst.id,
                pure_uuid="w2",
                title="Work Two",
                norm_title="work two",
                year=2022,
                oa_status="closed",
                journal_issn_l="2222-2221",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
        ]
    )
    await db.flush()

    stats = await run_ingest(db, inst.id, None, inst.ror)
    await db.commit()
    assert stats == {
        "authors": 2, "edges": 3, "with_faculty": 2, "with_research_group": 1, "confirmed": 1,
    }

    a_rows = {row.pure_uuid: row for row in (await db.execute(select(Author))).scalars()}
    assert a_rows["a-uuid"].faculty == TNW
    assert a_rows["a-uuid"].research_group == DEPT
    assert a_rows["a-uuid"].n_works == 2
    assert a_rows["a-uuid"].orgs == [DEPT, "University of Twente"]
    # a: dept -> TNW -> UT root closure reaches the institution ROR.
    assert a_rows["a-uuid"].confirmed is True
    assert a_rows["a-uuid"].last_pub_year == 2023
    # Physics 1 vs Chemistry 1 tie -> alphabetical.
    assert a_rows["a-uuid"].primary_topic == "Chemistry"
    # b: no CERIF affiliations (unconfirmed), faculty via canonical-person
    # fallback.
    assert a_rows["b-uuid"].faculty == TNW
    assert a_rows["b-uuid"].n_works == 1
    assert a_rows["b-uuid"].confirmed is False
    assert a_rows["b-uuid"].last_pub_year == 2023
    assert a_rows["b-uuid"].primary_topic == "Physics"

    edges = {
        (row.author_pure_uuid, row.work_pure_uuid)
        for row in (await db.execute(select(AuthorWork))).scalars()
    }
    assert edges == {("a-uuid", "w1"), ("a-uuid", "w2"), ("b-uuid", "w1")}

    # Rerun: identical end state (upsert + full edge replace, no dupes).
    await run_ingest(db, inst.id, None, inst.ror)
    await db.commit()
    rows = {row.pure_uuid: row for row in (await db.execute(select(Author))).scalars()}
    assert len(rows) == 2
    assert len((await db.execute(select(AuthorWork))).scalars().all()) == 3
    assert rows["a-uuid"].confirmed is True
    assert rows["a-uuid"].last_pub_year == 2023
    assert rows["a-uuid"].primary_topic == "Chemistry"

    # Retiring a work drops it (and its author edge count) on the next run.
    w1 = await db.scalar(select(Work).where(Work.pure_uuid == "w1"))
    w1.retired_at = datetime.now(UTC)
    await db.commit()
    await run_ingest(db, inst.id, None, inst.ror)
    await db.commit()
    remaining = {
        (row.author_pure_uuid, row.work_pure_uuid)
        for row in (await db.execute(select(AuthorWork))).scalars()
    }
    # w1 was both authors' shared edge; only Alice's w2 survives.
    assert remaining == {("a-uuid", "w2")}
    final = {row.pure_uuid: row for row in (await db.execute(select(Author))).scalars()}
    assert final["a-uuid"].n_works == 1
    assert final["a-uuid"].last_pub_year == 2022
    assert final["a-uuid"].primary_topic == "Chemistry"  # single venue, 1 work
    assert final["b-uuid"].n_works == 0
    assert final["b-uuid"].last_pub_year is None
    assert final["b-uuid"].primary_topic is None
