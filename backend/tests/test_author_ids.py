"""Identity resolution (run_sweeps=False) and the local source adapter.

Fixtures port the ut-metadata cascade scenarios onto journal-browser's
own stores: org tree + pure persons + CERIF work authors + the
openalex_works projection, then assert rung outcomes, status policy,
and admin-flip stickiness.
"""

from sqlalchemy import select

from conftest import journal_factory, requires_db
from journal_browser.harvest.author_ids import resolve_author_ids
from journal_browser.models import (
    AuthorIdentity,
    HarvestRun,
    OpenalexWork,
    PureOrg,
    PureOrgParent,
    PurePerson,
    Work,
    WorkPureAuthor,
)

ORCID_ALICE = "0000-0002-1825-0097"


async def _fixture(db, institution_factory):
    """The shared scenario: UT org tree (root + science dept + partner),
    five persons, seven DOI-bearing works with CERIF author lists, and
    the matching openalex_works authorships.

    alice: orcid-exact on w1 (a-alice), initials-only on w2 (a-alice2).
    bob: name-exact on w1 + w3 (a-bob), profile-affiliated.
    carol: partner-university profile, no work-level affiliation —
    excluded from the roster gate.
    dave: partner profile but a w1 work-level affiliation — admitted via
    the work-level arm, name-exact on a-dave.
    eve: namesake competitor scenario — a-eve matched on w4, a-eve2 on
    w5 (with its own orcid), a-eve3 on w7 (different orcid); w6 lists
    a-eve and a-eve2 together, so a-eve2 co-occurs with the primary and
    stays a candidate; a-eve3 contradicts on orcid and stays too."""
    inst = await institution_factory(
        code="ut", name="University of Twente", ror="https://ror.org/006hf6230"
    )
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
            PureOrgParent(institution_id=inst.id, org_uuid="dept", parent_uuid="root"),
        ]
    )

    def _person(uuid, first, family, org_uuids, orcid=None):
        return PurePerson(
            institution_id=inst.id,
            uuid=uuid,
            orcid=orcid,
            name=f"{first} {family}",
            payload={
                "cerif": {
                    "first_names": first,
                    "family_names": family,
                    "affiliations": [{"affiliation_id": o} for o in org_uuids],
                }
            },
        )

    db.add_all(
        [
            _person("p-alice", "Alice", "Author", ["dept"], orcid=ORCID_ALICE),
            _person("p-bob", "Bob", "Builder", ["dept"]),
            _person("p-carol", "Carol", "Partner", ["partner"]),
            _person("p-dave", "Dave", "Worker", ["partner"]),
            _person("p-eve", "Eve", "Namesake", ["dept"]),
        ]
    )
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()

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

    db.add_all([_work("w1", "10.1000/w1"), _work("w2", "10.1000/w2"), _work("w3", "10.1000/w3")])
    db.add_all(
        [
            _work("w4", "10.1000/w4"),
            _work("w5", "10.1000/w5"),
            _work("w6", "10.1000/w6"),
            _work("w7", "10.1000/w7"),
        ]
    )
    db.add(journal_factory("1234-5678"))
    await db.flush()  # journal FK + works must exist before author edges

    def _cerif_author(work, person, first, family, affs):
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
            _cerif_author("w1", "p-alice", "Alice", "Author", ["dept"]),
            _cerif_author("w1", "p-bob", "Bob", "Builder", ["dept"]),
            _cerif_author("w1", "p-dave", "Dave", "Worker", ["dept"]),
            _cerif_author("w2", "p-alice", "A.", "Author", []),
            _cerif_author("w3", "p-bob", "Bob", "Builder", ["dept"]),
            _cerif_author("w3", "p-carol", "Carol", "Partner", []),
            _cerif_author("w4", "p-eve", "Eve", "Namesake", ["dept"]),
            _cerif_author("w5", "p-eve", "Eve", "Namesake", ["dept"]),
            _cerif_author("w6", "p-eve", "Eve", "Namesake", ["dept"]),
            _cerif_author("w7", "p-eve", "Eve", "Namesake", ["dept"]),
        ]
    )

    def _oa_work(w_id, doi, authorships):
        return OpenalexWork(
            institution_id=inst.id,
            w_id=w_id,
            doi_normalized=doi,
            title=f"OA {w_id}",
            year=2023,
            work_type="article",
            oa_status="gold",
            authorships=authorships,
        )

    db.add_all(
        [
            _oa_work(
                "W-a",
                "10.1000/w1",
                [
                    {"a": "a-alice", "n": "Alice Author", "o": ORCID_ALICE},
                    {"a": "a-bob", "n": "B. Builder", "o": None},
                    {"a": "a-dave", "n": "Dave Worker", "o": None},
                ],
            ),
            _oa_work(
                "W-b",
                "10.1000/w2",
                [{"a": "a-alice2", "n": "A. Author", "o": None}],
            ),
            _oa_work(
                "W-c",
                "10.1000/w3",
                [
                    {"a": "a-bob", "n": "Bob Builder", "o": None},
                    {"a": "a-carol", "n": "Carol Partner", "o": None},
                ],
            ),
            _oa_work(
                "W-d",
                "10.1000/w4",
                [{"a": "a-eve", "n": "Eve Namesake", "o": None}],
            ),
            _oa_work(
                "W-e",
                "10.1000/w5",
                [{"a": "a-eve2", "n": "Eve Namesake", "o": "0000-0009-0001-0001"}],
            ),
            _oa_work(
                "W-f",
                "10.1000/w6",
                [
                    {"a": "a-eve", "n": "Eve Namesake", "o": None},
                    {"a": "a-eve2", "n": "E. Namesake", "o": None},
                ],
            ),
            _oa_work(
                "W-g",
                "10.1000/w7",
                [{"a": "a-eve3", "n": "Eve Namesake", "o": "0000-0009-0002-0002"}],
            ),
        ]
    )
    await db.flush()
    return inst


