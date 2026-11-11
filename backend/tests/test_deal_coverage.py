"""ORM dj_scope vs denorm.DEAL_FLAGS_SQL: one rule, two encodings.

Both must return the same effective coverage per institution on the same
fixture. Change the SQL and the helper together or not at all."""

from sqlalchemy import select

from conftest import requires_db
from journal_browser.harvest.denorm import DEAL_FLAGS_SQL, refresh_deal_flags
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


async def _seed_caps(db):
    """One institution, eight journals, six current deals:

    - A reached: 2026 used=total
    - B unreached: 2026 used < total
    - C no cap_usage data (never counts reached)
    - D reached only via its LATEST year (2026); 2025 entry unreached
    - E unreached: only an OLDER year (2025) reached
    - F latest year with used never reported
    """
    inst = Institution(code="caps", name="C", active=True)
    db.add(inst)
    await db.flush()
    db.add_all(
        [
            Journal(issn_l=issn_l, title=title, type="journal", search_text=title)
            for issn_l, title in [
                ("4444-4444", "Single reached"),
                ("5555-5555", "Single unreached"),
                ("6666-6666", "No cap data"),
                ("7777-7777", "Reached plus unreached"),
                ("8888-8888", "Both reached"),
                ("9999-9999", "Only old year reached"),
                ("1212-1212", "Used never reported"),
                ("1010-1010", "Uncovered"),
            ]
        ]
    )
    deals = {
        "reached": Deal(
            esac_id="capA", status="current", cap_usage=[{"year": 2026, "total": 100, "used": 100}]
        ),
        "unreached": Deal(
            esac_id="capB", status="current", cap_usage=[{"year": 2026, "total": 100, "used": 40}]
        ),
        "nodata": Deal(esac_id="capC", status="current"),
        "latest": Deal(
            esac_id="capD",
            status="current",
            cap_usage=[
                {"year": 2025, "total": 10, "used": 2},
                {"year": 2026, "total": 10, "used": 10},
            ],
        ),
        "oldonly": Deal(
            esac_id="capE",
            status="current",
            cap_usage=[
                {"year": 2025, "total": 5, "used": 5},
                {"year": 2026, "total": 5, "used": 1},
            ],
        ),
        "usednull": Deal(
            esac_id="capF", status="current", cap_usage=[{"year": 2026, "total": 5, "used": None}]
        ),
    }
    db.add_all(deals.values())
    await db.flush()
    db.add_all(
        [DealInstitution(deal_id=deal.id, institution_id=inst.id) for deal in deals.values()]
    )
    cover = [
        ("reached", "4444-4444"),
        ("unreached", "5555-5555"),
        ("nodata", "6666-6666"),
        ("reached", "7777-7777"),
        ("unreached", "7777-7777"),
        ("reached", "8888-8888"),
        ("latest", "8888-8888"),
        ("oldonly", "9999-9999"),
        ("usednull", "1212-1212"),
    ]
    db.add_all(
        [
            DealJournal(deal_id=deals[key].id, issn=issn_l, issn_l=issn_l, source="manual")
            for key, issn_l in cover
        ]
    )
    await db.commit()
    return inst


async def _cap_flags(db, inst):
    rows = (
        await db.execute(
            select(
                JournalFlags.issn_l,
                JournalFlags.deal_covered,
                JournalFlags.deal_cap_reached,
            ).where(JournalFlags.institution_id == inst.id)
        )
    ).all()
    return {r.issn_l: (r.deal_covered, r.deal_cap_reached) for r in rows}


@requires_db
async def test_cap_reached_true_only_when_all_covering_deals_reached(db):
    inst = await _seed_caps(db)
    await refresh_deal_flags(db, inst.id)
    got = await _cap_flags(db, inst)
    assert got["4444-4444"] == (True, True)  # one deal, latest year used >= total
    assert got["5555-5555"] == (True, False)  # one deal, used < total
    assert got["6666-6666"] == (True, False)  # covered deal without cap_usage data
    assert got["7777-7777"] == (True, False)  # one reached + one unreached
    assert got["8888-8888"] == (True, True)  # both deals reached via latest year
    assert got["9999-9999"] == (True, False)  # only an older entry year reached
    assert got["1212-1212"] == (True, False)  # used never reported
    assert got["1010-1010"] == (False, False)  # uncovered journal stays false
    # Re-refresh converges: the guarded write is idempotent.
    await refresh_deal_flags(db, inst.id)
    assert await _cap_flags(db, inst) == got


@requires_db
async def test_search_items_carry_deal_cap_reached(db, db_engine, client):
    """The flag reaches /journals items on every result path (search +
    fuzzy fallback), alongside the covered flag it qualifies."""
    inst = await _seed_caps(db)
    await refresh_deal_flags(db, inst.id)
    # The API reads through its own session; publish the refresh first.
    await db.commit()
    # Above the >3 corpus cutoff so the journals appear in listings.
    async with db_engine.begin() as conn:
        await conn.exec_driver_sql(
            f"UPDATE journal_flags SET works_window_plus = 10 WHERE institution_id = {inst.id}"
        )
    # The fuzzy fallback's trigram match needs pg_trgm (create_all skips
    # migration-side extensions; same setup the search-scopes api fixture does).
    async with db_engine.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    hit = (await client.get(f"/api/v1/{inst.code}/journals", params={"q": "Single"})).json()
    by_issn = {i["issn_l"]: i for i in hit["items"]}
    assert by_issn["4444-4444"]["deal_covered"] is True
    assert by_issn["4444-4444"]["deal_cap_reached"] is True
    assert by_issn["5555-5555"]["deal_covered"] is True
    assert by_issn["5555-5555"]["deal_cap_reached"] is False
    fuzzy = (
        await client.get(
            f"/api/v1/{inst.code}/journals", params={"q": "Single reched", "search_in": "title"}
        )
    ).json()
    assert fuzzy["fuzzy"] is True
    item = next(i for i in fuzzy["items"] if i["issn_l"] == "4444-4444")
    assert item["deal_cap_reached"] is True
