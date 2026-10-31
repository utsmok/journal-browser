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
    # carol's profile never resolves; dave rides the work-level arm;
    # eve is roster-admitted (dept profile) with no confirmed openalex id
    # (her namesake competitors stayed candidates); frank is rostered via
    # the orcid-direct listing join; gina and karl via the weak-affiliation
    # rung (confirmed identity substitutes for org closure)
    assert roster == {"p-alice", "p-bob", "p-dave", "p-eve", "p-frank", "p-gina", "p-karl"}

    alice = next(a for a in data.authors if a["pure_uuid"] == "p-alice")
    assert alice["openalex_author_id"] == "a-alice"  # confirmed rows only
    assert alice["openalex_alt_ids"] == ["a-alice2"]  # work-matched twin is a fact too
    assert alice["orcid"] == ORCID_ALICE
    assert alice["name"] == "Alice Author"

    eve = next(a for a in data.authors if a["pure_uuid"] == "p-eve")
    assert eve["openalex_author_id"] is None  # namesake competitors stayed candidates
    assert eve["openalex_alt_ids"] == []

    frank = next(a for a in data.authors if a["pure_uuid"] == "p-frank")
    assert frank["openalex_author_id"] == "A-frank"  # listing join, confirmed

    # the openaire identity row never leaks into openalex ids
    assert set(data.edges) == {
        ("a-alice", "w1"),
        ("a-bob", "w1"),
        ("a-dave", "w1"),
        ("a-alice2", "w2"),
        ("a-bob", "w3"),
        ("a-carol", "w3"),
        ("a-eve", "w4"),
        ("a-eve2", "w5"),
        ("a-eve", "w6"),
        ("a-eve2", "w6"),
        ("a-eve3", "w7"),
        ("a-gina", "w8"),
        ("a-hank", "w9"),
        ("a-ivy", "w10"),
        ("a-ivy", "w11"),
        ("a-jack", "w12"),
        ("a-eve", "w13"),
        ("a-jack", "w13"),
        ("a-karl", "w14"),
    }
    # pure's own author lists ride verbatim (roster-gated at ingest)
    assert set(data.pure_edges) == {
        ("p-alice", "w1"),
        ("p-bob", "w1"),
        ("p-dave", "w1"),
        ("p-alice", "w2"),
        ("p-bob", "w3"),
        ("p-carol", "w3"),
        ("p-eve", "w4"),
        ("p-eve", "w5"),
        ("p-eve", "w6"),
        ("p-eve", "w7"),
        ("p-gina", "w8"),
        ("p-hank", "w9"),
        ("p-ivy1", "w10"),
        ("p-ivy2", "w11"),
        ("p-jack", "w12"),
        ("p-eve", "w13"),
        ("p-karl", "w14"),
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
    assert stats["authors"] == 7
    assert stats["confirmed"] == 5  # the weak rung rides identity evidence, not HR affiliation
    await db.commit()

    authors = {r.pure_uuid: r for r in (await db.execute(select(Author))).scalars()}
    assert set(authors) == {
        "p-alice",
        "p-bob",
        "p-dave",
        "p-eve",
        "p-frank",
        "p-gina",
        "p-karl",
    }
    alice = authors["p-alice"]
    assert alice.confirmed is True  # profile dept chain reaches the ROR root
    assert alice.openalex_ids == ["a-alice", "a-alice2"]  # primary + twin
    assert alice.n_works == 2  # w1 + w2 (OpenAlex + pure edges merged)
    assert alice.last_pub_year == 2023
    assert authors["p-dave"].confirmed is True  # work-level arm confirmation
    assert authors["p-bob"].openalex_ids == ["a-bob"]
    assert authors["p-eve"].openalex_ids == []  # nothing confirmed, still rostered
    assert authors["p-frank"].openalex_ids == ["a-frank"]  # listing join
    assert authors["p-gina"].openalex_ids == ["a-gina"]  # weak rung: admitted, unconfirmed
    assert authors["p-gina"].confirmed is False
    assert authors["p-karl"].openalex_ids == ["a-karl"]
