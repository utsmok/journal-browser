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
    SourceRecord,
    Work,
    WorkPureAuthor,
)

ORCID_ALICE = "0000-0002-1825-0097"
ORCID_FRANK = "0000-0002-4444-4444"
ORCID_GINA = "0000-0009-0003-0003"
ORCID_IVY = "0000-0009-0005-0005"
ORCID_J1 = "0000-0009-0006-0006"
ORCID_J2 = "0000-0009-0007-0007"
ORCID_KARL = "0000-0009-0008-0008"


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
    stays a candidate; a-eve3 contradicts on orcid and stays too.
    frank: profile-orcid person with no works — admitted via the
    orcid-direct listing join; eve's OpenAIRE authorship on w4 exercises
    the openaire cascade arm (namespace kept out of openalex_ids).
    Weak-affiliation rung scenarios (flat org "flat" has NO parent edge,
    so tree.resolves never closes for these persons): gina (name-exact,
    single orcid) and karl (name-initials, single orcid) are admitted;
    hank carries no orcid anywhere; jack's id appears with two different
    orcids across the store (merged/impostor profile); ivy1 and ivy2 are
    same-name persons whose works both select one shared id."""
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
            PureOrg(
                institution_id=inst.id,
                uuid="flat",
                name="Stochastic Operations Research",
                org_type="department",
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
            _person("p-frank", "Frank", "Listing", ["dept"], orcid=ORCID_FRANK),
            _person("p-gina", "Gina", "Flat", ["flat"]),
            _person("p-hank", "Hank", "Flat", ["flat"]),
            _person("p-ivy1", "Ivy", "Twin", ["flat"]),
            _person("p-ivy2", "Ivy", "Twin", ["flat"]),
            _person("p-jack", "Jack", "Flat", ["flat"]),
            _person("p-karl", "Karl", "Flat", ["flat"]),
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
            _work("w8", "10.1000/w8"),
            _work("w9", "10.1000/w9"),
            _work("w10", "10.1000/w10"),
            _work("w11", "10.1000/w11"),
            _work("w12", "10.1000/w12"),
            _work("w13", "10.1000/w13"),
            _work("w14", "10.1000/w14"),
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
            _cerif_author("w8", "p-gina", "Gina", "Flat", ["flat"]),
            _cerif_author("w9", "p-hank", "Hank", "Flat", ["flat"]),
            _cerif_author("w10", "p-ivy1", "Ivy", "Twin", ["flat"]),
            _cerif_author("w11", "p-ivy2", "Ivy", "Twin", ["flat"]),
            _cerif_author("w12", "p-jack", "Jack", "Flat", ["flat"]),
            _cerif_author("w13", "p-eve", "Eve", "Namesake", ["dept"]),
            _cerif_author("w14", "p-karl", "K.", "Flat", ["flat"]),
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
            _oa_work("W-h", "10.1000/w8", [{"a": "a-gina", "n": "Gina Flat", "o": ORCID_GINA}]),
            _oa_work("W-i", "10.1000/w9", [{"a": "a-hank", "n": "Hank Flat", "o": None}]),
            _oa_work("W-j", "10.1000/w10", [{"a": "a-ivy", "n": "Ivy Twin", "o": ORCID_IVY}]),
            _oa_work("W-k", "10.1000/w11", [{"a": "a-ivy", "n": "Ivy Twin", "o": ORCID_IVY}]),
            _oa_work("W-l", "10.1000/w12", [{"a": "a-jack", "n": "Jack Flat", "o": ORCID_J1}]),
            _oa_work(
                "W-m",
                "10.1000/w13",
                [
                    {"a": "a-eve", "n": "Eve Namesake", "o": None},
                    {"a": "a-jack", "n": "J. Flat", "o": ORCID_J2},
                ],
            ),
            _oa_work("W-n", "10.1000/w14", [{"a": "a-karl", "n": "Karl Flat", "o": ORCID_KARL}]),
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
            # OpenAIRE authorship of w4: orcid-backed person key, inverted name
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
            # author listing row carrying frank's own orcid
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
    # the openaire arm matched eve once on w4; frank rides the listing join
    assert stats["openaire"]["matched"] == 1
    assert stats["orcid_listing"] == 1
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

    # openaire arm: eve matched via the inverted-name initials form (the
    # raw name-exact rung compares display order, so "Namesake, Eve" runs
    # one rung down — deterministic either way), own namespace
    eve_oa = rows[("p-eve", "orcid_______::eve1")]
    assert eve_oa.status == "confirmed"
    assert eve_oa.source == "openaire"
    assert eve_oa.method == "name-initials"

    # orcid-direct: frank's listing profile carries his own orcid
    frank = rows[("p-frank", "A-frank")]
    assert frank.status == "confirmed"
    assert frank.method == "orcid-exact"
    assert frank.n_works == 0
    assert frank.evidence.get("source") == "author-listing"

    bob = rows[("p-bob", "a-bob")]
    assert bob.status == "confirmed"  # non-fuzzy (initials/name), zero conflict
    assert bob.n_works == 2  # w1 + w3

    dave = rows[("p-dave", "a-dave")]
    assert dave.status == "confirmed"  # admitted via the work-level arm


@requires_db
async def test_weak_affiliation_rung(db, institution_factory):
    """Org-dead-end persons: deterministic name + single consistent orcid
    admits; no orcid, merged-profile orcid clash, and namesake-shared ids
    stay out. Flat-org persons never enter the strong cascade."""
    inst = await _fixture(db, institution_factory)
    stats = await resolve_author_ids(db, inst, run_sweeps=False)
    await db.commit()

    # the rung never perturbs the work-anchored cascade
    assert stats["matched"] == 4
    assert stats["weak_affiliation"] == {
        "admitted": 2,
        "methods": {"name-exact": 1, "name-initials": 1},
        # carol (partner-org profile, no orcid) and hank both evaluated and
        # declined for missing orcid evidence
        "skipped_orcid_missing": 2,
        "skipped_orcid_mismatch": 1,
        "skipped_namesake_contested": 2,
    }

    rows = {
        (r.author_pure_uuid, r.external_id): r
        for r in (await db.execute(select(AuthorIdentity))).scalars()
    }
    gina = rows[("p-gina", "a-gina")]
    assert gina.status == "confirmed"
    assert gina.method == "name-exact"
    assert gina.orcid_corroborated is True
    assert gina.n_works == 1
    assert gina.evidence.get("weak_affiliation") is True
    assert gina.evidence.get("orcids") == [ORCID_GINA]

    karl = rows[("p-karl", "a-karl")]
    assert karl.status == "confirmed"  # initials-form evidence, same gate
    assert karl.method == "name-initials"

    # hank: no orcid anywhere; jack: the id carries two orcids across the
    # store; the ivys: one shared id selected by two same-name persons
    assert ("p-hank", "a-hank") not in rows
    assert ("p-jack", "a-jack") not in rows
    assert ("p-ivy1", "a-ivy") not in rows
    assert ("p-ivy2", "a-ivy") not in rows


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
