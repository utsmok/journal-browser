"""The Pure backend export import (work_cerif_full) and the publication-record
preference helper: full-author export versions beat the stream's truncated
work_cerif versions per uuid, scoped per institution, and the authorship
backfill + entity mining read through the helper."""

from jobs.backfill_pure_authors import backfill_pure_work_authors
from jobs.import_pure_export import import_pure_export
from sqlalchemy import select

from conftest import requires_db
from journal_browser.harvest.pure.cerif import publication_contributors
from journal_browser.harvest.pure.entities import (
    latest_publication_records,
    mine_publication_entities,
    parse_metadata_xml,
)
from journal_browser.models import HarvestRun, SourceRecord, Work, WorkPureAuthor

UUID_1 = "46a63e16-5680-45ff-a9a3-4edc78159aa7"
UUID_2 = "1b2e9d44-22c2-4a44-9e03-0d59c6611b3f"
UUID_3 = "5f3a1c02-8a41-4d3f-9d3e-2c2f55f57c10"
UUID_4 = "9e7b3a11-4f52-4c48-a2b6-7a1d0e9f6d21"

ORG_ONE = '<OrgUnit id="openaire_cris_orgunits/o-1"><Name>Org One</Name></OrgUnit>'
ORG_EXT = '<OrgUnit id="openaire_cris_orgunits/o-ext"><Name>External Institute</Name></OrgUnit>'


def _author(pid: str, family: str, first: str, org: str | None) -> str:
    org_xml = f"<Affiliation>{org}</Affiliation>" if org else ""
    return (
        f'<Author><Person id="{pid}"><PersonName>'
        f"<FamilyNames>{family}</FamilyNames><FirstNames>{first}</FirstNames>"
        f"</PersonName></Person>{org_xml}</Author>"
    )


AUTHOR_A = _author("openaire_cris_persons/p-a", "One", "Ann", ORG_ONE)
AUTHOR_B = _author("openaire_cris_persons/p-b", "Two", "Bob", None)
AUTHOR_EXT = _author("openaire_cris_persons/p-ext", "Ext", "Eve", ORG_EXT)

# Full-author export record: 3 authors with person ids (stream only kept 1).
FULL_XML = (
    '<Publication xmlns:cerif="https://www.openaire.eu/cerif-profile/1.2/">'
    '<cerif:Title xml:lang="en">Full-author work</cerif:Title>'
    "<DOI>10.1234/full.1</DOI>"
    f"<Authors>{AUTHOR_A}{AUTHOR_B}{AUTHOR_EXT}</Authors></Publication>"
)
# Stream-truncated version of the same work: one author with a person id.
STREAM_XML = f"<Publication><Authors>{AUTHOR_A}</Authors></Publication>"
# Minimal second record for the importer fixture.
MINIMAL_XML = (
    '<Publication xmlns:cerif="https://www.openaire.eu/cerif-profile/1.2/">'
    '<cerif:Title xml:lang="en">Second work</cerif:Title></Publication>'
)


def _export_xml(*records: tuple[str, str]) -> str:
    """OAI-PMH ListRecords wrapper around (bare uuid, metadata xml) records,
    mirroring the backend export file's shape."""
    body = "".join(
        f"<record><header><identifier>{uuid}</identifier>"
        "<datestamp>2026-10-30T14:21:46Z</datestamp>"
        "<setSpec>openaire_cris_publications</setSpec></header>"
        f"<metadata>{xml}</metadata></record>"
        for uuid, xml in records
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">'
        f"<ListRecords>{body}</ListRecords></OAI-PMH>"
    )


def _stream_pk(uuid: str) -> str:
    return f"oai:ris.utwente.nl:publications/{uuid}"


async def _seed_run(db, inst, entity_type):
    run = HarvestRun(
        source="pure", entity_type=entity_type, institution_id=inst.id, config_fingerprint="test"
    )
    db.add(run)
    await db.flush()
    return run


async def _seed_record(db, run, entity_type, pk, xml):
    db.add(
        SourceRecord(
            source="pure",
            entity_type=entity_type,
            source_pk=pk,
            payload={"metadata_xml": xml},
            content_hash=f"h-{pk}-{entity_type}",
            harvest_run_id=run.id,
        )
    )
    await db.flush()