@requires_db
async def test_resolve_statuses_and_gates(db, institution_factory):
    inst = await _fixture(db, institution_factory)
    stats = await resolve_author_ids(db, inst, run_sweeps=False)
    await db.commit()

    assert stats["matched"] == 4  # alice, bob, dave, eve
    # alice sees two ids across her works (a-alice + the a-alice2
    # fragmentation); eve matches three namesake profiles — the conflict
    # counter flags exactly those two.
    assert stats["conflicted_authors"] == 2
    rows = {
        (r.author_pure_uuid, r.external_id): r
        for r in (await db.execute(select(AuthorIdentity))).scalars()
    }
    # carol excluded by the org gate; her OpenAlex id never resolves
    assert all(uuid != "p-carol" for uuid, _aid in rows)
    assert ("p-carol", "a-carol") not in rows

    alice_primary = rows[("p-alice", "a-alice")]
    assert alice_primary.status == "confirmed"  # orcid-exact
    assert alice_primary.method == "orcid-exact"
    assert alice_primary.orcid_corroborated is True
    assert alice_primary.n_works == 1  # w1 only (w2's entry is another id)

    alice_alt = rows[("p-alice", "a-alice2")]
    assert alice_alt.status == "confirmed"  # twin: never co-occurs, no orcid clash
    assert alice_alt.method == "fragmentation"

    # eve's competing namesake profiles all stay in review
    eve_primary = rows[("p-eve", "a-eve")]
    assert eve_primary.status == "candidate"  # name-exact but conflicted
    eve_co = rows[("p-eve", "a-eve2")]
    assert eve_co.status == "candidate"  # co-occurs with the primary on w6
    assert eve_co.evidence.get("co_occurs_with_primary") is True
    assert rows[("p-eve", "a-eve3")].status == "candidate"  # orcid contradiction

    bob = rows[("p-bob", "a-bob")]
    assert bob.status == "confirmed"  # non-fuzzy (initials/name), zero conflict
    assert bob.n_works == 2  # w1 + w3

    dave = rows[("p-dave", "a-dave")]
    assert dave.status == "confirmed"  # admitted via the work-level arm


@requires_db
async def test_admin_flips_are_sticky(db, institution_factory):
    inst = await _fixture(db, institution_factory)
    db.add_all(
        [
            # admin rejected alice's orcid-exact id before this pass
            AuthorIdentity(
                institution_id=inst.id,
                author_pure_uuid="p-alice",
                source="openalex",
                external_id="a-alice",
                status="rejected",
            ),
            # admin confirmed the fragmentation candidate
            AuthorIdentity(
                institution_id=inst.id,
                author_pure_uuid="p-alice",
                source="openalex",
                external_id="a-alice2",
                status="confirmed",
            ),
        ]
    )
    await db.flush()
    await resolve_author_ids(db, inst, run_sweeps=False)
    await db.commit()
    rows = {
        r.external_id: r
        for r in (await db.execute(select(AuthorIdentity))).scalars()
        if r.author_pure_uuid == "p-alice"
    }
    assert rows["a-alice"].status == "rejected"  # evidence can't resurrect it
    assert rows["a-alice2"].status == "confirmed"  # never silently demoted
