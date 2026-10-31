"""Portal persons bind: name matching, the apply contract (gap-fill
evidence only, ambiguity skipped, ORCID-disambiguated twins, full
replace), and the portal derive arms."""

from sqlalchemy import select

from conftest import requires_db
from journal_browser.harvest.authors import (
    SourceData,
    augment_faculty,
    augment_institute,
    augment_research_group,
    derive_identity,
)
from journal_browser.harvest.pure_portal_persons import (
    apply_person_bindings,
    parse_listing,
    person_name_key,
    person_name_keys,
)
from journal_browser.ingest import IngestSession
from journal_browser.models import (
    PureOrg,
    PureOrgParent,
    PurePerson,
    PurePersonOrg,
    SourceRecord,
)

EEMCS = "Faculty of Electrical Engineering, Mathematics and Computer Science"
KAI_ORCID = "0009-0007-4912-4652"


def test_person_name_key():
    # Credential suffixes after a comma must not break the match.
    assert person_name_key("Geert A. Folkertsma, CEng") == person_name_key("Geert A. Folkertsma")
    assert person_name_key("Jan de Jong, PDEng") == person_name_key("jan de jong")
    # Diacritics fold; punctuation tokenizes.
    assert person_name_key("Céline Steenge") == person_name_key("celine steenge")
    assert person_name_key("Marjolein G.J. Brusse-Keizer") == person_name_key(
        "marjolein g j brusse keizer"
    )
    assert person_name_key(None) == ""
    # Token order is a separate key (Pure occasionally flips first/last).
    first, flipped = person_name_keys("Wouter M. den Breeijen")
    assert first == "wouter m den breeijen"
    assert flipped == "breeijen den m wouter"


def test_match_org_name_fallback_and_alias():
    """Org relations resolve via curated alias, exact name_key, or the
    prefix-stripped fallback; an ambiguous exact level stays ambiguous."""
    from journal_browser.harvest.pure_portal_persons import match_org_name

    candidates = {
        "departmentofgeoinformationprocessing": ["gip-uuid"],
        "geosciences": ["geosciences-uuid"],
        "bmslaboratory": ["bms-uuid"],
        "biomechanicalengineering": ["bme-2", "bme-3"],
    }
    bare = {"geoinformationprocessing": ["gip-uuid"], "geosciences": ["geosciences-uuid"]}
    aliases = {"BMS-LAB": "BMS - Laboratory"}

    # Exact match.
    assert match_org_name("Geosciences", aliases, candidates, bare) == ["geosciences-uuid"]
    # Prefix-stripped fallback: portal prefixes, OAI tree names bare.
    assert match_org_name("Department of Geosciences", aliases, candidates, bare) == [
        "geosciences-uuid"
    ]
    # Curated alias (comma/space variants the normalizer cannot bridge).
    assert match_org_name("BMS-LAB", aliases, candidates, bare) == ["bms-uuid"]
    # Ambiguous exact level: no fallback dodge.
    assert match_org_name("Biomechanical Engineering", aliases, candidates, bare) == [
        "bme-2",
        "bme-3",
    ]
    assert match_org_name("Nowhere Lab", aliases, candidates, bare) == []


