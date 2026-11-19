"""OpenAIRE work facts: payload extraction, the derive job, the journal
OpenAIRE card, and the openaire_diamond denorm flag."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import journal_factory, requires_db
from journal_browser.harvest.denorm import refresh_institution_stats
from journal_browser.harvest.openaire_facts import derive_openaire_facts, facts_from_payload
from journal_browser.models import (
    HarvestRun,
    Institution,
    JournalFlags,
    OpenaireWorkFacts,
    OpenalexWork,
    SourceRecord,
    Work,
    WorkIdentity,
)

MAIN_ISSN = "1234-5678"
OTHER_ISSN = "2222-2222"

#: Realistic stored payload (aireloom ResearchProduct dump): FOS scheme is
#: uppercase on the live Graph, usage counts/embargo/diamond/licenses all
#: present, one keyword subject that must stay out of fos.
FULL_PAYLOAD = {
    "id": "doajarticles::abc123",
    "type": "publication",
    "isInDiamondJournal": True,
    "openAccessColor": "gold",
    "license": "cc-by-4.0",
    "open_access_url": "https://example.org/final.pdf",
    "indicators": {
        "usageCounts": {"views": 12, "downloads": 3},
        "citationImpact": {"citationCount": 0},
    },
    "subjects": [
        {"subject": {"scheme": "FOS", "value": "0101 mathematics"}, "provenance": None},
        {"subject": {"scheme": "fos", "value": "0102 computer and information sciences"}},
        {"subject": {"scheme": "FOS", "value": "0101 mathematics"}},
        {"subject": {"scheme": "keyword", "value": "chronic disease"}},
        {"subject": {"scheme": "FOS", "value": None}},
        {"subject": None},
    ],
    "projects": [
        {"id": "nwo_________::a1", "funder": "NWO", "code": "13544", "acronym": "COPD"},
        {"id": "ec_________::a2", "funder": "EC", "code": None, "acronym": None},
        "garbage",
        None,
    ],
    "instances": [
        {"embargoEndDate": None},
        {"embargoEndDate": "2027-03-15T00:00:00Z"},
        {"embargoEndDate": "not-a-date"},
        {"embargoEndDate": "2026-01-01"},
    ],
}


# ── payload extraction (pure) ─────────────────────────────────────────────


def test_facts_from_full_payload():
    facts = facts_from_payload(FULL_PAYLOAD)
    assert facts["views"] == 12
    assert facts["downloads"] == 3
    assert facts["diamond"] is True
    assert facts["oa_color"] == "gold"
    assert facts["license"] == "cc-by-4.0"
    assert facts["oa_url"] == "https://example.org/final.pdf"
    # max across instances, unparseable entries skipped
    assert facts["embargo_end"].isoformat() == "2027-03-15"
    # sorted unique FOS values; keyword/None subjects excluded, both
    # scheme casings accepted
    assert facts["fos"] == ["0101 mathematics", "0102 computer and information sciences"]
    # non-dict entries dropped, known keys projected (None kept as null)
    assert facts["projects"] == [
        {"id": "nwo_________::a1", "funder": "NWO", "code": "13544", "acronym": "COPD"},
        {"id": "ec_________::a2", "funder": "EC", "code": None, "acronym": None},
    ]


def test_facts_usage_and_diamond_falsy_defaults():
    facts = facts_from_payload(
        {
            "id": "x",
            "indicators": {"usageCounts": {"views": None, "downloads": None}},
            "isInDiamondJournal": False,
            "instances": [],
            "subjects": [],
            "projects": None,
        }
    )
    assert facts["views"] is None
    assert facts["downloads"] is None
    assert facts["diamond"] is False
    assert facts["embargo_end"] is None
    assert facts["fos"] == []
    assert facts["projects"] == []


def test_facts_missing_sections_are_null_not_errors():
    facts = facts_from_payload({"id": "x"})
    assert facts["views"] is None
    assert facts["downloads"] is None
    assert facts["diamond"] is False
    assert facts["oa_color"] is None
    assert facts["license"] is None
    assert facts["oa_url"] is None
    assert facts["fos"] == []
    assert facts["projects"] == []


def test_facts_projects_scalar_dict():
    facts = facts_from_payload({"id": "x", "projects": {"id": "p1", "funder": "EC"}})
    assert facts["projects"] == [{"id": "p1", "funder": "EC", "code": None, "acronym": None}]


# ── DB helpers ────────────────────────────────────────────────────────────


async def _land_work(db, inst: Institution, uuid: str, *, doi=None, issn=None, year=2021):
    run = HarvestRun(source="test", entity_type="works", config_fingerprint="t")
    db.add(run)
    await db.flush()
    work = Work(
        institution_id=inst.id,
        pure_uuid=uuid,
        doi_normalized=doi,
        title=f"T {uuid}",
        norm_title=f"t {uuid}",
        year=year,
        work_type="article",
        journal_issn_l=issn,
        first_seen_run=run.id,
        last_seen_run=run.id,
    )
    db.add(work)
    await db.flush()
    return work


async def _land_openaire(db, inst: Institution, pk: str, payload: dict) -> None:
    run = HarvestRun(
        source="openaire", entity_type="work", config_fingerprint="t", institution_id=inst.id
    )
    db.add(run)
    await db.flush()

    from journal_browser.ingest import content_hash

    db.add(
        SourceRecord(
            source="openaire",
            entity_type="work",
            source_pk=pk,
            payload=payload,
            publication_year=None,
            content_hash=content_hash(payload),
            harvest_run_id=run.id,
        )
    )
    await db.flush()


async def _confirm_identity(db, inst: Institution, pk: str, uuid: str, status="confirmed"):
    db.add(
        WorkIdentity(
            institution_id=inst.id,
            source="openaire",
            source_pk=pk,
            work_id=uuid,
            matched_by="doi",
            confidence=1.0,
            status=status,
        )
    )
    await db.flush()


async def _all_facts(db):
    return (
        (
            await db.execute(
                select(OpenaireWorkFacts)
                .execution_options(populate_existing=True)
                .order_by(OpenaireWorkFacts.pure_uuid)
            )
        )
        .scalars()
        .all()
    )


# ── derive job (DB) ───────────────────────────────────────────────────────


@requires_db
async def test_derive_upserts_idempotent_and_prunes(db, institution_factory):
    inst = await institution_factory(code="ut")
    db.add(journal_factory(MAIN_ISSN))
    await db.flush()
    work = await _land_work(db, inst, "pw1", doi="10.1/w1", issn=MAIN_ISSN)
    await _land_openaire(db, inst, "oa-1", FULL_PAYLOAD)
    await _confirm_identity(db, inst, "oa-1", work.pure_uuid)
    await db.commit()

    stats = await derive_openaire_facts(db, inst)
    await db.commit()
    assert stats["identities"] == 1
    assert stats["upserted"] == 1
    assert stats["with_usage"] == 1
    assert stats["with_fulltext"] == 1
    assert stats["diamond"] == 1

    rows = await _all_facts(db)
    assert len(rows) == 1
    row = rows[0]
    assert (row.institution_id, row.pure_uuid, row.source_pk) == (inst.id, "pw1", "oa-1")
    assert (row.views, row.downloads) == (12, 3)
    assert row.diamond is True
    assert row.oa_color == "gold"
    assert row.license == "cc-by-4.0"
    assert row.oa_url == "https://example.org/final.pdf"
    assert row.embargo_end.isoformat() == "2027-03-15"
    assert row.fos == ["0101 mathematics", "0102 computer and information sciences"]
    assert len(row.projects) == 2

    # rerun: same row refreshed in place, nothing grows
    stats = await derive_openaire_facts(db, inst)
    await db.commit()
    assert stats["upserted"] == 1
    assert stats["pruned"] == 0
    assert len(await _all_facts(db)) == 1

    # identity un-confirmed: the facts row is pruned on the next refresh
    await db.execute(
        WorkIdentity.__table__.update()
        .where(WorkIdentity.source_pk == "oa-1")
        .values(status="missing")
    )
    await db.commit()
    stats = await derive_openaire_facts(db, inst)
    await db.commit()
    assert stats["pruned"] == 1
    assert await _all_facts(db) == []


@requires_db
async def test_derive_latest_payload_wins(db, institution_factory):
    """Two stored versions of one record: the newest harvested_at wins."""
    from datetime import UTC, datetime, timedelta

    inst = await institution_factory(code="ut")
    db.add(journal_factory(MAIN_ISSN))
    await db.flush()
    work = await _land_work(db, inst, "pw1", doi="10.1/w1", issn=MAIN_ISSN)
    run = HarvestRun(
        source="openaire", entity_type="work", config_fingerprint="t", institution_id=inst.id
    )
    db.add(run)
    await db.flush()
    old = dict(FULL_PAYLOAD, openAccessColor="green")
    new = dict(FULL_PAYLOAD, openAccessColor="gold")
    stamps = (datetime.now(UTC) - timedelta(days=1), datetime.now(UTC))
    for pk_payload, harvested_at in ((old, stamps[0]), (new, stamps[1])):
        from journal_browser.ingest import content_hash

        db.add(
            SourceRecord(
                source="openaire",
                entity_type="work",
                source_pk="oa-1",
                payload=pk_payload,
                publication_year=None,
                content_hash=content_hash(pk_payload),
                harvest_run_id=run.id,
                harvested_at=harvested_at,
            )
        )
    await _confirm_identity(db, inst, "oa-1", work.pure_uuid)
    await db.commit()

    await derive_openaire_facts(db, inst)
    await db.commit()
    rows = await _all_facts(db)
    assert [r.oa_color for r in rows] == ["gold"]


# ── journal card + works items via the API (DB) ───────────────────────────


@pytest.fixture
async def api(client, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        session.add_all([journal_factory(MAIN_ISSN), journal_factory(OTHER_ISSN)])
        inst = Institution(name="Test U", code="tu", active=True)
        session.add(inst)
        await session.flush()
        run = HarvestRun(source="test", entity_type="works", config_fingerprint="t")
        session.add(run)
        await session.flush()

        # pw1: full facts, store row disagrees on the OA color;
        # pw2: identity-confirmed, facts mostly null, store row agrees;
        # pw3: other journal, never matched.
        session.add_all(
            [
                Work(
                    institution_id=inst.id,
                    pure_uuid="pw1",
                    doi_normalized="10.1/w1",
                    title="T pw1",
                    norm_title="t pw1",
                    year=2021,
                    work_type="article",
                    journal_issn_l=MAIN_ISSN,
                    first_seen_run=run.id,
                    last_seen_run=run.id,
                ),
                Work(
                    institution_id=inst.id,
                    pure_uuid="pw2",
                    doi_normalized="10.2/w2",
                    title="T pw2",
                    norm_title="t pw2",
                    year=2022,
                    work_type="article",
                    journal_issn_l=MAIN_ISSN,
                    first_seen_run=run.id,
                    last_seen_run=run.id,
                ),
                Work(
                    institution_id=inst.id,
                    pure_uuid="pw3",
                    title="T pw3",
                    norm_title="t pw3",
                    year=2022,
                    work_type="article",
                    journal_issn_l=OTHER_ISSN,
                    first_seen_run=run.id,
                    last_seen_run=run.id,
                ),
            ]
        )
        session.add_all(
            [
                OpenalexWork(
                    institution_id=inst.id,
                    w_id="W1",
                    doi_normalized="10.1/w1",
                    title="Store W1",
                    year=2021,
                    work_type="article",
                    oa_status="green",
                ),
                OpenalexWork(
                    institution_id=inst.id,
                    w_id="W2",
                    doi_normalized="10.2/w2",
                    title="Store W2",
                    year=2022,
                    work_type="article",
                    oa_status="gold",
                ),
                # merged-profile duplicate of the same DOI, less open and a
                # higher W-id: the most-open row must win the cross-check
                OpenalexWork(
                    institution_id=inst.id,
                    w_id="W2b",
                    doi_normalized="10.2/w2",
                    title="Store W2 twin",
                    year=2022,
                    work_type="article",
                    oa_status="closed",
                ),
            ]
        )
        await _land_openaire(session, inst, "oa-1", FULL_PAYLOAD)
        await _land_openaire(
            session,
            inst,
            "oa-2",
            {
                "id": "oa-2",
                "openAccessColor": "gold",
                "isInDiamondJournal": False,
                "subjects": [{"subject": {"scheme": "FOS", "value": "0101 mathematics"}}],
                "projects": [{"id": "nwo_________::b7", "funder": "NWO"}],
            },
        )
        await _confirm_identity(session, inst, "oa-1", "pw1")
        await _confirm_identity(session, inst, "oa-2", "pw2")
        await session.commit()
        await derive_openaire_facts(session, inst)
        await session.commit()
    return client


@requires_db
async def test_works_item_carries_openaire_block(api):
    r = await api.get(f"/api/v1/tu/journals/{MAIN_ISSN}/works")
    assert r.status_code == 200
    items = {i["title"]: i for i in r.json()["items"]}
    assert items["T pw1"]["openaire"] == {
        "views": 12,
        "downloads": 3,
        "oa_url": "https://example.org/final.pdf",
        "license": "cc-by-4.0",
        "oa_color": "gold",
        "diamond": True,
        "embargo_end": "2027-03-15",
        "fos": ["0101 mathematics", "0102 computer and information sciences"],
        "projects": [
            {"id": "nwo_________::a1", "funder": "NWO", "code": "13544", "acronym": "COPD"},
            {"id": "ec_________::a2", "funder": "EC", "code": None, "acronym": None},
        ],
    }
    # matched but sparsely-populated record: keys present, values null
    assert items["T pw2"]["openaire"] == {
        "views": None,
        "downloads": None,
        "oa_url": None,
        "license": None,
        "oa_color": "gold",
        "diamond": False,
        "embargo_end": None,
        "fos": ["0101 mathematics"],
        "projects": [{"id": "nwo_________::b7", "funder": "NWO", "code": None, "acronym": None}],
    }


@requires_db
async def test_openaire_info_counts_and_crosscheck(api, db):
    inst = (await db.execute(select(Institution).where(Institution.code == "tu"))).scalar_one()
    from journal_browser.services import detail_enrichment

    info = await detail_enrichment.openaire_info(db, inst, MAIN_ISSN)
    assert info["matched_works"] == 2
    assert info["with_fulltext"] == 1
    assert info["with_usage"] == 1
    assert info["diamond_works"] == 1
    # both works state an OA color on both sides
    assert info["oa_color_total"] == 2
    # pw1 gold (facts) vs green (store); pw2 agrees gold vs gold — the
    # merged-profile twin (closed) must not win the store pick
    assert info["oa_color_disagree"] == 1
    assert info["top_fos"] == [
        {"subject": "0101 mathematics", "works": 2},
        {"subject": "0102 computer and information sciences", "works": 1},
    ]
    assert info["top_funders"] == [{"funder": "NWO", "works": 2}, {"funder": "EC", "works": 1}]


@requires_db
async def test_openaire_info_served_on_detail(api):
    r = await api.get(f"/api/v1/tu/journals/{MAIN_ISSN}")
    assert r.status_code == 200
    body = r.json()
    assert body["openaire"]["matched_works"] == 2
    assert body["openaire"]["oa_color_disagree"] == 1
    assert body["openaire"]["diamond_works"] == 1
    assert {"subject": "0101 mathematics", "works": 2} in body["openaire"]["top_fos"]
    assert {"funder": "NWO", "works": 2} in body["openaire"]["top_funders"]


# ── openaire_diamond denorm flag (DB) ─────────────────────────────────────


@requires_db
async def test_refresh_institution_stats_stamps_openaire_diamond(db, institution_factory):
    inst = await institution_factory(code="ut")
    db.add_all([journal_factory(MAIN_ISSN), journal_factory(OTHER_ISSN)])
    await db.flush()
    await _land_work(db, inst, "pw1", doi="10.1/w1", issn=MAIN_ISSN)
    await _land_work(db, inst, "pw2", doi="10.2/w2", issn=OTHER_ISSN)
    await _land_openaire(db, inst, "oa-1", FULL_PAYLOAD)  # diamond payload
    await _land_openaire(db, inst, "oa-2", {"id": "oa-2", "isInDiamondJournal": False})
    await _confirm_identity(db, inst, "oa-1", "pw1")
    await _confirm_identity(db, inst, "oa-2", "pw2")
    await db.commit()
    await derive_openaire_facts(db, inst)
    await db.commit()

    await refresh_institution_stats(db, inst)
    await db.commit()
    flags = dict(
        (
            await db.execute(
                select(JournalFlags.issn_l, JournalFlags.openaire_diamond).where(
                    JournalFlags.institution_id == inst.id
                )
            )
        ).all()
    )
    assert flags[MAIN_ISSN] is True
    assert flags[OTHER_ISSN] is False

    # the diamond work retires: the flag must clear on the next refresh
    await db.execute(
        Work.__table__.update().where(Work.pure_uuid == "pw1").values(retired_at=func.now())
    )
    await db.commit()
    await refresh_institution_stats(db, inst)
    await db.commit()
    flags = dict(
        (
            await db.execute(
                select(JournalFlags.issn_l, JournalFlags.openaire_diamond).where(
                    JournalFlags.institution_id == inst.id
                )
            )
        ).all()
    )
    assert flags[MAIN_ISSN] is False
