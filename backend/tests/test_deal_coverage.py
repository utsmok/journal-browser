"""ORM dj_scope vs denorm.DEAL_FLAGS_SQL: one rule, two encodings.

Both must return the same effective coverage per institution on the same
fixture. Change the SQL and the helper together or not at all."""

from sqlalchemy import select

from conftest import requires_db
from journal_browser.harvest.denorm import DEAL_FLAGS_SQL
from journal_browser.models import (
    Deal,
    DealInstitution,
    DealJournal,
    Institution,
    Journal,
    JournalFlags,
)
from journal_browser.services.deal_coverage import dj_scope


async def _seed(db):
    shared = Institution(code="shared", name="S")  # journal_override = False
    override = Institution(code="override", name="O")  # journal_override = True
    db.add_all([shared, override])
    await db.flush()
    db.add_all(
        [
            Journal(issn_l="1111-111X", title="Shared covered"),
            Journal(issn_l="2222-2220", title="Shared excluded"),
            Journal(issn_l="3333-3339", title="Scoped only"),
        ]
    )
    deal = Deal(esac_id="cov2026", status="current")
    db.add(deal)
    await db.flush()
    db.add_all(
        [
            DealInstitution(deal_id=deal.id, institution_id=shared.id),
            DealInstitution(deal_id=deal.id, institution_id=override.id, journal_override=True),
            # Shared sheet rows: 1111 covered, 2222 admin-excluded.
            DealJournal(deal_id=deal.id, issn="1111-111X", issn_l="1111-111X", source="manual"),
            DealJournal(
                deal_id=deal.id,
                issn="2222-2220",
                issn_l="2222-2220",
                source="manual",
                excluded=True,
            ),
            # Override-scoped row only visible to the override institution.
            DealJournal(
                deal_id=deal.id,
                institution_id=override.id,
                issn="3333-3339",
                issn_l="3333-3339",
                source="manual",
            ),
        ]
    )
    await db.commit()
    return shared, override


async def _orm_covered(db, institution):
    rows = (
        await db.execute(
            select(DealJournal.issn_l)
            .select_from(Deal)
            .join(
                DealInstitution,
                (DealInstitution.deal_id == Deal.id)
                & (DealInstitution.institution_id == institution.id),
            )
            .join(
                DealJournal,
                (DealJournal.deal_id == Deal.id)
                & dj_scope(institution.id)
                & DealJournal.excluded.is_not(True),
            )
            .where(Deal.status == "current")
        )
    ).scalars()
    return set(rows)


async def _sql_covered(db, institution):
    for row in ("1111-111X", "2222-2220", "3333-3339"):
        db.add(
            JournalFlags(
                institution_id=institution.id,
                issn_l=row,
                deal_covered=False,
            )
        )
    await db.commit()
    await db.execute(DEAL_FLAGS_SQL, {"iid": institution.id})
    await db.commit()
    rows = await db.execute(
        select(JournalFlags.issn_l).where(
            JournalFlags.institution_id == institution.id,
            JournalFlags.deal_covered.is_(True),
        )
    )
    return set(rows.scalars())


@requires_db
async def test_orm_scope_matches_denorm_sql(db):
    shared, override = await _seed(db)
    for inst in (shared, override):
        assert await _orm_covered(db, inst) == await _sql_covered(db, inst), inst.code
    # Spot-check the actual expected sets, not just equality of two empties.
    assert await _orm_covered(db, shared) == {"1111-111X"}
    assert await _orm_covered(db, override) == {"3333-3339"}
