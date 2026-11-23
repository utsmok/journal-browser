"""Outcome tests for the funder_aliases derive (jobs/derive_funder_aliases.py):
the name rule, the grant rule, what stays unresolved, and the rebuild."""

from sqlalchemy import select

from conftest import requires_db
from journal_browser.harvest.funder_aliases import derive_funder_aliases
from journal_browser.models import (
    FunderAlias,
    HarvestRun,
    OpenaireWorkFacts,
    OpenalexFunder,
    Work,
    WorkFunder,
)

NWO = "Netherlands Organisation for Scientific Research (NWO)"


async def _rows(db):
    stmt = select(
        FunderAlias.funder_name,
        FunderAlias.funder_openalex_id,
        FunderAlias.rule,
        FunderAlias.works,
    ).order_by(FunderAlias.funder_name)
    return [tuple(row) for row in (await db.execute(stmt)).all()]


def _work(ut, run, pure_uuid: str) -> Work:
    return Work(
        institution_id=ut.id,
        pure_uuid=pure_uuid,
        title=f"Work {pure_uuid}",
        norm_title=f"work {pure_uuid}",
        year=2021,
        work_type="info:eu-repo/semantics/article",
        first_seen_run=run.id,
        last_seen_run=run.id,
    )


def _award(ut, work: str, funder: str, code: str) -> WorkFunder:
    return WorkFunder(
        institution_id=ut.id,
        pure_uuid=work,
        funder_openalex_id=funder,
        funder_name=funder,
        award=code,
    )


def _project(ut, work: str, funder: str, code: str | None) -> OpenaireWorkFacts:
    return OpenaireWorkFacts(
        institution_id=ut.id,
        pure_uuid=work,
        source_pk=f"oai:{work}",
        projects=[{"id": f"p-{code}", "funder": funder, "code": code}],
    )


@requires_db
async def test_names_resolve_by_display_name_then_shared_grants(db, institution_factory):
    """A name that is an OpenAlex display name resolves to that funder; the
    bare and the full id form are one funder. A name OpenAlex spells
    differently resolves through grant numbers both payloads share. A name
    with neither stays unresolved. A rerun gives the same rows."""
    ut = await institution_factory(code="ut")
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()
    db.add_all(_work(ut, run, f"w{i}") for i in range(1, 8))
    await db.flush()
    db.add_all(
        [
            OpenalexFunder(
                openalex_id="F4320320300", display_name="European Commission", works_count=1361263
            ),
            OpenalexFunder(
                openalex_id="https://openalex.org/F4320320300",
                display_name="European Commission",
                works_count=1337641,
            ),
            OpenalexFunder(
                openalex_id="F4320321800",
                display_name="Nederlandse Organisatie voor Wetenschappelijk Onderzoek",
                works_count=9,
            ),
            OpenalexFunder(
                openalex_id="F4320320307",
                display_name="Directorate-General for Research",
                works_count=5,
            ),
        ]
    )
    for i in range(1, 5):
        db.add(_award(ut, f"w{i}", "F4320321800", f"N-{i}"))
        db.add(_project(ut, f"w{i}", NWO, f"N-{i}"))
    db.add(_award(ut, "w5", "F4320320307", "N-5"))
    db.add(_project(ut, "w5", NWO, "N-5"))
    db.add(_project(ut, "w6", "European Commission", "812345"))
    db.add(_project(ut, "w7", "Nowhere Charity", None))
    await db.flush()

    stats = await derive_funder_aliases(db)

    assert stats == {"names": 3, "by_name": 1, "by_grant": 1, "unresolved": 1}
    rows = await _rows(db)
    assert rows == [
        ("European Commission", "F4320320300", "name", 0),
        (NWO, "F4320321800", "grant", 4),
    ]
    # A rerun replaces the rows, it does not add to them.
    assert await derive_funder_aliases(db) == stats
    assert await _rows(db) == rows


@requires_db
async def test_weak_grant_evidence_stays_unresolved(db, institution_factory):
    """Two shared grant numbers are too few to trust, and a funder with
    less than half of a name's shared grant numbers is not its funder."""
    ut = await institution_factory(code="tud")
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()
    db.add_all(_work(ut, run, f"s{i}") for i in range(1, 8))
    db.add_all(_work(ut, run, f"t{i}") for i in (1, 2))
    await db.flush()
    # "Split Council": three funders share its seven grant numbers.
    for i in range(1, 8):
        funder = "FA" if i <= 3 else ("FB" if i <= 6 else "FC")
        db.add(_award(ut, f"s{i}", funder, f"G-{i}"))
        db.add(_project(ut, f"s{i}", "Split Council", f"G-{i}"))
    # "Small Fund": two shared grant numbers, all on one funder.
    for i in (1, 2):
        db.add(_award(ut, f"t{i}", "FD", f"H-{i}"))
        db.add(_project(ut, f"t{i}", "Small Fund", f"H-{i}"))

    stats = await derive_funder_aliases(db)

    assert stats == {"names": 2, "by_name": 0, "by_grant": 0, "unresolved": 2}
    assert await _rows(db) == []
