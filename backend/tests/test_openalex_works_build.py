"""Focused outcome tests for the streaming/SQL-backed rebuild_openalex_works
projection and jobs/build_openalex_works.py runner."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from jobs import build_openalex_works as build_job
from sqlalchemy import select

from conftest import journal_factory, requires_db
from journal_browser.harvest import openalex_works as oa_works
from journal_browser.harvest.openalex_works import rebuild_openalex_works
from journal_browser.models import (
    HarvestRun,
    HarvestState,
    Journal,
    OpenaireWorkFacts,
    OpenalexWork,
    OpenalexWorkAuthor,
    SourceRecord,
    Work,
)


def _payload(
    w_id: str | None,
    *,
    title: str = "Title",
    work_type: str = "article",
    doi: str | None = "10.1234/test",
    oa_status: str | None = "gold",
    source_id: str | None = "S100",
    language: str | None = "en",
    authorships: list[dict[str, Any]] | None = None,
    parent_works: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if authorships is None:
        authorships = [{"author": {"id": "https://openalex.org/A1", "display_name": "Author One"}}]
    data: dict[str, Any] = {
        "id": f"https://openalex.org/{w_id}" if w_id else None,
        "doi": f"https://doi.org/{doi}" if doi else None,
        "display_name": title,
        "publication_year": 2024,
        "type": work_type,
        "open_access": {"oa_status": oa_status} if oa_status is not None else {},
        "primary_location": (
            {"source": {"id": f"https://openalex.org/{source_id}", "display_name": "J"}}
            if source_id
            else {}
        ),
        "language": language,
        "authorships": authorships,
        "cited_by_count": 3,
        "fwci": 1.0,
        "is_retracted": False,
    }
    if parent_works is not None:
        data["parent_works"] = parent_works
    return data


async def _seed_records(
    db,
    inst,
    records: list[tuple[str, dict[str, Any], datetime]],
    *,
    filter_set: str = "institutions.id=UT",
) -> HarvestRun:
    run = HarvestRun(
        source="openalex",
        entity_type="works_stats",
        institution_id=inst.id,
        status="completed",
        config_fingerprint="test",
    )
    db.add(run)
    await db.flush()
    db.add(
        HarvestState(
            source="openalex",
            entity_type="works_stats",
            filter_set=filter_set,
            institution_id=inst.id,
            last_run_id=run.id,
        )
    )
    for i, (pk, payload, ts) in enumerate(records):
        db.add(
            SourceRecord(
                source="openalex",
                entity_type="works_stats",
                source_pk=pk,
                payload=payload,
                publication_year=payload.get("publication_year"),
                content_hash=f"h-{run.id}-{pk}-{i}",
                harvested_at=ts,
                harvest_run_id=run.id,
            )
        )
    await db.flush()
    return run


@requires_db
async def test_rebuild_newest_payload_wins_dedupes_wid_and_chunks(
    db, institution_factory, monkeypatch
):
    """DISTINCT ON picks the newest payload per source_pk (tie-breaking on id),
    distinct source_pk spellings decoding to the same w_id keep first-wins
    deterministically, and multi-chunk streaming inserts work end-to-end."""
    monkeypatch.setattr(oa_works, "INSERT_CHUNK", 2)
    monkeypatch.setattr(oa_works, "STREAM_PARTITION", 2)

    ut = await institution_factory(code="ut")
    t0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=1)

    # Same source_pk with older and newer harvested_at -> t1 wins.
    # Same source_pk with identical harvested_at -> higher id (second row) wins.
    # Two distinct source_pk strings ("W20" and "W20-alias") decoding to w_id "W20" ->
    # "W20" sorts before "W20-alias" so first-wins keeps "Primary W20".
    await _seed_records(
        db,
        ut,
        [
            ("W01", _payload("W01", title="Old W01"), t0),
            ("W01", _payload("W01", title="New W01"), t1),
            ("W02", _payload("W02", title="First W02 same-ts"), t0),
            ("W02", _payload("W02", title="Second W02 same-ts"), t0),
            ("W20", _payload("W20", title="Primary W20"), t0),
            ("W21", _payload("W21", title="Work 21"), t0),
            ("W22", _payload("W22", title="Work 22"), t0),
            ("W23", _payload("W23", title="Work 23"), t0),
        ],
        filter_set="institutions.id=UT",
    )
    # Alias in an author-sweep run must NOT double-count works or author_sweep_rows.
    await _seed_records(
        db,
        ut,
        [
            ("W20-alias", _payload("W20", title="Duplicate W20"), t1),
            ("W24", _payload("W24", title="Sweep W24"), t0),
        ],
        filter_set="author-sweep:0",
    )

    stats = await rebuild_openalex_works(db, ut)
    assert stats["works"] == 7
    assert stats["author_sweep_rows"] == 1
    rows = {
        r.w_id: r
        for r in (
            await db.execute(select(OpenalexWork).where(OpenalexWork.institution_id == ut.id))
        ).scalars()
    }
    assert set(rows) == {"W01", "W02", "W20", "W21", "W22", "W23", "W24"}
    assert rows["W01"].title == "New W01"
    assert rows["W02"].title == "Second W02 same-ts"
    assert rows["W20"].title == "Primary W20"
    assert rows["W20"].source == "works_stats"
    assert rows["W24"].source == "author-sweep"


@requires_db
async def test_rebuild_preserves_prior_parts(db, institution_factory):
    """Prior part-of facts and checked timestamps survive silent rebuilds,
    while new payload-carried parent_works win and stamp parts_checked_at."""
    ut = await institution_factory(code="ut")
    t_old = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    t_checked = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
    existing_parents = [{"id": "W999", "name": "Old Book", "rel": "part_of"}]
    new_parents = [
        {"id": "https://openalex.org/W888", "display_name": "Fresh Book", "relationship": "part_of"}
    ]

    db.add_all(
        [
            OpenalexWork(
                institution_id=ut.id,
                w_id="W_PART",
                parent_works=existing_parents,
                is_part=True,
                parts_checked_at=t_old,
            ),
            OpenalexWork(
                institution_id=ut.id,
                w_id="W_CHECKED",
                parent_works=[],
                is_part=False,
                parts_checked_at=t_checked,
            ),
            OpenalexWork(
                institution_id=ut.id,
                w_id="W_UNCHECKED",
                parent_works=[],
                is_part=False,
                parts_checked_at=None,
            ),
            OpenalexWork(
                institution_id=ut.id,
                w_id="W_UPGRADED",
                parent_works=existing_parents,
                is_part=True,
                parts_checked_at=t_old,
            ),
        ]
    )
    await db.flush()

    now = datetime.now(UTC)
    await _seed_records(
        db,
        ut,
        [
            ("W_PART", _payload("W_PART"), now),
            ("W_CHECKED", _payload("W_CHECKED"), now),
            ("W_UNCHECKED", _payload("W_UNCHECKED"), now),
            ("W_UPGRADED", _payload("W_UPGRADED", parent_works=new_parents), now),
            ("W_NEW_SILENT", _payload("W_NEW_SILENT"), now),
            ("W_NEW_PART", _payload("W_NEW_PART", parent_works=new_parents), now),
        ],
    )

    before_rebuild = datetime.now(UTC)
    await rebuild_openalex_works(db, ut)
    rows = {
        r.w_id: r
        for r in (
            await db.execute(select(OpenalexWork).where(OpenalexWork.institution_id == ut.id))
        ).scalars()
    }

    assert rows["W_PART"].is_part is True
    assert rows["W_PART"].parent_works == existing_parents
    assert rows["W_PART"].parts_checked_at == t_old

    assert rows["W_CHECKED"].is_part is False
    assert rows["W_CHECKED"].parent_works == []
    assert rows["W_CHECKED"].parts_checked_at == t_checked

    assert rows["W_UNCHECKED"].is_part is False
    assert rows["W_UNCHECKED"].parent_works == []
    assert rows["W_UNCHECKED"].parts_checked_at is None

    assert rows["W_UPGRADED"].is_part is True
    assert rows["W_UPGRADED"].parent_works == [
        {"id": "W888", "name": "Fresh Book", "rel": "part_of"}
    ]
    assert rows["W_UPGRADED"].parts_checked_at is not None
    assert rows["W_UPGRADED"].parts_checked_at >= before_rebuild

    assert rows["W_NEW_SILENT"].is_part is False
    assert rows["W_NEW_SILENT"].parts_checked_at is None

    assert rows["W_NEW_PART"].is_part is True
    assert rows["W_NEW_PART"].parent_works == [
        {"id": "W888", "name": "Fresh Book", "rel": "part_of"}
    ]
    assert rows["W_NEW_PART"].parts_checked_at is not None
    assert rows["W_NEW_PART"].parts_checked_at >= before_rebuild


@requires_db
async def test_rebuild_work_authors_sql_derivation_and_dedupe(db, institution_factory):
    """openalex_work_authors is derived in SQL, lowercases A-ids, dedupes
    repeated authors within one work, skips id-less entries, and isolates
    other institutions."""
    ut = await institution_factory(code="ut")
    rug = await institution_factory(code="rug")
    # Pre-existing RUG edge must survive UT's rebuild.
    db.add(OpenalexWorkAuthor(institution_id=rug.id, author_id="a99", w_id="W99"))
    await db.flush()

    now = datetime.now(UTC)
    await _seed_records(
        db,
        ut,
        [
            (
                "W1",
                _payload(
                    "W1",
                    authorships=[
                        {"author": {"id": "https://openalex.org/A10", "display_name": "Alice"}},
                        {"author": {"id": "https://openalex.org/a10", "display_name": "Alice dup"}},
                        {"author": {"id": None, "display_name": "No ID Author"}},
                        {"author": {"id": "", "orcid": "https://orcid.org/0000-0001-2345-6789"}},
                        {"author": {"id": "https://openalex.org/A20", "display_name": "Bob"}},
                    ],
                ),
                now,
            ),
            ("W2", _payload("W2", authorships=[]), now),
        ],
    )

    stats = await rebuild_openalex_works(db, ut)
    assert stats["attributions"] == 2

    ut_edges = {
        (r.w_id, r.author_id)
        for r in (
            await db.execute(
                select(OpenalexWorkAuthor).where(OpenalexWorkAuthor.institution_id == ut.id)
            )
        ).scalars()
    }
    assert ut_edges == {("W1", "a10"), ("W1", "a20")}

    rug_edges = {
        (r.w_id, r.author_id)
        for r in (
            await db.execute(
                select(OpenalexWorkAuthor).where(OpenalexWorkAuthor.institution_id == rug.id)
            )
        ).scalars()
    }
    assert rug_edges == {("W99", "a99")}


@requires_db
async def test_rebuild_language_stamp_oa_foldback_and_stats_keys(db, institution_factory):
    """Modal journals.language (with alphabetical tie-break), works.oa_status
    OpenAlex-wins + most-open-DOI foldback, and the full stats dict schema."""
    ut = await institution_factory(code="ut")
    db.add_all(
        [
            journal_factory("1111-1111", openalex_id="S1"),
            journal_factory("2222-2222", openalex_id="S2"),
        ]
    )
    work_run = HarvestRun(
        source="pure",
        entity_type="work",
        institution_id=ut.id,
        status="completed",
        config_fingerprint="test",
    )
    db.add(work_run)
    await db.flush()
    db.add_all(
        [
            Work(
                institution_id=ut.id,
                pure_uuid="p-conflict",
                doi_normalized="10.1234/conflict",
                title="Conflict",
                norm_title="conflict",
                year=2024,
                oa_status="closed",
                first_seen_run=work_run.id,
                last_seen_run=work_run.id,
            ),
            Work(
                institution_id=ut.id,
                pure_uuid="p-multi",
                doi_normalized="10.1234/multi",
                title="Multi",
                norm_title="multi",
                year=2024,
                oa_status="closed",
                first_seen_run=work_run.id,
                last_seen_run=work_run.id,
            ),
        ]
    )
    await db.flush()
    db.add(
        OpenaireWorkFacts(
            institution_id=ut.id,
            pure_uuid="p-conflict",
            source_pk="oa-1",
            oa_color="gold",
        )
    )
    await db.flush()

    now = datetime.now(UTC)
    await _seed_records(
        db,
        ut,
        [
            # S1: 2 en vs 1 de -> en
            (
                "W1",
                _payload(
                    "W1", source_id="S1", language="en", doi="10.1234/conflict", oa_status="green"
                ),
                now,
            ),
            (
                "W2",
                _payload(
                    "W2", source_id="S1", language="en", doi="10.1234/multi", oa_status="closed"
                ),
                now,
            ),
            (
                "W3",
                _payload(
                    "W3", source_id="S1", language="de", doi="10.1234/multi", oa_status="gold"
                ),
                now,
            ),
            # S2: 1 fr vs 1 de -> tie breaks alphabetically to de
            ("W4", _payload("W4", source_id="S2", language="fr", doi=None), now),
            ("W5", _payload("W5", source_id="S2", language="de", doi=None), now),
            # Excluded type + parse failure (missing id)
            ("W6", _payload("W6", work_type="preprint"), now),
            ("W_BAD", _payload(None, title="No ID"), now),
        ],
    )

    stats = await rebuild_openalex_works(db, ut)
    assert set(stats) == {
        "works",
        "parse_failures",
        "excluded_types",
        "author_sweep_rows",
        "attributions",
        "journals_language_stamped",
        "works_oa_synced",
    }
    assert stats["works"] == 5
    assert stats["parse_failures"] == 1
    assert stats["excluded_types"] == 1
    assert stats["journals_language_stamped"] == 2
    assert stats["works_oa_synced"] == 2

    j1 = await db.get(Journal, "1111-1111")
    j2 = await db.get(Journal, "2222-2222")
    assert j1 is not None and j1.language == "en"
    assert j2 is not None and j2.language == "de"

    stored_oa = dict(
        (
            await db.execute(
                select(Work.pure_uuid, Work.oa_status).where(Work.institution_id == ut.id)
            )
        ).all()
    )
    # OpenAlex green beats OpenAIRE gold; for duplicate DOI, gold beats closed.
    assert stored_oa == {"p-conflict": "green", "p-multi": "gold"}


@requires_db
async def test_build_openalex_works_job_commits_per_institution(
    db, institution_factory, capsys, monkeypatch
):
    """jobs/build_openalex_works.py commits after each institution so earlier
    institutions persist even if a later one fails."""
    ut = await institution_factory(code="ut")
    rug = await institution_factory(code="rug")
    now = datetime.now(UTC)
    await _seed_records(db, ut, [("W1", _payload("W1"), now)])
    await _seed_records(db, rug, [("W2", _payload("W2"), now)])
    await db.commit()

    calls: list[str] = []
    real_rebuild = oa_works.rebuild_openalex_works

    async def _fail_second(session, institution):
        calls.append(institution.code or str(institution.id))
        if len(calls) == 2:
            raise RuntimeError("boom on second institution")
        return await real_rebuild(session, institution)

    monkeypatch.setattr(build_job, "rebuild_openalex_works", _fail_second)
    with pytest.raises(RuntimeError, match="boom on second institution"):
        await build_job.main()

    first_code = calls[0]
    first_inst = ut if first_code == "ut" else rug
    second_inst = rug if first_code == "ut" else ut
    first_rows = (
        (await db.execute(select(OpenalexWork).where(OpenalexWork.institution_id == first_inst.id)))
        .scalars()
        .all()
    )
    second_rows = (
        (
            await db.execute(
                select(OpenalexWork).where(OpenalexWork.institution_id == second_inst.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(first_rows) == 1
    assert len(second_rows) == 0

    # Full run with both succeeding prints JSON keyed by both institution codes.
    monkeypatch.setattr(build_job, "rebuild_openalex_works", real_rebuild)
    await build_job.main()
    out = capsys.readouterr().out
    assert '"ut"' in out and '"rug"' in out


@requires_db
async def test_pure_entities_streaming_distinct_on_and_institution_isolation(
    db, institution_factory, monkeypatch
):
    """rebuild_pure_orgs/rebuild_pure_persons/iter_latest_publication_xml
    dedupe newest version per source_pk in SQL, isolate institutions, and
    flush multi-chunk batches cleanly (including PureOrgParent FK order)."""
    from journal_browser.harvest.pure import entities as pure_entities
    from journal_browser.models import PureOrg, PureOrgParent, PurePerson

    monkeypatch.setattr(pure_entities, "STREAM_PARTITION", 2)
    monkeypatch.setattr(pure_entities, "INSERT_CHUNK", 2)

    ut = await institution_factory(code="ut")
    rug = await institution_factory(code="rug")
    t0 = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=1)

    ut_run = HarvestRun(
        source="pure",
        entity_type="orgs",
        institution_id=ut.id,
        status="completed",
        config_fingerprint="test",
    )
    rug_run = HarvestRun(
        source="pure",
        entity_type="orgs",
        institution_id=rug.id,
        status="completed",
        config_fingerprint="test",
    )
    db.add_all([ut_run, rug_run])
    await db.flush()

    def _org_xml(org_id: str, name: str, parent_id: str | None = None) -> str:
        part_of = (
            f'<PartOf><OrgUnit id="openaire_cris_orgunits/{parent_id}">'
            f"<Name>Parent</Name></OrgUnit></PartOf>"
            if parent_id
            else ""
        )
        return (
            f'<OrgUnit xmlns="https://www.openaire.eu/cerif-profile/1.1/" '
            f'id="openaire_cris_orgunits/{org_id}">'
            f"<Name>{name}</Name>{part_of}</OrgUnit>"
        )

    def _person_xml(pid: str, first: str, family: str, orcid: str | None = None) -> str:
        orcid_el = f"<ORCID>https://orcid.org/{orcid}</ORCID>" if orcid else ""
        return (
            f'<Person xmlns="https://www.openaire.eu/cerif-profile/1.1/" '
            f'id="openaire_cris_persons/{pid}">'
            f"<PersonName><FamilyNames>{family}</FamilyNames>"
            f"<FirstNames>{first}</FirstNames></PersonName>{orcid_el}</Person>"
        )

    db.add_all(
        [
            # UT orgs: o-1 has old + new versions; o-2 & o-3 force multiple chunks.
            SourceRecord(
                source="pure",
                entity_type="orgs",
                source_pk="openaire_cris_orgunits/o-1",
                payload={"metadata_xml": _org_xml("o-1", "Old Name")},
                content_hash="o1-old",
                harvested_at=t0,
                harvest_run_id=ut_run.id,
            ),
            SourceRecord(
                source="pure",
                entity_type="orgs",
                source_pk="openaire_cris_orgunits/o-1",
                payload={"metadata_xml": _org_xml("o-1", "New Name", parent_id="o-root")},
                content_hash="o1-new",
                harvested_at=t1,
                harvest_run_id=ut_run.id,
            ),
            SourceRecord(
                source="pure",
                entity_type="orgs",
                source_pk="openaire_cris_orgunits/o-2",
                payload={"metadata_xml": _org_xml("o-2", "Org Two", parent_id="o-1")},
                content_hash="o2",
                harvested_at=t0,
                harvest_run_id=ut_run.id,
            ),
            SourceRecord(
                source="pure",
                entity_type="orgs",
                source_pk="openaire_cris_orgunits/o-3",
                payload={"metadata_xml": _org_xml("o-3", "Org Three")},
                content_hash="o3",
                harvested_at=t0,
                harvest_run_id=ut_run.id,
            ),
            # RUG org must never leak into UT's rebuild.
            SourceRecord(
                source="pure",
                entity_type="orgs",
                source_pk="openaire_cris_orgunits/o-rug",
                payload={"metadata_xml": _org_xml("o-rug", "RUG Faculty")},
                content_hash="orug",
                harvested_at=t1,
                harvest_run_id=rug_run.id,
            ),
            # UT persons: p-1 updated, p-2 & p-3 force multiple chunks; p-rug isolated.
            SourceRecord(
                source="pure",
                entity_type="persons",
                source_pk="openaire_cris_persons/p-1",
                payload={"metadata_xml": _person_xml("p-1", "Old", "Name")},
                content_hash="p1-old",
                harvested_at=t0,
                harvest_run_id=ut_run.id,
            ),
            SourceRecord(
                source="pure",
                entity_type="persons",
                source_pk="openaire_cris_persons/p-1",
                payload={
                    "metadata_xml": _person_xml("p-1", "Ada", "Lovelace", "0000-0001-2345-6789")
                },
                content_hash="p1-new",
                harvested_at=t1,
                harvest_run_id=ut_run.id,
            ),
            SourceRecord(
                source="pure",
                entity_type="persons",
                source_pk="openaire_cris_persons/p-2",
                payload={"metadata_xml": _person_xml("p-2", "Alan", "Turing")},
                content_hash="p2",
                harvested_at=t0,
                harvest_run_id=ut_run.id,
            ),
            SourceRecord(
                source="pure",
                entity_type="persons",
                source_pk="openaire_cris_persons/p-3",
                payload={"metadata_xml": _person_xml("p-3", "Grace", "Hopper")},
                content_hash="p3",
                harvested_at=t0,
                harvest_run_id=ut_run.id,
            ),
            SourceRecord(
                source="pure",
                entity_type="persons",
                source_pk="openaire_cris_persons/p-rug",
                payload={"metadata_xml": _person_xml("p-rug", "RUG", "Person")},
                content_hash="prug",
                harvested_at=t1,
                harvest_run_id=rug_run.id,
            ),
        ]
    )
    await db.flush()

    mined_orgs = {
        "o-1": {"name": "Should Not Override"},
        "o-m1": {"name": "Mined One"},
        "o-m2": {"name": "Mined Two"},
        "o-m3": {"name": "Mined Three"},
    }
    org_stats = await pure_entities.rebuild_pure_orgs(db, ut.id, mined=mined_orgs)
    assert org_stats == {"orgs": 3, "parents": 2, "mined_orgs": 3, "parse_failures": 0}
    ut_orgs = {
        r.uuid: r.name
        for r in (
            await db.execute(select(PureOrg).where(PureOrg.institution_id == ut.id))
        ).scalars()
    }
    assert ut_orgs == {
        "o-1": "New Name",
        "o-2": "Org Two",
        "o-3": "Org Three",
        "o-m1": "Mined One",
        "o-m2": "Mined Two",
        "o-m3": "Mined Three",
    }
    ut_parents = {
        (r.org_uuid, r.parent_uuid)
        for r in (
            await db.execute(select(PureOrgParent).where(PureOrgParent.institution_id == ut.id))
        ).scalars()
    }
    assert ut_parents == {("o-1", "o-root"), ("o-2", "o-1")}

    mined_persons = {
        "p-1": {"first_names": "Ignored", "family_names": "Dup"},
        "p-m1": {"first_names": "Mined", "family_names": "One"},
        "p-m2": {"first_names": "Mined", "family_names": "Two"},
        "p-m3": {"first_names": "Mined", "family_names": "Three"},
    }
    person_stats = await pure_entities.rebuild_pure_persons(db, ut.id, mined=mined_persons)
    assert person_stats == {"persons": 3, "mined_persons": 3, "parse_failures": 0}
    ut_persons = {
        r.uuid: (r.name, r.orcid)
        for r in (
            await db.execute(select(PurePerson).where(PurePerson.institution_id == ut.id))
        ).scalars()
    }
    assert ut_persons == {
        "p-1": ("Ada Lovelace", "0000-0001-2345-6789"),
        "p-2": ("Alan Turing", None),
        "p-3": ("Grace Hopper", None),
        "p-m1": ("Mined One", None),
        "p-m2": ("Mined Two", None),
        "p-m3": ("Mined Three", None),
    }


@requires_db
async def test_listing_orcids_distinct_on_latest_and_isolated(db, institution_factory):
    """_listing_orcids projects payload->>'orcid' with DISTINCT ON, picks the
    newest version per author pk, normalizes to bare lowercase ORCID, and
    isolates institutions."""
    from journal_browser.harvest.author_ids import _listing_orcids

    ut = await institution_factory(code="ut")
    rug = await institution_factory(code="rug")
    t0 = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=1)

    ut_run = HarvestRun(
        source="openalex",
        entity_type="authors",
        institution_id=ut.id,
        status="completed",
        config_fingerprint="test",
    )
    rug_run = HarvestRun(
        source="openalex",
        entity_type="authors",
        institution_id=rug.id,
        status="completed",
        config_fingerprint="test",
    )
    db.add_all([ut_run, rug_run])
    await db.flush()

    db.add_all(
        [
            SourceRecord(
                source="openalex",
                entity_type="authors",
                source_pk="A1",
                payload={
                    "id": "https://openalex.org/A1",
                    "orcid": "https://orcid.org/0000-0000-0000-0001",
                },
                content_hash="a1-old",
                harvested_at=t0,
                harvest_run_id=ut_run.id,
            ),
            SourceRecord(
                source="openalex",
                entity_type="authors",
                source_pk="A1",
                payload={
                    "id": "https://openalex.org/A1",
                    "orcid": "https://orcid.org/0000-0000-0000-000X",
                },
                content_hash="a1-new",
                harvested_at=t1,
                harvest_run_id=ut_run.id,
            ),
            SourceRecord(
                source="openalex",
                entity_type="authors",
                source_pk="A2",
                payload={"id": "https://openalex.org/A2", "orcid": None},
                content_hash="a2",
                harvested_at=t0,
                harvest_run_id=ut_run.id,
            ),
            SourceRecord(
                source="openalex",
                entity_type="authors",
                source_pk="A9",
                payload={
                    "id": "https://openalex.org/A9",
                    "orcid": "https://orcid.org/0000-0009-9999-9999",
                },
                content_hash="a9",
                harvested_at=t1,
                harvest_run_id=rug_run.id,
            ),
        ]
    )
    await db.flush()

    assert await _listing_orcids(db, ut.id) == {
        "A1": "0000-0000-0000-000x",
        "A2": None,
    }
    assert await _listing_orcids(db, rug.id) == {
        "A9": "0000-0009-9999-9999",
    }