@requires_db
async def test_import_pure_export_stores_full_versions(db, institution_factory, tmp_path):
    """Two export records store as work_cerif_full with the stream payload
    shape; the full-author list and DOI survive verbatim; a re-run stores
    nothing (content-hash dedupe)."""
    inst = await institution_factory(code="ut", name="University of Twente")
    file = tmp_path / "export.xml"
    file.write_text(_export_xml((UUID_1, FULL_XML), (UUID_2, MINIMAL_XML)))

    stats = await import_pure_export(db, file, inst)
    assert stats["records_seen"] == 2
    assert stats["records_stored"] == 2
    assert stats["parse_failures"] == 0

    stmt = select(SourceRecord).where(SourceRecord.entity_type == "work_cerif_full")
    rows = (await db.execute(stmt)).scalars().all()
    assert {r.source_pk for r in rows} == {UUID_1, UUID_2}
    full = next(r for r in rows if r.source_pk == UUID_1)
    # Mirrored stream payload shape (record_payload keys + cerif fields).
    assert {"oai_identifier", "datestamp", "set_specs", "metadata_xml", "dc", "cerif"} <= set(
        full.payload
    )
    assert full.payload["oai_identifier"] == UUID_1
    assert full.payload["dc"] == {}
    assert full.payload["cerif"]["doi"] == "10.1234/full.1"
    assert full.payload["doi_normalized"] == "10.1234/full.1"
    root = parse_metadata_xml(full.payload["metadata_xml"])
    assert root is not None
    authors = publication_contributors(root, "Author")
    assert len(authors) == 3
    assert authors[2]["affiliations"] == [
        {
            "affiliation_id": "openaire_cris_orgunits/o-ext",
            "affiliation_name": "External Institute",
        }
    ]

    stats2 = await import_pure_export(db, file, inst)
    assert stats2["records_seen"] == 2
    assert stats2["records_stored"] == 0


@requires_db
async def test_latest_publication_records_prefers_full(db, institution_factory):
    """Full versions win per uuid regardless of insert order, stream fills
    the uuids the export set lacks, and another institution's records are
    invisible."""
    inst_ut = await institution_factory(code="ut", name="University of Twente")
    inst_rug = await institution_factory(code="rug", name="RUG")
    run_full = await _seed_run(db, inst_ut, "work_cerif_full")
    run_stream = await _seed_run(db, inst_ut, "work_cerif")
    run_rug = await _seed_run(db, inst_rug, "work_cerif_full")
    # Stream rows inserted after the full row: recency must not matter.
    await _seed_record(db, run_full, "work_cerif_full", UUID_1, FULL_XML)
    await _seed_record(db, run_stream, "work_cerif", _stream_pk(UUID_1), STREAM_XML)
    await _seed_record(db, run_stream, "work_cerif", _stream_pk(UUID_3), STREAM_XML)
    await _seed_record(db, run_rug, "work_cerif_full", UUID_4, FULL_XML)

    latest = await latest_publication_records(db, inst_ut.id)
    assert set(latest) == {UUID_1, UUID_3}
    assert latest[UUID_1]["metadata_xml"] == FULL_XML
    assert latest[UUID_3]["metadata_xml"] == STREAM_XML


@requires_db
async def test_backfill_prefers_full_versions(db, institution_factory):
    """The authorship backfill stores 3 edges from the full version where
    the stream version of the same work would store 1."""
    inst = await institution_factory(code="ut", name="University of Twente")
    run_full = await _seed_run(db, inst, "work_cerif_full")
    run_stream = await _seed_run(db, inst, "work_cerif")
    await _seed_record(db, run_full, "work_cerif_full", UUID_1, FULL_XML)
    await _seed_record(db, run_stream, "work_cerif", _stream_pk(UUID_1), STREAM_XML)
    db.add(
        Work(
            institution_id=inst.id,
            pure_uuid=UUID_1,
            title="Full-author work",
            norm_title="full author work",
            year=2026,
            first_seen_run=run_full.id,
            last_seen_run=run_full.id,
        )
    )
    await db.flush()

    stats = await backfill_pure_work_authors(db, inst)
    assert stats["cerif_records"] == 1
    assert stats["works_with_authors"] == 1
    assert stats["edges"] == 3
    edges = (
        (await db.execute(select(WorkPureAuthor).where(WorkPureAuthor.work_pure_uuid == UUID_1)))
        .scalars()
        .all()
    )
    assert {e.person_uuid for e in edges} == {"p-a", "p-b", "p-ext"}


@requires_db
async def test_mining_is_institution_scoped(db, institution_factory):
    """Publication records under another institution's harvest run must not
    feed this institution's mined candidates."""
    inst = await institution_factory(code="ut", name="University of Twente")
    other = await institution_factory(code="rug", name="RUG")
    run_other = await _seed_run(db, other, "work_cerif_full")
    await _seed_record(db, run_other, "work_cerif_full", UUID_1, FULL_XML)

    org_candidates, person_candidates = await mine_publication_entities(db, inst.id)
    assert org_candidates == {}
    assert person_candidates == {}
