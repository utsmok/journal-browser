"""Publication-record mining into the Pure entity rebuilds: mined persons
and orgs land insert-if-absent after the set-derived rows, the origin
"publication" payload marker, set-derived wins on uuid collision, and
re-runs are idempotent."""

from sqlalchemy import select

from conftest import requires_db
from journal_browser.harvest.pure.entities import (
    mine_publication_entities,
    rebuild_pure_orgs,
    rebuild_pure_persons,
)
from journal_browser.models import HarvestRun, PureOrg, PurePerson, SourceRecord

AUTHOR_UT = "openaire_cris_persons/p-ut"
AUTHOR_EXT = "openaire_cris_persons/p-ext"
ORG_EEMCS = "openaire_cris_orgunits/o-eemcs"
ORG_EXT = "openaire_cris_orgunits/o-ext"

PUB_XML = (
    "<Publication>"
    "<Authors>"
    # UT-tree author: relative @id forms, as the live stream delivers them.
    "<Author>"
    f'<Person id="{AUTHOR_UT}">'
    "<PersonName><FamilyNames>Jansen</FamilyNames><FirstNames>Piet</FirstNames></PersonName>"
    "</Person>"
    f'<Affiliation><OrgUnit id="{ORG_EEMCS}"><Name>EEMCS</Name></OrgUnit></Affiliation>'
    "</Author>"
    # External author with their own org.
    "<Author>"
    f'<Person id="{AUTHOR_EXT}">'
    "<PersonName><FamilyNames>Smith</FamilyNames><FirstNames>Jane</FirstNames></PersonName>"
    "</Person>"
    f'<Affiliation><OrgUnit id="{ORG_EXT}"><Name>External Institute</Name></OrgUnit></Affiliation>'
    "</Author>"
    # No person id, org ref without an id: both must be skipped silently.
    "<Author>"
    "<Person>"
    "<PersonName><FamilyNames>Nobody</FamilyNames><FirstNames>NF</FirstNames></PersonName>"
    "</Person>"
    "<Affiliation><OrgUnit><Name>Id-less Org</Name></OrgUnit></Affiliation>"
    "</Author>"
    "</Authors>"
    "</Publication>"
)

# Set-derived person record whose uuid collides with the mined UT author.
PERSON_XML = (
    f'<Person id="{AUTHOR_UT}">'
    "<PersonName><FamilyNames>Jansen</FamilyNames><FirstNames>Piet J.</FirstNames></PersonName>"
    "<ORCID>https://orcid.org/0000-0002-1825-0097</ORCID>"
    f'<Affiliation><OrgUnit id="{ORG_EEMCS}"><Name>EEMCS</Name></OrgUnit></Affiliation>'
    "</Person>"
)


async def _seed_run(db, inst):
    run = HarvestRun(
        source="pure",
        entity_type="persons",
        institution_id=inst.id,
        config_fingerprint="test",
    )
    db.add(run)
    await db.flush()
    return run


async def _seed_records(db, run):
    db.add_all(
        [
            SourceRecord(
                source="pure",
                entity_type="work_cerif",
                source_pk="oai:ris.utwente.nl:publications/pub-1",
                payload={"metadata_xml": PUB_XML},
                content_hash="h-pub-1",
                harvest_run_id=run.id,
            ),
            SourceRecord(
                source="pure",
                entity_type="persons",
                source_pk=AUTHOR_UT,
                payload={"metadata_xml": PERSON_XML},
                content_hash="h-person-ut",
                harvest_run_id=run.id,
            ),
        ]
    )
    await db.flush()


@requires_db
async def test_mining_rebuild_contract(db, institution_factory):
    """Mined rows insert with the origin marker and parse_cerif_person
    payload shape; the set-derived row wins the uuid collision; re-running
    the miner + rebuilds changes nothing (full-replace + insert-if-absent)."""
    inst = await institution_factory(code="ut", name="University of Twente")
    run = await _seed_run(db, inst)
    await _seed_records(db, run)

    org_candidates, person_candidates = await mine_publication_entities(db, inst.id)
    # Id-less person and id-less org skipped; relative ids normalized.
    assert set(org_candidates) == {"o-eemcs", "o-ext"}
    assert set(person_candidates) == {"p-ut", "p-ext"}

    org_stats = await rebuild_pure_orgs(db, inst.id, mined=org_candidates)
    assert org_stats == {"orgs": 0, "parents": 0, "mined_orgs": 2, "parse_failures": 0}
    person_stats = await rebuild_pure_persons(db, inst.id, mined=person_candidates)
    assert person_stats == {"persons": 1, "mined_persons": 1, "parse_failures": 0}

    orgs = {
        row.uuid: (row.name, row.org_type, row.identifiers)
        for row in (await db.execute(select(PureOrg))).scalars()
    }
    assert orgs == {
        "o-eemcs": ("EEMCS", None, []),
        "o-ext": ("External Institute", None, []),
    }

    persons = {row.uuid: row for row in (await db.execute(select(PurePerson))).scalars()}
    assert set(persons) == {"p-ut", "p-ext"}
    # Set-derived row: verbatim CERIF payload, no origin marker, orcid set.
    set_row = persons["p-ut"]
    assert set_row.orcid == "0000-0002-1825-0097"
    assert set_row.name == "Piet J. Jansen"
    assert set(set_row.payload) == {"cerif"}
    assert set_row.payload["cerif"]["first_names"] == "Piet J."
    # Mined row: origin marker, full parse_cerif_person key set, orcid None.
    mined_row = persons["p-ext"]
    assert mined_row.orcid is None
    assert mined_row.name == "Jane Smith"
    assert set(mined_row.payload) == {"cerif", "origin"}
    assert mined_row.payload["origin"] == "publication"
    assert set(mined_row.payload["cerif"]) == {
        "id",
        "family_names",
        "first_names",
        "orcid",
        "scopus_author_id",
        "researcher_id",
        "affiliations",
    }
    assert mined_row.payload["cerif"]["affiliations"] == [
        {"affiliation_id": "o-ext", "affiliation_name": "External Institute"}
    ]

    # Second run: same stats and same rows (modulo updated_at).
    org_candidates2, person_candidates2 = await mine_publication_entities(db, inst.id)
    org_stats2 = await rebuild_pure_orgs(db, inst.id, mined=org_candidates2)
    person_stats2 = await rebuild_pure_persons(db, inst.id, mined=person_candidates2)
    assert org_stats2 == org_stats
    assert person_stats2 == person_stats
    persons2 = {
        row.uuid: (row.orcid, row.name, row.payload)
        for row in (await db.execute(select(PurePerson))).scalars()
    }
    assert persons2 == {u: (r.orcid, r.name, r.payload) for u, r in persons.items()}
    orgs2 = {
        row.uuid: (row.name, row.org_type, row.identifiers)
        for row in (await db.execute(select(PureOrg))).scalars()
    }
    assert orgs2 == orgs


@requires_db
async def test_rebuilds_without_mined_unchanged(db, institution_factory):
    """The default (no candidates) keeps the old full-replace behavior."""
    inst = await institution_factory(code="ut2", name="University of Twente 2")
    run = await _seed_run(db, inst)
    await _seed_records(db, run)
    org_stats = await rebuild_pure_orgs(db, inst.id)
    person_stats = await rebuild_pure_persons(db, inst.id)
    assert org_stats["mined_orgs"] == 0
    assert person_stats["mined_persons"] == 0
    uuids = {row.uuid for row in (await db.execute(select(PurePerson))).scalars()}
    # Only the set-derived person; the mined external author is absent.
    assert uuids == {"p-ut"}