def _listing(org_slug: str, unit_kind: str, persons: list[dict]) -> dict:
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
async def test_apply_person_bindings_contract(db, institution_factory):
    """Persons match by normalized name (ORCID resolves twins); ambiguous
    persons and org names are skipped; the table full-replaces; verbatim
    listings land in source_records; re-running is idempotent."""
    inst = await institution_factory(
        code="ut", name="University of Twente", ror="https://ror.org/006hf6230"
    )
    db.add_all(
        [
            PureOrg(institution_id=inst.id, uuid="ut-root", name="University of Twente"),
            PureOrg(institution_id=inst.id, uuid="eemcs-uuid", name=EEMCS, org_type="faculty"),
            PureOrg(
                institution_id=inst.id,
                uuid="dept-uuid",
                name="Department of Environmental Resources",
            ),
            PureOrg(
                institution_id=inst.id,
                uuid="mesa-uuid",
                name="MESA+ Institute",
                org_type="institute",
            ),
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

    listings = [
        parse_listing(
            _listing(
                "faculty-of-eemcs",
                "faculty",
                [
                    {
                        "slug": "angela-abascal",
                        "name": "Angela Abascal",
                        "orgs": [
                            {
                                "slug": "department-of-environmental-resources",
                                "name": "Department of Environmental Resources",
                                "role": "Researcher",
                            },
                            {
                                "slug": "biomechanical-engineering-2",
                                "name": "Biomechanical Engineering",
                                "role": None,
                            },
                            {"slug": "nowhere-lab", "name": "Nowhere Lab", "role": None},
                        ],
                        "type": "Person: Academic",
                    },
                    {
                        "slug": "kai-wang",
                        "name": "Kai Wang",
                        "orgs": [
                            {
                                "slug": "department-of-environmental-resources",
                                "name": "Department of Environmental Resources",
                                "role": "PhD Candidate",
                            }
                        ],
                        "type": "Person: Academic",
                    },
                    {
                        "slug": "yan-zhao-2",
                        "name": "Yan Zhao",
                        "orgs": [
                            {
                                "slug": "department-of-environmental-resources",
                                "name": "Department of Environmental Resources",
                                "role": None,
                            }
                        ],
                        "type": None,
                    },
                ],
            )
        ),
        parse_listing(
            _listing(
                "mesa-institute-2",
                "institute",
                [
                    {
                        "slug": "angela-abascal",
                        "name": "Angela Abascal",
                        "orgs": [
                            {
                                "slug": "mesa-institute-2",
                                "name": "MESA+ Institute",
                                "role": "Researcher",
                            }
                        ],
                        "type": "Person: Academic",
                    },
                    {
                        "slug": "kai-wang",
                        "name": "Kai Wang",
                        "orgs": [
                            {
                                "slug": "department-of-environmental-resources",
                                "name": "Department of Environmental Resources",
                                "role": None,
                            }
                        ],
                        "type": "Person: Academic",
                    },
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
    assert stats["persons_matched"] == 2  # Angela + Kai (ORCID-resolved)
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
                    SourceRecord.source == "pure-portal",
                    SourceRecord.entity_type == "persons",
                )
            )
        )
        .scalars()
        .all()
    )
    assert {r.source_pk for r in stored} == {"faculty-of-eemcs", "mesa-institute-2"}

    # Full-replace idempotency: re-running the same dataset lands the
    # same three edges and no new source_record versions.
    ingest2 = IngestSession(db)
    await ingest2.start_run("pure-portal", "persons", "inst:ut", {"test": "bindings-2"})
    stats2 = await apply_person_bindings(db, inst, listings, ingest2, orcid_by_slug=orcid_by_slug)
    await ingest2.commit()
    assert stats2["edges"] == 3
    assert stats2["orcid_resolved"] == 1
    again = (
        (
            await db.execute(
                select(SourceRecord).where(
                    SourceRecord.source == "pure-portal",
                    SourceRecord.entity_type == "persons",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(again) == len(stored)


def _source_data() -> SourceData:
    """Hand-built SourceData: dept → EEMCS → root closure, MESA+ pinned
    to the root as an institute."""
    data = SourceData()
    data.orgs = {
        "root": ("root-uuid", "University of Twente"),
        "eemcs": ("eemcs-uuid", EEMCS),
        "dept": ("dept-uuid", "Department of Environmental Resources"),
        "mesa": ("mesa-uuid", "MESA+ Institute"),
    }
    data.tree = {
        "root": [(0, "root")],
        "eemcs": [(0, "eemcs"), (1, "root")],
        "dept": [(0, "dept"), (1, "eemcs"), (2, "root")],
        "mesa": [(0, "mesa"), (1, "root")],
    }
    data.institute_orgs = {"mesa"}
    data.person_by_pure = {
        "p-native": "p-native",
        "p-empty": "p-empty",
        "p-institute-only": "p-institute-only",
    }
    data.person_orgs = {"p-native": ["dept"]}
    data.portal_person_orgs = {
        "p-native": ["mesa"],
        "p-empty": ["dept"],
        "p-institute-only": ["mesa"],
    }
    return data


def _author(uuid: str) -> dict:
    return {"pure_uuid": uuid}


def test_portal_arms_gap_fill_only():
    data = _source_data()

    # Native CERIF path resolves without ever seeing the portal arm.
    payload = {"cerif": {"affiliations": [{"affiliation_id": "dept-uuid"}]}}
    faculty, group, orgs = derive_identity(payload, data)
    assert faculty == EEMCS and group == "Department of Environmental Resources"
    assert orgs == ["Department of Environmental Resources"]

    # No native arms at all: the portal binding fills faculty + group.
    empty = _author("p-empty")
    assert augment_faculty(empty, data) == EEMCS
    assert augment_research_group(empty, data) == "Department of Environmental Resources"
    assert augment_institute(empty, data) is None

    # Institute-only member: the institute fills, faculty stays empty —
    # institute chains carry no faculty or group evidence.
    institute_only = _author("p-institute-only")
    assert augment_institute(institute_only, data) == "MESA+ Institute"
    assert augment_faculty(institute_only, data) is None
    assert augment_research_group(institute_only, data) is None

    # Native evidence still wins its own path: derive_identity (payload
    # only) is untouched by the portal arm — the portal can only fill
    # what the native path left empty.
    native = _author("p-native")
    assert augment_institute(native, data) == "MESA+ Institute"
    faculty, group, _orgs = derive_identity(payload, data)
    assert faculty == EEMCS and group == "Department of Environmental Resources"
