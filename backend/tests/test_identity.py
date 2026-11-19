"""Author identity pipeline as served: idempotent ingest, resolution
gates, cascade rung decisions, roster edges, the profile bundle, gap
tags, and portal-person bindings.

Replaces test_authors_ingest, test_author_cascade, test_author_ids,
test_local_author_adapter, test_authors_api (profile core),
test_author_gap_tags, test_authorship, test_pure_portal_persons, and
test_people_utwente. Every old branch family asserts through an
ingest/resolve outcome, stored rows, or a served response instead of
driving private match helpers one branch at a time.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from conftest import journal_factory, pair_rows, requires_db
from journal_browser.config import reset_settings_cache
from journal_browser.harvest.author_ids import openaire_author_orcid, resolve_author_ids
from journal_browser.harvest.authors import SourceData, fetch_local_source, ingest_authors
from journal_browser.harvest.people_utwente import (
    name_match_tier,
    tile_clean_name,
    tile_common_name,
)
from journal_browser.harvest.pure.xmlrecords import _norm_title
from journal_browser.harvest.pure_portal_persons import apply_person_bindings, parse_listing
from journal_browser.ingest import IngestSession
from journal_browser.models import (
    Author,
    AuthorIdentity,
    AuthorWork,
    HarvestRun,
    JournalFlags,
    OpenalexWork,
    PureOrg,
    PureOrgParent,
    PurePerson,
    PurePersonOrg,
    SourceRecord,
    StatusChangeLog,
    Work,
    WorkPureAuthor,
)
from journal_browser.routers.admin.auth import reset_login_limiter
from journal_browser.services import authorship

TNW = "Faculty of Science and Technology"
DEPT = "Quantum Transport in Matter"
MESA = "MESA+ Institute"
EEMCS = "Faculty of Electrical Engineering, Mathematics and Computer Science"
UT_ROR = "https://ror.org/006hf6230"
ADMIN_PW = "identity-test-pw"

ORCID_ALICE = "0000-0002-1825-0097"
ORCID_FRANK = "0000-0002-4444-4444"
ORCID_GINA = "0000-0009-0003-0003"
ORCID_IVY = "0000-0009-0005-0005"
ORCID_KARL = "0000-0009-0008-0008"
ORCID_J1 = "0000-0009-0006-0006"
ORCID_J2 = "0000-0009-0007-0007"
ORCID_M1 = "0000-0009-0009-0009"
ORCID_M2 = "0000-0009-0001-0002"
ORCID_P1 = "0000-0001-7295-651x"
KAI_ORCID = "0009-0007-4912-4652"

BOOK_DOI = "10.10.0/book"
CHAPTER_DOI = f"{BOOK_DOI}_4"
SAME_TITLE_DOI = "10.10.0/ox"
HELD_DOI = "10.10.0/held"
MISSING_DOI = "10.10.0/miss"


@pytest.fixture
async def admin_client(client, monkeypatch):
    monkeypatch.setenv("JB_ADMIN_PASSWORD", ADMIN_PW)
    reset_settings_cache()
    reset_login_limiter()
    yield client
    reset_settings_cache()
    reset_login_limiter()


def _fixture_source() -> SourceData:
    """Hand-built pull: Alice carries dept + institute + root CERIF
    affiliations; Bob's CERIF is empty and reaches a faculty only via his
    canonical OpenAlex person."""
    data = SourceData()
    data.orgs = {
        1: ("ut-root-uuid", "University of Twente"),
        2: ("tnw-uuid", TNW),
        3: ("dept-uuid", DEPT),
        5: ("mesa-uuid", MESA),
    }
    data.org_rors = {1: "006hf6230", 2: None, 3: None, 5: None}
    data.tree = {
        1: [(0, 1)],
        2: [(0, 2), (1, 1)],
        3: [(0, 3), (1, 2), (2, 1)],
        5: [(0, 5), (1, 1)],
    }
    data.institute_orgs = {5}
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
            "name": "Bob Noaffiliation",
            "openalex_author_id": "A111",
            "openaire_person_id": None,
            "crossref_orcid": None,
            "openalex_alt_ids": [],
        },
    ]
    data.persons = {
        "a-uuid": {
            "cerif": {
                "affiliations": [
                    {"affiliation_id": "dept-uuid", "affiliation_name": "n-dept"},
                    {"affiliation_id": "mesa-uuid", "affiliation_name": "n-mesa"},
                    {"affiliation_id": "ut-root-uuid", "affiliation_name": "n-root"},
                ]
            }
        },
        "b-uuid": {"cerif": {}},
    }
    data.person_orcids = {"0000-0002-0001": 11}
    data.person_by_openalex = {"a111": 12}
    data.person_orgs = {11: [2], 12: [2]}
    data.edges = [
        ("a5038098443", "w1"),
        ("a999", "w2"),
        ("a111", "w1"),
        ("ghost", "w1"),  # no such author: dropped
    ]
    # Pure's own author list gives Bob w2 even though OpenAlex never did.
    data.pure_edges = [("b-uuid", "w2")]
    return data


@requires_db
async def test_author_ingest_is_idempotent(db, institution_factory):
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

    stats = await ingest_authors(db, inst.id, _fixture_source(), inst.ror)
    await db.commit()
    assert stats == {
        "authors": 2,
        "edges": 4,
        "with_faculty": 2,
        "with_research_group": 1,
        "with_institute": 1,
        "confirmed": 2,
    }

    rows = {row.pure_uuid: row for row in (await db.execute(select(Author))).scalars()}
    alice = rows["a-uuid"]
    assert alice.faculty == TNW
    assert alice.research_group == DEPT
    assert alice.institute == MESA
    # Most specific org first, root last; institute chains stay display-only.
    assert alice.orgs == [DEPT, MESA, "University of Twente"]
    assert alice.openalex_ids == ["a5038098443", "a999"]
    assert alice.openalex_author_id == "a5038098443"  # canonical lower-cased
    assert alice.confirmed is True  # dept closure reaches the institution ROR
    assert alice.n_works == 2 and alice.last_pub_year == 2023
    assert alice.primary_topic == "Chemistry"  # 1:1 venue tie -> alphabetical
    bob = rows["b-uuid"]
    assert bob.faculty == TNW  # canonical-person arm fills the empty CERIF
    assert bob.institute is None and bob.confirmed is True
    edges = {
        (row.author_pure_uuid, row.work_pure_uuid)
        for row in (await db.execute(select(AuthorWork))).scalars()
    }
    assert edges == {("a-uuid", "w1"), ("a-uuid", "w2"), ("b-uuid", "w1"), ("b-uuid", "w2")}

    # Rerun: upsert + full edge replace, no duplicates.
    await ingest_authors(db, inst.id, _fixture_source(), inst.ror)
    await db.commit()
    rows = {row.pure_uuid: row for row in (await db.execute(select(Author))).scalars()}
    assert len(rows) == 2
    assert len((await db.execute(select(AuthorWork))).scalars().all()) == 4
    assert rows["a-uuid"].primary_topic == "Chemistry"

    # A work retired since the last run drops out with its edge and counts.
    w1 = await db.scalar(select(Work).where(Work.pure_uuid == "w1"))
    w1.retired_at = datetime.now(UTC)
    await db.commit()
    await ingest_authors(db, inst.id, _fixture_source(), inst.ror)
    await db.commit()
    remaining = {
        (row.author_pure_uuid, row.work_pure_uuid)
        for row in (await db.execute(select(AuthorWork))).scalars()
    }
    assert remaining == {("a-uuid", "w2"), ("b-uuid", "w2")}
    final = {row.pure_uuid: row for row in (await db.execute(select(Author))).scalars()}
    assert final["a-uuid"].n_works == 1
    assert final["a-uuid"].last_pub_year == 2022
    assert final["b-uuid"].n_works == 1 and final["b-uuid"].last_pub_year == 2022


async def _identity_fixture(db, institution_factory):
    """One UT scenario for the resolution cascade: the roster gates
    (profile + work-level arms, partner exclusion), the namesake/conflict
    policies, the weak-affiliation rung, the orcid-listing join, and one
    work per cascade rung."""
    inst = await institution_factory(code="ut", name="University of Twente", ror=UT_ROR)
    db.add_all(
        [
            PureOrg(
                institution_id=inst.id,
                uuid="root",
                name="University of Twente",
                org_type="University",
            ),
            PureOrg(institution_id=inst.id, uuid="dept", name="Science", org_type="faculty"),
            PureOrg(
                institution_id=inst.id, uuid="partner", name="Partner U", org_type="university"
            ),
            # No parent edge: the org dead end the weak-affiliation rung serves.
            PureOrg(
                institution_id=inst.id,
                uuid="flat",
                name="Stochastic Operations Research",
                org_type="department",
            ),
            PureOrgParent(institution_id=inst.id, org_uuid="dept", parent_uuid="root"),
        ]
    )

    def _person(uuid, first, family, affs, orcid=None):
        return PurePerson(
            institution_id=inst.id,
            uuid=uuid,
            orcid=orcid,
            name=f"{first} {family}",
            payload={
                "cerif": {
                    "first_names": first,
                    "family_names": family,
                    "affiliations": [{"affiliation_id": a} for a in affs],
                }
            },
        )

    db.add_all(
        [
            _person("p-alice", "Alice", "Author", ["dept"], ORCID_ALICE),
            _person("p-bob", "Bob", "Builder", ["dept"]),
            _person("p-carol", "Carol", "Partner", ["partner"]),
            _person("p-dave", "Dave", "Worker", ["partner"]),
            _person("p-eve", "Eve", "Namesake", ["dept"]),
            _person("p-frank", "Frank", "Listing", ["dept"], ORCID_FRANK),
            _person("p-gina", "Gina", "Flat", ["flat"]),
            _person("p-hank", "Hank", "Flat", ["flat"]),
            _person("p-ivy1", "Ivy", "Twin", ["flat"]),
            _person("p-ivy2", "Ivy", "Twin", ["flat"]),
            _person("p-jack", "Jack", "Flat", ["flat"]),
            _person("p-karl", "Karl", "Flat", ["flat"]),
            _person("p-mary", "Mary", "Flat", ["flat"]),
            _person("p-orcid", "Mandy", "Velthuis", ["dept"], ORCID_P1),
            _person("p-name", "Nora", "Fielder", ["dept"]),
            _person("p-init", "Anneke", "de Vries", ["dept"]),
            _person("p-family", "L.", "Maas", ["dept"]),
            _person("p-fuzzy", "J.B.F.", "van Erp", ["dept"]),
            _person("p-wang", "L.", "Wang", ["dept"]),
            _person("p-ambig", "Michael", "Velthuis", ["dept"]),
        ]
    )
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()
    db.add(journal_factory("1234-5678"))

    def _work(uuid, doi):
        return Work(
            institution_id=inst.id,
            pure_uuid=uuid,
            title=f"Work {uuid}",
            norm_title=f"work {uuid}",
            year=2023,
            doi_normalized=doi,
            journal_issn_l="1234-5678",
            first_seen_run=run.id,
            last_seen_run=run.id,
        )

    db.add_all(
        [_work(f"w{n}", f"10.1000/w{n}") for n in range(1, 18)]
        + [
            _work("wc-orcid", "10.1000/c1"),
            _work("wc-name", "10.1000/c2"),
            _work("wc-init", "10.1000/c3"),
            _work("wc-family", "10.1000/c4"),
            _work("wc-fuzzy", "10.1000/c5"),
            _work("wc-wang", "10.1000/c6"),
            _work("wc-ambig", "10.1000/c7"),
        ]
    )
    await db.flush()  # journal + works exist before the author edges

    def _edge(work, person, first, family, affs):
        return WorkPureAuthor(
            institution_id=inst.id,
            work_pure_uuid=work,
            person_uuid=person,
            position=0,
            first_names=first,
            family_names=family,
            affiliations=affs,
        )

    db.add_all(
        [
            _edge("w1", "p-alice", "Alice", "Author", ["dept"]),
            _edge("w1", "p-bob", "Bob", "Builder", ["dept"]),
            _edge("w1", "p-dave", "Dave", "Worker", ["dept"]),  # work-level affiliation arm
            _edge("w2", "p-alice", "A.", "Author", []),
            _edge("w3", "p-bob", "Bob", "Builder", ["dept"]),
            _edge("w3", "p-carol", "Carol", "Partner", []),
            _edge("w4", "p-eve", "Eve", "Namesake", ["dept"]),
            _edge("w5", "p-eve", "Eve", "Namesake", ["dept"]),
            _edge("w6", "p-eve", "Eve", "Namesake", ["dept"]),
            _edge("w7", "p-eve", "Eve", "Namesake", ["dept"]),
            _edge("w8", "p-gina", "Gina", "Flat", ["flat"]),
            _edge("w9", "p-hank", "Hank", "Flat", ["flat"]),
            _edge("w10", "p-ivy1", "Ivy", "Twin", ["flat"]),
            _edge("w11", "p-ivy2", "Ivy", "Twin", ["flat"]),
            _edge("w12", "p-jack", "Jack", "Flat", ["flat"]),
            _edge("w13", "p-eve", "Eve", "Namesake", ["dept"]),
            _edge("w14", "p-karl", "K.", "Flat", ["flat"]),
            _edge("w15", "p-gina", "Gina", "Flat", ["flat"]),
            _edge("w16", "p-mary", "Mary", "Flat", ["flat"]),
            _edge("w17", "p-mary", "Mary", "Flat", ["flat"]),
            _edge("wc-orcid", "p-orcid", "Mandy", "Velthuis", ["dept"]),
            _edge("wc-name", "p-name", "Nora", "Fielder", ["dept"]),
            _edge("wc-init", "p-init", "Anneke", "de Vries", ["dept"]),
            _edge("wc-family", "p-family", "L.", "Maas", ["dept"]),
            _edge("wc-fuzzy", "p-fuzzy", "J.B.F.", "van Erp", ["dept"]),
            _edge("wc-wang", "p-wang", "L.", "Wang", ["dept"]),
            _edge("wc-ambig", "p-ambig", "Michael", "Velthuis", ["dept"]),
        ]
    )

    def _oa(w_id, doi, *authorships):
        return OpenalexWork(
            institution_id=inst.id,
            w_id=w_id,
            doi_normalized=doi,
            title=f"OA {w_id}",
            year=2023,
            work_type="article",
            oa_status="gold",
            authorships=list(authorships),
        )

    db.add_all(
        [
            _oa(
                "W-a",
                "10.1000/w1",
                {"a": "a-alice", "n": "Alice Author", "o": ORCID_ALICE},
                {"a": "a-bob", "n": "B. Builder"},
                {"a": "a-dave", "n": "Dave Worker"},
            ),
            _oa("W-b", "10.1000/w2", {"a": "a-alice2", "n": "A. Author"}),
            _oa(
                "W-c",
                "10.1000/w3",
                {"a": "a-bob", "n": "Bob Builder"},
                {"a": "a-carol", "n": "Carol Partner"},
            ),
            _oa("W-d", "10.1000/w4", {"a": "a-eve", "n": "Eve Namesake"}),
            _oa(
                "W-e",
                "10.1000/w5",
                {"a": "a-eve2", "n": "Eve Namesake", "o": "0000-0009-0001-0001"},
            ),
            _oa(
                "W-f",
                "10.1000/w6",
                {"a": "a-eve", "n": "Eve Namesake"},
                {"a": "a-eve2", "n": "E. Namesake"},
            ),
            _oa(
                "W-g",
                "10.1000/w7",
                {"a": "a-eve3", "n": "Eve Namesake", "o": "0000-0009-0002-0002"},
            ),
            _oa("W-h", "10.1000/w8", {"a": "a-gina", "n": "Gina Flat", "o": ORCID_GINA}),
            _oa("W-i", "10.1000/w9", {"a": "a-hank", "n": "Hank Flat"}),
            _oa("W-j", "10.1000/w10", {"a": "a-ivy", "n": "Ivy Twin", "o": ORCID_IVY}),
            _oa("W-k", "10.1000/w11", {"a": "a-ivy", "n": "Ivy Twin", "o": ORCID_IVY}),
            _oa("W-l", "10.1000/w12", {"a": "a-jack", "n": "Jack Flat", "o": ORCID_J1}),
            _oa(
                "W-m",
                "10.1000/w13",
                {"a": "a-eve", "n": "Eve Namesake"},
                {"a": "a-jack", "n": "J. Flat", "o": ORCID_J2},
            ),
            _oa("W-n", "10.1000/w14", {"a": "a-karl", "n": "Karl Flat", "o": ORCID_KARL}),
            # Gina's orcid-less fragment: never co-listed, rides as a twin.
            _oa("W-o", "10.1000/w15", {"a": "a-gina2", "n": "G. Flat"}),
            _oa("W-p", "10.1000/w16", {"a": "a-mary", "n": "Mary Flat", "o": ORCID_M1}),
            _oa("W-q", "10.1000/w17", {"a": "a-mary", "n": "Mary Flat", "o": ORCID_M2}),
            _oa("W-c1", "10.1000/c1", {"a": "a-orcid", "n": "M. Velthuis", "o": ORCID_P1}),
            _oa("W-c2", "10.1000/c2", {"a": "a-name", "n": "Nora Fielder"}),
            _oa("W-c3", "10.1000/c3", {"a": "a-init", "n": "A. de Vries"}),
            _oa("W-c4", "10.1000/c4", {"a": "a-family", "n": "Anna Maas"}),
            # The K. twin defeats the family-unique rung; fuzzy decides.
            _oa(
                "W-c5",
                "10.1000/c5",
                {"a": "a-fuzzy", "n": "Jeroen Bernard van Erp"},
                {"a": "a-k-erp", "n": "K. van Erp"},
            ),
            _oa("W-c6", "10.1000/c6", {"a": "a-wang", "n": "Wei Wang"}),
            _oa(
                "W-c7",
                "10.1000/c7",
                {"a": "a-v1", "n": "M. Velthuis"},
                {"a": "a-v2", "n": "Max Velthuis"},
            ),
        ]
    )
    oa_run = HarvestRun(
        source="openaire",
        entity_type="work",
        institution_id=inst.id,
        status="completed",
        config_fingerprint="t",
    )
    listing_run = HarvestRun(
        source="openalex",
        entity_type="authors",
        institution_id=inst.id,
        status="completed",
        config_fingerprint="t",
    )
    db.add_all([oa_run, listing_run])
    await db.flush()
    db.add_all(
        [
            SourceRecord(
                source="openaire",
                entity_type="work",
                source_pk="oa:w4",
                payload={
                    "doi": "10.1000/w4",
                    "authors": [
                        {
                            "id": "orcid_______::eve1",
                            "pid": {"id": {"value": "0000-0009-0004-0004", "scheme": "orcid"}},
                            "fullName": "Namesake, Eve",
                        }
                    ],
                },
                content_hash="h-openaire-w4",
                harvest_run_id=oa_run.id,
            ),
            SourceRecord(
                source="openalex",
                entity_type="authors",
                source_pk="A-frank",
                payload={
                    "id": "https://openalex.org/A-frank",
                    "orcid": ORCID_FRANK,
                    "display_name": "Frank Listing",
                },
                content_hash="h-listing-frank",
                harvest_run_id=listing_run.id,
            ),
        ]
    )
    await db.flush()
    return inst


async def _identity_rows(db):
    return {
        (r.author_pure_uuid, r.external_id): r
        for r in (await db.execute(select(AuthorIdentity))).scalars()
    }


@requires_db
async def test_resolve_gates_and_admin_flip_sticks(db, institution_factory, admin_client):
    inst = await _identity_fixture(db, institution_factory)
    stats = await resolve_author_ids(db, inst, run_sweeps=False)
    await db.commit()

    assert stats["matched"] == 9  # alice bob dave eve + the five rung cases
    assert stats["conflicted_authors"] == 2  # alice's twin + eve's namesakes
    assert stats["openaire"]["matched"] == 1
    assert stats["orcid_listing"] == 1
    assert stats["weak_affiliation"] == {
        "admitted": 3,  # gina primary + twin, karl
        "methods": {"name-exact": 1, "name-initials": 1, "fragmentation": 1},
        "skipped_orcid_missing": 2,  # carol, hank
        "skipped_orcid_mismatch": 1,  # jack: the id carries two orcids
        "skipped_orcid_ambiguous": 1,  # mary: her own works carry two
        "skipped_namesake_contested": 2,  # the ivys share one id
    }

    rows = await _identity_rows(db)
    assert not any(uuid == "p-carol" for uuid, _aid in rows)  # partner profile: org gate
    alice = rows[("p-alice", "a-alice")]
    assert (alice.status, alice.method, alice.orcid_corroborated, alice.n_works) == (
        "confirmed",
        "orcid-exact",
        True,
        1,
    )
    twin = rows[("p-alice", "a-alice2")]
    assert (twin.status, twin.method, twin.n_works) == ("confirmed", "fragmentation", 1)
    assert rows[("p-bob", "a-bob")].status == "confirmed"
    assert rows[("p-dave", "a-dave")].status == "confirmed"  # work-level arm
    assert rows[("p-eve", "a-eve")].status == "candidate"  # namesake conflicts: review only
    assert rows[("p-eve", "a-eve2")].evidence["co_occurs_with_primary"] is True
    assert rows[("p-eve", "a-eve3")].status == "candidate"  # orcid contradiction
    oa_eve = rows[("p-eve", "orcid_______::eve1")]
    assert (oa_eve.source, oa_eve.status, oa_eve.method) == (
        "openaire",
        "confirmed",
        "name-initials",
    )
    frank = rows[("p-frank", "A-frank")]
    assert (frank.status, frank.method, frank.n_works, frank.evidence["source"]) == (
        "confirmed",
        "orcid-exact",
        0,
        "author-listing",
    )
    gina = rows[("p-gina", "a-gina")]
    assert (gina.status, gina.method, gina.orcid_corroborated) == ("confirmed", "name-exact", True)
    assert gina.evidence["weak_affiliation"] is True
    assert gina.evidence["orcids"] == [ORCID_GINA]
    gina_twin = rows[("p-gina", "a-gina2")]
    assert (gina_twin.status, gina_twin.method) == ("confirmed", "fragmentation")
    assert gina_twin.evidence["twin_of"] == "a-gina"
    assert rows[("p-karl", "a-karl")].method == "name-initials"
    for key in (
        ("p-hank", "a-hank"),
        ("p-jack", "a-jack"),
        ("p-mary", "a-mary"),
        ("p-ivy1", "a-ivy"),
        ("p-ivy2", "a-ivy"),
    ):
        assert key not in rows

    # Admin flip: sticky against later evidence, audited once, no-op repeat.
    login = await admin_client.post("/api/v1/admin/login", json={"password": ADMIN_PW})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    body = {
        "institution_id": inst.id,
        "author_pure_uuid": "p-alice",
        "source": "openalex",
        "external_id": "a-alice",
        "status": "rejected",
        "changed_by": "sam",
        "note": "namesake, not her",
    }
    r = await admin_client.put("/api/v1/admin/author-identities", headers=headers, json=body)
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    await admin_client.put("/api/v1/admin/author-identities", headers=headers, json=body)

    await resolve_author_ids(db, inst, run_sweeps=False)  # evidence cannot resurrect it
    await db.commit()
    db.expire_all()  # the flip committed in the client's session, not this one
    rows = await _identity_rows(db)
    assert rows[("p-alice", "a-alice")].status == "rejected"
    assert rows[("p-alice", "a-alice2")].status == "confirmed"  # never silently demoted
    changes = (
        (
            await db.execute(
                select(StatusChangeLog).where(StatusChangeLog.table_name == "author_identities")
            )
        )
        .scalars()
        .all()
    )
    assert len(changes) == 1
    assert (changes[0].old_value, changes[0].new_value, changes[0].changed_by) == (
        "confirmed",
        "rejected",
        "sam",
    )
    assert changes[0].row_key["external_id"] == "a-alice"


@requires_db
async def test_cascade_rung_decisions_as_stored_rows(db, institution_factory):
    """One decision table over the match rungs, read off the identity rows
    the resolve pass stores (never through the private match helpers)."""
    inst = await _identity_fixture(db, institution_factory)
    await resolve_author_ids(db, inst, run_sweeps=False)
    await db.commit()
    cases = [
        ("p-orcid", "a-orcid", "orcid-exact", "confirmed"),
        ("p-name", "a-name", "name-exact", "confirmed"),
        ("p-init", "a-init", "name-initials", "confirmed"),
        ("p-family", "a-family", "family-unique", "confirmed"),
        # The weakest rung always lands as candidate, zero conflicts or not.
        ("p-fuzzy", "a-fuzzy", "name-fuzzy-strict", "candidate"),
    ]
    wanted = {uuid for uuid, *_rest in cases} | {"p-wang", "p-ambig"}
    by_uuid = {
        r.author_pure_uuid: r
        for r in (await db.execute(select(AuthorIdentity))).scalars()
        if r.author_pure_uuid in wanted
    }
    for uuid, aid, method, status in cases:
        row = by_uuid.get(uuid)
        assert row is not None, uuid
        assert (row.external_id, row.method, row.status) == (aid, method, status), uuid
    assert by_uuid["p-orcid"].orcid_corroborated is True
    # CJK homonyms (family/fuzzy evidence must stay silent) and two
    # same-family same-initial entries (ambiguous) store no row at all.
    assert "p-wang" not in by_uuid and "p-ambig" not in by_uuid


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        (
            {
                "pid": {
                    "id": {"scheme": "orcid_pending", "value": f"https://orcid.org/{ORCID_ALICE}"}
                }
            },
            None,
        ),
        ({"pid": {"id": {"scheme": "orcid", "value": ORCID_ALICE}}}, ORCID_ALICE),
        ({"pid": {"id": {"value": ORCID_ALICE}}}, ORCID_ALICE),
        ({"pid": None}, None),
        ({"fullName": "No Pid"}, None),
        ({"pid": {"id": {"scheme": "orcid", "value": ""}}}, None),
    ],
    ids=["pending-ignored", "confirmed-kept", "schemeless-kept", "no-pid", "no-entry", "empty"],
)
def test_openaire_pid_rules(entry, expected):
    assert openaire_author_orcid(entry) == expected


@requires_db
async def test_local_roster_identity_edges_roundtrip(db, institution_factory):
    inst = await _identity_fixture(db, institution_factory)
    await resolve_author_ids(db, inst, run_sweeps=False)
    await db.commit()
    data = await fetch_local_source(db, inst)

    # Carol never resolves; gina/karl ride the weak rung's confirmed
    # identities in place of org closure; the rung-case persons are all
    # dept-rostered regardless of whether a rung matched them.
    assert {a["pure_uuid"] for a in data.authors} == {
        "p-alice",
        "p-ambig",
        "p-bob",
        "p-dave",
        "p-eve",
        "p-family",
        "p-frank",
        "p-fuzzy",
        "p-gina",
        "p-init",
        "p-karl",
        "p-name",
        "p-orcid",
        "p-wang",
    }
    by_uuid = {a["pure_uuid"]: a for a in data.authors}
    alice = by_uuid["p-alice"]
    assert alice["openalex_author_id"] == "a-alice"  # confirmed rows only
    assert alice["openalex_alt_ids"] == ["a-alice2"]
    assert alice["orcid"] == ORCID_ALICE
    assert by_uuid["p-eve"]["openalex_author_id"] is None  # candidates are not facts
    assert by_uuid["p-eve"]["openalex_alt_ids"] == []
    assert by_uuid["p-frank"]["openalex_author_id"] == "A-frank"
    # The openaire namespace never leaks into the openalex id list.
    assert all("::" not in (a["openalex_author_id"] or "") for a in data.authors)
    assert data.org_rors.get("root") == "006hf6230"

    oa_edges = set(data.edges)
    assert ("a-alice", "w1") in oa_edges and ("a-alice2", "w2") in oa_edges
    # Store facts ride along even where the rung declined the identity.
    assert ("a-mary", "w17") in oa_edges and ("a-carol", "w3") in oa_edges
    assert all(aid == aid.lower() for aid, _work in oa_edges)

    stats = await ingest_authors(db, inst.id, data, inst.ror)
    await db.commit()
    assert stats["authors"] == 14
    assert stats["confirmed"] == 12  # everyone dept-rostered; the weak rung is not HR evidence
    authors = {r.pure_uuid: r for r in (await db.execute(select(Author))).scalars()}
    assert authors["p-alice"].openalex_ids == ["a-alice", "a-alice2"]
    assert authors["p-alice"].confirmed is True and authors["p-alice"].n_works == 2
    assert authors["p-eve"].openalex_ids == []
    assert authors["p-gina"].openalex_ids == ["a-gina", "a-gina2"]
    assert authors["p-gina"].confirmed is False
    assert authors["p-frank"].openalex_ids == ["a-frank"]
    assert authors["p-karl"].openalex_ids == ["a-karl"]


async def _profile_fixture(db, institution_factory):
    ut = await institution_factory(code="ut")
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()
    db.add_all([journal_factory("1234-5678"), journal_factory("2222-2221")])
    await db.flush()
    db.add_all(
        [
            JournalFlags(
                institution_id=ut.id,
                issn_l="1234-5678",
                works_count=3,
                works_window_plus=10,
                deal_covered=True,
            ),
            JournalFlags(
                institution_id=ut.id, issn_l="2222-2221", works_count=1, works_window_plus=5
            ),
        ]
    )

    def _work(uuid, year, issn, oa, doi=None):
        return Work(
            institution_id=ut.id,
            pure_uuid=uuid,
            title=f"Work {uuid}",
            norm_title=f"work {uuid}",
            year=year,
            oa_status=oa,
            doi_normalized=doi,
            journal_issn_l=issn,
            first_seen_run=run.id,
            last_seen_run=run.id,
        )

    db.add_all(
        [
            _work("w-2024", 2024, "1234-5678", "hybrid", doi="10.1000/local"),
            _work("w-2023a", 2023, "1234-5678", "gold"),
            _work("w-2023b", 2023, "2222-2221", "closed"),
            _work("w-2021", 2021, "1234-5678", "diamond"),
        ]
    )
    db.add(
        Author(
            institution_id=ut.id,
            pure_uuid="alice-uuid",
            name="Alice Author",
            orcid="0000-0002-1111",
            faculty=TNW,
            research_group="Quantum Transport in Matter",
            orgs=["Quantum Transport in Matter", "University of Twente"],
            n_works=4,
            confirmed=True,
            last_pub_year=2024,
            primary_topic="Physics",
            openalex_author_id="a5038098443",
        )
    )
    await db.flush()
    db.add_all(
        [
            AuthorWork(institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid=w)
            for w in ("w-2024", "w-2023a", "w-2023b", "w-2021")
        ]
    )
    await db.commit()
    return ut


@requires_db
async def test_author_profile_merges_openalex_only(client, db, institution_factory, monkeypatch):
    await _profile_fixture(db, institution_factory)

    async def _fake(_session, _institution, _author):
        return [
            # Duplicate of local w-2024 by DOI (prefix noise on purpose).
            {
                "title": "Dup",
                "year": 2024,
                "doi": "https://doi.org/10.1000/LOCAL",
                "oa_status": "gold",
                "work_type": "article",
                "venue_name": None,
                "issn_l": None,
            },
            {
                "title": "Old",
                "year": 1999,
                "doi": "10.1000/old",
                "oa_status": "closed",
                "work_type": "article",
                "venue_name": None,
                "issn_l": None,
            },  # out of window
            {
                "title": "Pre",
                "year": 2021,
                "doi": None,
                "oa_status": None,
                "work_type": "preprint",
                "venue_name": None,
                "issn_l": None,
            },  # excluded type
            {
                "title": "Only OA",
                "year": 2022,
                "doi": "10.1000/oa-only",
                "oa_status": None,
                "work_type": None,
                "venue_name": "Outside Journal",
                "issn_l": "9999-9991",
            },
            {
                "title": "No Doi",
                "year": 2020,
                "doi": None,
                "oa_status": "green",
                "work_type": "article",
                "venue_name": None,
                "issn_l": None,
            },
        ]

    monkeypatch.setattr("journal_browser.services.authors.openalex_only_works_for_author", _fake)
    r = await client.get("/api/v1/ut/authors/alice-uuid")
    assert r.status_code == 200
    body = r.json()
    assert body["author"]["n_works"] == 4
    assert body["author"]["orgs"] == ["Quantum Transport in Matter", "University of Twente"]
    # Derived work counts: year buckets over the stored edges only.
    assert [row["year"] for row in body["oa_by_year"]] == [2024, 2023, 2021]
    assert body["oa_by_year"][1] == {
        "year": 2023,
        "total": 2,
        "gold": 1,
        "green": 0,
        "hybrid": 0,
        "bronze": 0,
        "closed": 1,
        "diamond": 0,
    }
    # Derived venue authorship counts: works per journal, count desc.
    assert [(j["issn_l"], j["n_works"], j["oa_type"]) for j in body["journals"]] == [
        ("1234-5678", 3, "hybrid"),
        ("2222-2221", 1, "subscription"),
    ]
    assert [w["pure_uuid"] for w in body["works"]] == ["w-2024", "w-2023a", "w-2023b", "w-2021"]
    source = {w["pure_uuid"]: w["oa_status_source"] for w in body["works"]}
    # DOI-less oa_status is Pure's own access flag, never OpenAlex-synced.
    assert source["w-2024"] == "openalex" and source["w-2023a"] == "pure"

    section = body["openalex_only"]
    assert section["available"] is True and section["total"] == 2
    assert body["openalex_only_count"] == 2 and section["likely_missing"] == 2
    assert [(w["title"], w["doi"]) for w in section["items"]] == [
        ("Only OA", "10.1000/oa-only"),
        ("No Doi", None),
    ]
    missed = section["items"][0]
    assert missed["in_pure"] is False and missed["pure_uuid"] is None
    assert missed["oa_status"] == "unknown" and missed["ut_authors"] == []
    assert missed["journal_title"] == "Outside Journal" and missed["openalex_url"] is None
    assert (await client.get("/api/v1/ut/authors/nobody")).status_code == 404


@requires_db
async def test_gap_tags_and_authorship_counts_as_served(client, db, institution_factory):
    ut = await institution_factory(code="ut", research_portal_url="https://pure.example.com")
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    db.add(journal_factory("1234-5678", publisher_name="Publisher One"))
    await db.flush()

    def _work(uuid, year, title, *, doi=None, oa="closed", work_type="article", issn="1234-5678"):
        return Work(
            institution_id=ut.id,
            pure_uuid=uuid,
            title=title,
            norm_title=_norm_title(title),
            year=year,
            doi_normalized=doi,
            oa_status=oa,
            work_type=work_type,
            journal_issn_l=issn,
            first_seen_run=run.id,
            last_seen_run=run.id,
        )

    db.add_all(
        [
            _work("book1", 2026, "Eco Anxiety The Book", doi=BOOK_DOI, work_type="book", issn=None),
            _work("dup1", 2023, "Innovation Ethics", doi="10.10.0/other", issn=None),
            _work("held", 2023, "Held Pure Record", doi=HELD_DOI),
            _work("green1", 2022, "Green No Doi", oa="green"),
            _work("local1", 2024, "Local Doi", doi="10.10.0/local"),
        ]
    )
    await db.flush()
    db.add_all(
        [
            Author(
                institution_id=ut.id,
                pure_uuid="alice-uuid",
                name="Alice Author",
                openalex_ids=["a-alice"],
                n_works=2,
                confirmed=True,
                faculty=TNW,
                research_group="Group X",
            ),
            Author(
                institution_id=ut.id,
                pure_uuid="bob-uuid",
                name="Bob Author",
                openalex_ids=["a-bob"],
                n_works=1,
                confirmed=True,
                faculty=TNW,
                research_group="Group Y",
            ),
            # Books keep their Pure author edge even though harvest drops
            # the author_works edge (that is why the merge is needed).
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="book1", person_uuid="alice-uuid"),
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="dup1", person_uuid="alice-uuid"),
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="held", person_uuid="bob-uuid"),
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="green1", person_uuid="alice-uuid"),
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="local1", person_uuid="alice-uuid"),
            AuthorWork(
                institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid="green1"
            ),
            AuthorWork(
                institution_id=ut.id, author_pure_uuid="alice-uuid", work_pure_uuid="local1"
            ),
        ]
    )

    def _oa(w_id, title, year, doi, work_type="bookchapter"):
        return OpenalexWork(
            institution_id=ut.id,
            w_id=w_id,
            doi_normalized=doi,
            title=title,
            year=year,
            work_type=work_type,
            oa_status="gold",
            venue_issn_l="1234-5678",
            venue_name="Journal One",
            authorships=[{"a": "A-ALICE"}],
            source="works_stats",
        )

    store = [
        _oa("W-chapter", "Eco Anxiety Chapter Four", 2026, CHAPTER_DOI),
        _oa("W-ox", "Innovation: Ethics!", 2023, SAME_TITLE_DOI, work_type="article"),
        _oa("W-held", "Held Copy", 2023, HELD_DOI, work_type="article"),
        _oa("W-miss", "Truly Missing", 2025, MISSING_DOI, work_type="article"),
    ]
    db.add_all(store)
    db.add_all(pair_rows(*store))
    await db.commit()

    def _portal(uuid):
        return f"https://pure.example.com/en/publications/{uuid}"

    body = (await client.get("/api/v1/ut/authors/alice-uuid")).json()
    section = body["openalex_only"]
    assert section["total"] == 4 and section["likely_missing"] == 1
    assert [(w["title"], w["pure_match"], w["pure_match_url"]) for w in section["items"]] == [
        ("Eco Anxiety Chapter Four", "parent_book_in_pure", _portal("book1")),
        ("Truly Missing", None, None),
        ("Held Copy", "doi_in_pure", _portal("held")),
        ("Innovation: Ethics!", "same_title_in_pure", _portal("dup1")),
    ]
    # The Pure book rides in the works list but stays out of every count.
    assert [w["pure_uuid"] for w in body["works"]] == ["book1", "local1", "green1"]
    assert body["works"][0]["work_type"] == "book" and body["works"][0]["in_pure"] is True
    assert body["author"]["n_works"] == 2
    assert all(row["year"] != 2026 for row in body["oa_by_year"])
    oa_source = {w["pure_uuid"]: w["oa_status_source"] for w in body["works"]}
    assert oa_source["green1"] == "pure" and oa_source["local1"] == "openalex"

    detail = (await client.get("/api/v1/ut/journals/1234-5678")).json()
    assert detail["ut_authorship"]["n_ut_works"] == 3  # local1 + green1 + held
    assert detail["ut_authorship"]["faculties"] == [{"name": TNW, "works": 3}]
    assert detail["ut_authorship"]["research_groups"] == [
        {"name": "Group X", "works": 2},
        {"name": "Group Y", "works": 1},
    ]
    assert [(a["name"], a["works"]) for a in detail["ut_authorship"]["top_authors"]] == [
        ("Alice Author", 2),
        ("Bob Author", 1),
    ]
    venue_gaps = detail["openalex_only"]
    assert venue_gaps["total"] == 3  # the held DOI anti-joins out entirely
    assert [w["title"] for w in venue_gaps["items"]] == [
        "Eco Anxiety Chapter Four",
        "Truly Missing",
        "Innovation: Ethics!",
    ]

    payload = await authorship.author_ids_openalex_only(db, ut, [["a-alice"]])
    assert payload["total"] == 3
    assert [(w["title"], w["pure_match"]) for w in payload["items"]] == [
        ("Eco Anxiety Chapter Four", "parent_book_in_pure"),
        ("Truly Missing", None),
        ("Innovation: Ethics!", "same_title_in_pure"),
    ]
    # Faculty-sized id sets ride one text[] param: past asyncpg's 32,767
    # bind ceiling the card still answers instead of 500-ing.
    big = ["a-alice"] + [f"a-filler-{i}" for i in range(40_000)]
    assert (await authorship.author_ids_openalex_only(db, ut, big))["total"] == 3


def _listing(org_slug, unit_kind, persons):
    return {
        "faculty": org_slug,
        "unit_kind": unit_kind,
        "org_slug": org_slug,
        "listing_url": f"https://research.utwente.nl/en/organisations/{org_slug}/persons/",
        "pages": 1,
        "person_count": len(persons),
        "persons": persons,
    }


@requires_db
async def test_portal_person_bindings(db, institution_factory):
    """The binding table: name match, ORCID-resolved twins, ambiguous
    persons and org names skipped, full-replace, listings stored, rerun
    idempotent."""
    inst = await institution_factory(code="ut", name="University of Twente", ror=UT_ROR)
    db.add_all(
        [
            PureOrg(institution_id=inst.id, uuid="ut-root", name="University of Twente"),
            PureOrg(institution_id=inst.id, uuid="eemcs-uuid", name=EEMCS, org_type="faculty"),
            PureOrg(
                institution_id=inst.id,
                uuid="dept-uuid",
                name="Department of Environmental Resources",
            ),
            PureOrg(institution_id=inst.id, uuid="mesa-uuid", name=MESA, org_type="institute"),
            # Portal duplicate-name twins: ambiguous, never matched.
            PureOrg(institution_id=inst.id, uuid="bme-2", name="Biomechanical Engineering"),
            PureOrg(institution_id=inst.id, uuid="bme-3", name="Biomechanical Engineering"),
            PureOrgParent(institution_id=inst.id, org_uuid="dept-uuid", parent_uuid="eemcs-uuid"),
            PureOrgParent(institution_id=inst.id, org_uuid="mesa-uuid", parent_uuid="ut-root"),
            PurePerson(
                institution_id=inst.id,
                uuid="p-angela",
                name="Angela Abascal",
                payload={"cerif": {}},
            ),
            PurePerson(
                institution_id=inst.id, uuid="p-kai-1", name="Kai Wang", payload={"cerif": {}}
            ),
            PurePerson(
                institution_id=inst.id,
                uuid="p-kai-2",
                name="Kai Wang",
                orcid=KAI_ORCID,
                payload={"cerif": {}},
            ),
            PurePerson(
                institution_id=inst.id, uuid="p-yan-1", name="Yan Zhao", payload={"cerif": {}}
            ),
            PurePerson(
                institution_id=inst.id, uuid="p-yan-2", name="Yan Zhao", payload={"cerif": {}}
            ),
        ]
    )
    await db.flush()

    def _person(slug, name, *orgs, type_="Person: Academic"):
        return {
            "slug": slug,
            "name": name,
            "orgs": [
                {"slug": org_slug, "name": org_name, "role": role}
                for org_slug, org_name, role in orgs
            ],
            "type": type_,
        }

    listings = [
        parse_listing(
            _listing(
                "faculty-of-eemcs",
                "faculty",
                [
                    _person(
                        "angela-abascal",
                        "Angela Abascal",
                        (
                            "department-of-environmental-resources",
                            "Department of Environmental Resources",
                            "Researcher",
                        ),
                        ("biomechanical-engineering-2", "Biomechanical Engineering", None),
                        ("nowhere-lab", "Nowhere Lab", None),
                    ),
                    _person(
                        "kai-wang",
                        "Kai Wang",
                        (
                            "department-of-environmental-resources",
                            "Department of Environmental Resources",
                            "PhD Candidate",
                        ),
                    ),
                    _person(
                        "yan-zhao-2",
                        "Yan Zhao",
                        (
                            "department-of-environmental-resources",
                            "Department of Environmental Resources",
                            None,
                        ),
                        type_=None,
                    ),
                ],
            )
        ),
        parse_listing(
            _listing(
                "mesa-institute-2",
                "institute",
                [
                    _person(
                        "angela-abascal",
                        "Angela Abascal",
                        ("mesa-institute-2", MESA, "Researcher"),
                    ),
                    _person(
                        "kai-wang",
                        "Kai Wang",
                        (
                            "department-of-environmental-resources",
                            "Department of Environmental Resources",
                            None,
                        ),
                    ),
                ],
            )
        ),
    ]
    orcid_by_slug = {"kai-wang": KAI_ORCID}

    ingest = IngestSession(db)
    await ingest.start_run("pure-portal", "persons", "inst:ut", {"test": "bindings"})
    stats = await apply_person_bindings(db, inst, listings, ingest, orcid_by_slug=orcid_by_slug)
    await ingest.commit()

    assert stats["person_records"] == 5
    assert stats["persons_matched"] == 2  # Angela + Kai (ORCID resolves the twins)
    assert stats["orcid_resolved"] == 1
    assert stats["persons_ambiguous"] == 1  # Yan Zhao, no ORCID anywhere
    assert stats["persons_unmatched"] == 0
    assert stats["org_ambiguous"] == 1  # Biomechanical Engineering twins
    assert stats["org_unmatched"] == 1  # Nowhere Lab
    assert stats["edges"] == 3
    rows = {
        (row.person_uuid, row.org_uuid): row
        for row in (await db.execute(select(PurePersonOrg))).scalars()
    }
    assert set(rows) == {
        ("p-angela", "dept-uuid"),
        ("p-angela", "mesa-uuid"),
        ("p-kai-2", "dept-uuid"),
    }
    assert rows[("p-angela", "dept-uuid")].listing_kinds == ["faculty"]
    assert rows[("p-angela", "mesa-uuid")].listing_kinds == ["institute"]
    assert rows[("p-angela", "mesa-uuid")].role == "Researcher"
    assert rows[("p-kai-2", "dept-uuid")].portal_org_slug == "department-of-environmental-resources"
    stored = (
        (
            await db.execute(
                select(SourceRecord).where(
                    SourceRecord.source == "pure-portal", SourceRecord.entity_type == "persons"
                )
            )
        )
        .scalars()
        .all()
    )
    assert {r.source_pk for r in stored} == {"faculty-of-eemcs", "mesa-institute-2"}

    # Full-replace idempotency: same edges, no new source_record versions.
    ingest2 = IngestSession(db)
    await ingest2.start_run("pure-portal", "persons", "inst:ut", {"test": "bindings-2"})
    stats2 = await apply_person_bindings(db, inst, listings, ingest2, orcid_by_slug=orcid_by_slug)
    await ingest2.commit()
    assert stats2["edges"] == 3 and stats2["orcid_resolved"] == 1
    again = (
        (
            await db.execute(
                select(SourceRecord).where(
                    SourceRecord.source == "pure-portal", SourceRecord.entity_type == "persons"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(again) == len(stored)


@pytest.mark.parametrize(
    ("tile_name", "tier"),
    [
        ("Jong, Jan de", 2),  # exact key, both token orders
        ("de Jong, Jan", 2),
        ("Jong, J.J. de (Jan)", 1),  # initials tier; the common name confirms
        ("Jong, J.M. de", 1),  # tiles may carry middle initials the roster lacks
        ("Jong, J.J. de (Joke)", 0),  # the common name names someone else
        ("Jansen, J.J. de", 0),  # wrong surname
        ("Jong, T. de", 0),  # wrong initials
    ],
)
def test_people_utwente_name_tiers(tile_name, tier):
    tile = {"name_clean": tile_clean_name(tile_name), "common_name": tile_common_name(tile_name)}
    assert name_match_tier("jan de jong", "de jong jan", tile) == tier
