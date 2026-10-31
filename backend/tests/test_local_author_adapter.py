"""The local source adapter: fetch_local_source builds the SourceData
contract from journal-browser's own stores, and ingest_authors consumes
it unchanged (the standalone author path end to end)."""

from sqlalchemy import select

from conftest import requires_db
from journal_browser.harvest.author_ids import resolve_author_ids
from journal_browser.harvest.authors import fetch_local_source, ingest_authors
from journal_browser.models import Author
from test_author_ids import ORCID_ALICE, _fixture


@requires_db
async def test_adapter_roster_edges_and_ids(db, institution_factory):
    inst = await _fixture(db, institution_factory)
    await resolve_author_ids(db, inst, run_sweeps=False)
    await db.commit()

    data = await fetch_local_source(db, inst)
    roster = {a["pure_uuid"] for a in data.authors}
    # carol's profile never resolves; dave rides the work-level arm
    assert roster == {"p-alice", "p-bob", "p-dave"}

    alice = next(a for a in data.authors if a["pure_uuid"] == "p-alice")
    assert alice["openalex_author_id"] == "a-alice"  # confirmed rows only
    assert alice["openalex_alt_ids"] == ["a-alice2"]  # work-matched twin is a fact too
    assert alice["orcid"] == ORCID_ALICE
    assert alice["name"] == "Alice Author"

    # OpenAlex authorships DOI-joined onto local works, ids lower-cased
    assert set(data.edges) == {
        ("a-alice", "w1"),
        ("a-bob", "w1"),
        ("a-dave", "w1"),
        ("a-alice2", "w2"),
        ("a-bob", "w3"),
        ("a-carol", "w3"),
    }
    # pure's own author lists ride verbatim (roster-gated at ingest)
    assert set(data.pure_edges) == {
        ("p-alice", "w1"),
        ("p-bob", "w1"),
        ("p-dave", "w1"),
        ("p-alice", "w2"),
        ("p-bob", "w3"),
        ("p-carol", "w3"),
    }
    # the resolved root carries the institution's bare ROR
    assert data.org_rors.get("root") == "006hf6230"
    assert data.tree["dept"] == [(0, "dept"), (1, "root")]
    # person_org arms: dave's work-level affiliation joined in
    assert set(data.person_orgs["p-dave"]) == {"partner", "dept"}


@requires_db
async def test_adapter_ingest_roundtrip(db, institution_factory):
    inst = await _fixture(db, institution_factory)
    await resolve_author_ids(db, inst, run_sweeps=False)
    await db.commit()
    data = await fetch_local_source(db, inst)

    stats = await ingest_authors(db, inst.id, data, inst.ror)
    assert stats["authors"] == 3
    assert stats["confirmed"] == 3
    await db.commit()

    authors = {r.pure_uuid: r for r in (await db.execute(select(Author))).scalars()}
    assert set(authors) == {"p-alice", "p-bob", "p-dave"}
    alice = authors["p-alice"]
    assert alice.confirmed is True  # profile dept chain reaches the ROR root
    assert alice.openalex_ids == ["a-alice", "a-alice2"]  # primary + twin
    assert alice.n_works == 2  # w1 + w2 (OpenAlex + pure edges merged)
    assert alice.last_pub_year == 2023
    assert authors["p-dave"].confirmed is True  # work-level arm confirmation
    assert authors["p-bob"].openalex_ids == ["a-bob"]
