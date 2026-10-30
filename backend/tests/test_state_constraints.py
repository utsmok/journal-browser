"""CHECK constraints reject the illegal states the code never writes."""

import pytest
from sqlalchemy.exc import IntegrityError

from conftest import requires_db
from journal_browser.models import (
    Deal,
    Feedback,
    HarvestRun,
    HarvestState,
    Institution,
    Work,
    WorkIdentity,
)


@requires_db
async def test_feedback_rejects_unknown_category(db):
    db.add(Feedback(title="t", description="d", category="bogus"))
    with pytest.raises(IntegrityError):
        await db.commit()


@requires_db
async def test_feedback_accepts_registry_category(db):
    db.add(Feedback(title="t", description="d", category="data"))
    await db.commit()


@requires_db
async def test_deal_rejects_reason_without_flag(db):
    db.add(
        Deal(
            esac_id="x1",
            status="current",
            needs_curation=False,
            needs_curation_reason="orphan reason",
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()


@requires_db
async def test_work_rejects_noncanonical_oa_status(db):
    inst = Institution(code="c1", name="C")
    db.add(inst)
    await db.flush()
    db.add(
        Work(
            institution_id=inst.id,
            pure_uuid="u1",
            title="t",
            norm_title="t",
            year=2024,
            first_seen_run=1,
            last_seen_run=1,
            oa_status="openAccess",
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()


@requires_db
async def _seed_work(db, code: str, pure_uuid: str) -> Institution:
    inst = Institution(code=code, name="C")
    db.add(inst)
    await db.flush()
    run = HarvestRun(
        source="test", entity_type="work", institution_id=inst.id, config_fingerprint="t"
    )
    db.add(run)
    await db.flush()
    db.add(
        Work(
            institution_id=inst.id,
            pure_uuid=pure_uuid,
            title="t",
            norm_title="t",
            year=2024,
            first_seen_run=run.id,
            last_seen_run=run.id,
        )
    )
    await db.flush()
    return inst


@requires_db
async def test_work_identity_rejects_unknown_matched_by(db):
    inst = await _seed_work(db, "c2", "u1")
    db.add(
        WorkIdentity(
            institution_id=inst.id,
            source="openalex",
            source_pk="doi:10.1/x",
            work_id="u1",
            matched_by="title-guess",
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()


@requires_db
async def test_work_identity_accepts_trgm_threshold(db):
    inst = await _seed_work(db, "c3", "u2")
    db.add(
        WorkIdentity(
            institution_id=inst.id,
            source="openalex",
            source_pk="doi:10.1/y",
            work_id="u2",
            matched_by="trgm:0.82+v",
        )
    )
    await db.commit()


@requires_db
async def test_harvest_state_rejects_unknown_status(db):
    db.add(HarvestState(source="s", entity_type="e", filter_set="all", status="paused"))
    with pytest.raises(IntegrityError):
        await db.commit()
