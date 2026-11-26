"""Who a deal's journal list belongs to (deal_publishers): the JCT ingest
withholds a sheet that is another publisher's, openaccess.nl facts win on a
deal row the two sources share, and reconcile flags a foreign list without
dropping it."""

from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, select

from conftest import journal_factory, requires_db
from journal_browser.harvest.deal_publishers import (
    MISMATCH_PREFIX,
    REJECTED_PREFIX,
    SHEET_REJECTED_KEY,
    SheetPublishers,
    Verdict,
    code_of,
    dominant_publisher,
    family_of,
    judge,
    name_matches,
    rejected_sheet,
    withheld,
)
from journal_browser.harvest.jct import _store_agreement
from journal_browser.harvest.openaccess_nl import _upsert_deal
from journal_browser.harvest.reconcile import (
    check_journal_list_publishers,
    reconcile_deals,
)
from journal_browser.models import (
    Deal,
    DealInstitution,
    DealJournal,
    Institution,
    IssnMap,
    ManualOverride,
    Publisher,
)

# The JCT index row of eme2025ukb (live 2026-11) carries the URL of the
# Elsevier UKB sheet; gid=1130349201 is what the provenance shows.
ELSEVIER_SHEET = (
    "https://docs.google.com/spreadsheets/d/e/2PACX-...-oMGy/pub?gid=684626521"
    "&single=true&output=csv"
)
EMERALD_PAGE = "https://www.openaccess.nl/en/publisherdeal/emerald-publishing-group-2025-2027"
FETCHED = "2026-11-24T00:00:00+00:00"

EMERALD_AGREEMENT = {
    "esac_id": "eme2025ukb",
    "end_date": "2026-12-31",
    "ca_only": "no",
    "data_url": ELSEVIER_SHEET,
    "last_reviewed": "2026-01-15",
}


def _sheet_journals(issns):
    return [{"Journal Name": f"Journal {i}", "ISSN (Online)": issn} for i, issn in enumerate(issns)]


def _sheet_participants(*institutions):
    return [{"ROR ID": inst.ror, "Institution Name": inst.name} for inst in institutions]


async def _publisher(db, name, slug=None):
    publisher = Publisher(name=name, openaccess_nl_slug=slug)
    db.add(publisher)
    await db.flush()
    return publisher


async def _deal(db, publisher_id, **kw):
    kw.setdefault("provenance", [])
    deal = Deal(
        publisher_id=publisher_id,
        status="current",
        corresponding_authors_only=False,
        **kw,
    )
    db.add(deal)
    await db.flush()
    return deal


async def _universe(db, publisher_name, stem, n=60):
    """n journals of one publisher; each ISSN is its own ISSN-L."""
    issns = [f"{stem}-{i:04d}" for i in range(n)]
    db.add_all([journal_factory(issn, publisher_name=publisher_name) for issn in issns])
    db.add_all([IssnMap(issn=issn, issn_l=issn, source="openalex") for issn in issns])
    await db.flush()
    return issns


async def _add_rows(db, deal, issns, source):
    db.add_all([DealJournal(deal_id=deal.id, issn=issn, source=source) for issn in issns])
    await db.flush()


async def _elsevier_and_emerald(db):
    """Elsevier and Emerald as on live 2026-11: openaccess.nl publisher rows,
    JCT placeholder rows, and the Elsevier agreement on its own sheet."""
    world = SimpleNamespace(
        els=await _publisher(db, "ELS"),
        elsevier=await _publisher(db, "Elsevier", slug="elsevier"),
        eme=await _publisher(db, "EME"),
        emerald=await _publisher(db, "Emerald Publishing group", slug="emerald-publishing-group"),
    )
    world.ut = Institution(
        name="University of Twente", ror="https://ror.org/006hf6230", code="ut", active=True
    )
    world.rug = Institution(
        name="University of Groningen", ror="https://ror.org/042tr2w39", code="rug", active=True
    )
    db.add_all([world.ut, world.rug])
    await db.flush()
    world.elsevier_issns = await _universe(db, "Elsevier BV", "1000")
    world.emerald_issns = await _universe(db, "Emerald Publishing Limited", "2000")
    world.els_deal = await _deal(
        db, world.els.id, esac_id="els2025ukb", jct_data_url=ELSEVIER_SHEET
    )
    await _add_rows(db, world.els_deal, world.elsevier_issns, "jct")
    return world


async def _row_counts(db, deal_id):
    rows = await db.execute(
        select(DealJournal.source, DealJournal.excluded, func.count())
        .where(DealJournal.deal_id == deal_id)
        .group_by(DealJournal.source, DealJournal.excluded)
    )
    return {(source, excluded): n for source, excluded, n in rows.all()}


# ── judging a list ─────────────────────────────────────────────────────────


def test_name_matches_ignores_company_words():
    assert code_of("eme2025ukb") == "eme" and code_of("Elsevier2026UKB") == "elsevier"
    assert name_matches("Elsevier", "Elsevier BV")
    assert name_matches("De Gruyter Brill", "Brill")
    assert name_matches("AIP Publishing (AIPP)", "AIP Publishing")
    assert not name_matches("Emerald Publishing group", "Elsevier BV")
    assert not name_matches("ACM", "Association for Computing Machinery")


def test_every_de_gruyter_code_is_one_family():
    """JCT spells De Gruyter as degruy, dgb and degruyter; all must share the
    family the sheet's journals resolve to, or the deal's own sheet is withheld."""
    families = {
        family_of(esac, code.upper())
        for esac, code in [
            ("degruy2025kemoe", "degruy"),
            ("dgb2026malmad2", "dgb"),
            ("degruyter2024x", "degruyter"),
        ]
    }
    assert families == {"de gruyter brill"}


def test_dominant_publisher_needs_a_majority():
    top = dominant_publisher({"Elsevier BV": 80, "Emerald Publishing Limited": 10})
    assert top is not None and (top.name, top.count, top.resolved) == ("Elsevier BV", 80, 90)
    assert top.share == pytest.approx(80 / 90)
    # Too few journals resolve, no publisher holds half of them, or the
    # largest group is journals without a publisher name.
    assert dominant_publisher({"Elsevier BV": 49}) is None
    assert dominant_publisher({"Elsevier BV": 30, "Emerald Publishing Limited": 30}) is None
    assert dominant_publisher({"": 70, "Elsevier BV": 60}) is None


def test_judge_prefers_the_owner_over_a_sibling_vouch():
    sheets = SheetPublishers(
        # deal 2 is a second Emerald agreement on the same wrong sheet
        sheets={1: "Elsevier BV", 2: "Elsevier BV"},
        families={1: "elsevier", 2: "emerald publishing group", 3: "emerald publishing group"},
        names={"elsevier": "Elsevier", "emerald publishing group": "Emerald Publishing group"},
    )
    verdict = judge(
        {"Elsevier BV": 80}, family="emerald publishing group", exclude=3, sheets=sheets
    )
    assert verdict.own is False and verdict.foreign == "Elsevier"
    # The same list is the Elsevier agreement's own.
    verdict = judge({"Elsevier BV": 80}, family="elsevier", exclude=1, sheets=sheets)
    assert verdict.own is True and verdict.foreign is None

    # An imprint name no family carries: a sheet of the deal's own family
    # that the imprint dominates vouches for it.
    imprint = SheetPublishers(sheets={1: "Routledge"}, families={1: "taylor & francis"}, names={})
    verdict = judge({"Routledge": 60}, family="taylor & francis", exclude=2, sheets=imprint)
    assert verdict.own is True and verdict.foreign is None
    # Without that voucher, and with no other family owning the imprint,
    # the list is neither the deal's own nor another family's.
    verdict = judge({"Routledge": 60}, family="taylor & francis", exclude=1, sheets=imprint)
    assert verdict.own is False and verdict.foreign is None

    # Unaliased ESAC code: the deal's own stored sheet never votes against it
    # as another owner when exclude=deal_id is passed.
    unaliased = SheetPublishers(
        sheets={10: "American Society for Microbiology"},
        families={10: "american society for microbiology"},
        names={"american society for microbiology": "American Society for Microbiology"},
    )
    assert unaliased.other_owner("asm", "American Society for Microbiology", exclude=10) is None
    verdict = judge(
        {"American Society for Microbiology": 60}, family="asm", exclude=10, sheets=unaliased
    )
    assert verdict.foreign is None


def test_withheld_keeps_an_earlier_rejection():
    unjudged = Verdict(None, False, None)
    assert withheld(unjudged, None) is None
    assert withheld(unjudged, "rejected in an earlier run") == "rejected in an earlier run"
    assert withheld(Verdict(None, True, None), "rejected in an earlier run") is None


# ── JCT ingest ──────────────────────────────────────────────────────────────


@requires_db
async def test_jct_withholds_another_publishers_sheet(db):
    world = await _elsevier_and_emerald(db)
    # The Emerald deal as an older ingest left it on live: the openaccess.nl
    # page, the Elsevier sheet's rows, an admin removal among them, and a
    # contract title list.
    eme = await _deal(
        db,
        world.eme.id,
        esac_id="eme2025ukb",
        openaccess_nl_url=EMERALD_PAGE,
        jct_data_url=ELSEVIER_SHEET,
        start_year=2025,
        end_year=2027,
        duration_text="2025-2027",
    )
    await _add_rows(db, eme, world.elsevier_issns[:40], "jct")
    db.add(DealJournal(deal_id=eme.id, issn=world.elsevier_issns[40], source="jct", excluded=True))
    await _add_rows(db, eme, world.emerald_issns[:30], "manual")
    await db.commit()

    reason = await _store_agreement(
        db,
        EMERALD_AGREEMENT,
        _sheet_journals(world.elsevier_issns),
        _sheet_participants(world.ut, world.rug),
        FETCHED,
    )
    await db.commit()

    assert reason is not None and reason.startswith(REJECTED_PREFIX)
    assert "Elsevier BV" in reason and "Elsevier agreements" in reason
    deal = await db.get(Deal, eme.id)
    assert deal.jct_data_url is None
    assert rejected_sheet(deal.provenance) == reason
    assert deal.needs_curation is True and deal.needs_curation_reason == reason
    # openaccess.nl owns the publisher and the period of a row with a page.
    assert deal.publisher_id == world.eme.id
    assert (deal.start_year, deal.end_year) == (2025, 2027)
    # The sheet's rows go (the admin removal stays as a tombstone), the
    # contract list stays, the participants are stored.
    assert await _row_counts(db, deal.id) == {("manual", False): 30, ("jct", True): 1}
    linked = set(
        (
            await db.execute(
                select(Institution.code).where(
                    Institution.id.in_(
                        select(DealInstitution.institution_id).where(
                            DealInstitution.deal_id == deal.id
                        )
                    )
                )
            )
        ).scalars()
    )
    assert linked == {"ut", "rug"}
    assert await _row_counts(db, world.els_deal.id) == {("jct", False): 60}

    # A rerun changes nothing.
    again = await _store_agreement(
        db,
        EMERALD_AGREEMENT,
        _sheet_journals(world.elsevier_issns),
        _sheet_participants(world.ut, world.rug),
        FETCHED,
    )
    await db.commit()
    assert again == reason
    assert await _row_counts(db, deal.id) == {("manual", False): 30, ("jct", True): 1}


@requires_db
async def test_jct_withheld_sheet_flag_stays_down_after_dismissal(db):
    world = await _elsevier_and_emerald(db)
    eme = await _deal(db, world.eme.id, esac_id="eme2025ukb", openaccess_nl_url=EMERALD_PAGE)
    await db.commit()
    reason = await _store_agreement(
        db,
        EMERALD_AGREEMENT,
        _sheet_journals(world.elsevier_issns),
        _sheet_participants(world.ut),
        FETCHED,
    )
    # The admin dismissed the flag while the journal universe moved on, so
    # the counts in the stored reason text differ.
    eme.needs_curation = False
    eme.needs_curation_reason = None
    eme.curation_resolved_reason = f"{REJECTED_PREFIX}: 2572 of 2600 journals ..."
    await db.commit()

    assert (
        await _store_agreement(
            db,
            EMERALD_AGREEMENT,
            _sheet_journals(world.elsevier_issns),
            _sheet_participants(world.ut),
            FETCHED,
        )
        == reason
    )
    await db.commit()
    deal = await db.get(Deal, eme.id)
    assert deal.needs_curation is False
    assert deal.curation_resolved_reason.startswith(REJECTED_PREFIX)


@requires_db
async def test_jct_stores_the_deals_own_sheet(db):
    world = await _elsevier_and_emerald(db)
    assert (
        await _store_agreement(
            db,
            EMERALD_AGREEMENT,
            _sheet_journals(world.emerald_issns),
            _sheet_participants(world.ut),
            FETCHED,
        )
        is None
    )
    await db.commit()
    deal = await db.scalar(select(Deal).where(Deal.esac_id == "eme2025ukb"))
    assert deal.jct_data_url == ELSEVIER_SHEET
    assert rejected_sheet(deal.provenance) is None
    assert deal.needs_curation is False
    assert await _row_counts(db, deal.id) == {("jct", False): 60}
    # No openaccess.nl page on this row: JCT's placeholder publisher and
    # End Date stand until reconcile finds the page.
    assert deal.publisher_id == world.eme.id
    assert (deal.start_year, deal.end_year) == (2025, 2026)


# ── openaccess.nl first ─────────────────────────────────────────────────────


@requires_db
async def test_scrape_leaves_a_dismissed_journal_list_flag(db):
    dismissed = f"{REJECTED_PREFIX}: 2572 of 2600 journals that resolve ..."
    pub = await _publisher(db, "Emerald Publishing group", slug="emerald-publishing-group")
    deal = await _deal(db, pub.id, openaccess_nl_url=EMERALD_PAGE, esac_id="eme2025ukb")
    deal.curation_resolved_reason = dismissed
    await db.commit()
    page = {
        "url": EMERALD_PAGE,
        "openaccess_nl_url": EMERALD_PAGE,
        "summary": "All Dutch universities ...",
        "conditions_text": "License and conditions",
        "workflow_text": "How it works",
        "article_types_text": None,
        "cap_text": None,
        "cap_numbers": None,
        "contract_url": None,
        "curation_reasons": [],
    }
    item = {
        "duration_text": "2025-2027",
        "status": "current",
        "start_year": 2025,
        "end_year": 2027,
        "per_year_oa_counts": None,
    }
    assert await _upsert_deal(db, pub.id, item, page) is False
    await db.commit()
    # A clean page retires a dismissal of a page reason, not of a
    # journal-list flag: that one is the reconcile's to retire.
    assert (await db.get(Deal, deal.id)).curation_resolved_reason == dismissed


@requires_db
async def test_reconcile_restores_openaccess_nl_facts(db):
    world = await _elsevier_and_emerald(db)
    # The Elsevier agreement already carries its placeholder publisher; an
    # older JCT ingest also wrote its End Date onto the row that holds the
    # openaccess.nl page.
    plain = world.els_deal
    plain.openaccess_nl_url = "https://www.openaccess.nl/en/publisherdeal/elsevier-2025-2027"
    plain.start_year, plain.end_year = 2025, 2026
    plain.duration_text = "2025-2027"
    pinned = await _deal(
        db,
        world.els.id,
        esac_id="els2026ukb",
        openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/elsevier-2026-2028",
        start_year=2026,
        end_year=2026,
        duration_text="2025-2027",
    )
    db.add(
        ManualOverride(
            table_name="deals",
            row_key=str(pinned.id),
            field="publisher_id",
            value=world.els.id,
            rationale="checked: keep on the ESAC publisher",
        )
    )
    # The ESAC code "compbio" has no name of its own, and openaccess.nl
    # spells the publisher without "The": the family name still matches.
    compbio = await _publisher(db, "COMPBIO")
    biologists = await _publisher(db, "Company of Biologists", slug="company-of-biologists")
    renamed = await _deal(
        db,
        compbio.id,
        esac_id="compbio2025ukb",
        openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/company-of-biologists",
    )
    await db.commit()

    stats = await reconcile_deals(db)
    await db.commit()
    assert stats["publisher_restored"] == 2 and stats["period_restored"] == 2
    assert (await db.get(Deal, renamed.id)).publisher_id == biologists.id
    plain = await db.get(Deal, plain.id)
    assert plain.publisher_id == world.elsevier.id
    assert (plain.start_year, plain.end_year) == (2025, 2027)
    # A field with a ManualOverride row is left alone; the others still move.
    pinned = await db.get(Deal, pinned.id)
    assert pinned.publisher_id == world.els.id
    assert (pinned.start_year, pinned.end_year) == (2025, 2027)


# ── reconcile check: flag, never drop ───────────────────────────────────────


@requires_db
async def test_reconcile_flags_a_foreign_list_and_keeps_its_rows(db):
    world = await _elsevier_and_emerald(db)
    # A list that reached the Emerald deal another way (admin import).
    eme = await _deal(
        db,
        world.emerald.id,
        esac_id="eme2024ukb",
        openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/emerald-2024",
    )
    await _add_rows(db, eme, world.elsevier_issns, "manual")
    await db.commit()

    stats = await check_journal_list_publishers(db)
    await db.commit()
    assert stats == {
        "foreign_lists_flagged": 1,
        "rejected_sheets_flagged": 0,
        "list_flags_retired": 0,
    }
    deal = await db.get(Deal, eme.id)
    assert deal.needs_curation is True
    assert deal.needs_curation_reason.startswith(MISMATCH_PREFIX)
    assert "Elsevier BV" in deal.needs_curation_reason
    assert await _row_counts(db, deal.id) == {("manual", False): 60}  # flagged, not dropped

    # The curator replaces the list with Emerald titles: the flag retires.
    await db.execute(delete(DealJournal).where(DealJournal.deal_id == deal.id))
    await _add_rows(db, deal, world.emerald_issns, "manual")
    await db.commit()
    stats = await check_journal_list_publishers(db)
    await db.commit()
    assert stats["list_flags_retired"] == 1
    deal = await db.get(Deal, eme.id)
    assert deal.needs_curation is False and deal.needs_curation_reason is None


@requires_db
async def test_reconcile_keeps_a_withheld_sheet_flagged(db):
    world = await _elsevier_and_emerald(db)
    marker = f"{REJECTED_PREFIX}: 2572 of 2600 journals that resolve ..."
    eme = await _deal(
        db,
        world.emerald.id,
        esac_id="eme2025ukb",
        openaccess_nl_url=EMERALD_PAGE,
        provenance=[{"source": "jct", "url": ELSEVIER_SHEET, SHEET_REJECTED_KEY: marker}],
    )
    # The deal does carry a list of its own now (the contract title list).
    await _add_rows(db, eme, world.emerald_issns, "manual")
    await db.commit()

    stats = await check_journal_list_publishers(db)
    await db.commit()
    assert stats["rejected_sheets_flagged"] == 1 and stats["foreign_lists_flagged"] == 0
    deal = await db.get(Deal, eme.id)
    assert deal.needs_curation_reason == marker

    # Dismissed: the flag stays down while the marker stands, even though
    # the reason text was written against other counts.
    deal.needs_curation = False
    deal.needs_curation_reason = None
    deal.curation_resolved_reason = f"{REJECTED_PREFIX}: 2567 of 2627 journals ..."
    await db.commit()
    stats = await check_journal_list_publishers(db)
    await db.commit()
    assert stats["rejected_sheets_flagged"] == 0 and stats["list_flags_retired"] == 0
    deal = await db.get(Deal, eme.id)
    assert deal.needs_curation is False

    # JCT published the right sheet: the next ingest left no marker. The
    # dismissal retires with its cause.
    deal.provenance = [{"source": "jct", "url": ELSEVIER_SHEET}]
    await db.commit()
    stats = await check_journal_list_publishers(db)
    await db.commit()
    assert stats["list_flags_retired"] == 1
    deal = await db.get(Deal, eme.id)
    assert deal.needs_curation is False and deal.curation_resolved_reason is None


@requires_db
async def test_reconcile_merge_withholds_the_sheet_and_keeps_participants(db):
    world = await _elsevier_and_emerald(db)
    # The openaccess.nl Emerald deal, and beside it the JCT row of the same
    # agreement carrying the Elsevier sheet (a JCT ingest that ran before
    # the check, or a fresh database).
    canonical = await _deal(
        db,
        world.emerald.id,
        openaccess_nl_url=EMERALD_PAGE,
        start_year=2025,
        end_year=2027,
        duration_text="2025-2027",
        conditions_text="Participating in the agreement are: University of Twente",
    )
    await _add_rows(db, canonical, world.emerald_issns[:30], "manual")
    shadow = await _deal(
        db,
        world.eme.id,
        esac_id="eme2025ukb",
        jct_data_url=ELSEVIER_SHEET,
        start_year=2025,
        end_year=2026,
    )
    await _add_rows(db, shadow, world.elsevier_issns, "jct")
    db.add(DealInstitution(deal_id=shadow.id, institution_id=world.ut.id))
    await db.commit()

    stats = await reconcile_deals(db)
    await db.commit()
    assert stats["matched"] == 1
    deal = await db.get(Deal, canonical.id)
    assert deal.esac_id == "eme2025ukb"
    assert deal.jct_data_url is None
    assert (rejected_sheet(deal.provenance) or "").startswith(REJECTED_PREFIX)
    # Only the contract list remains; participation is still linked.
    assert await _row_counts(db, deal.id) == {("manual", False): 30}
    assert await db.scalar(
        select(DealInstitution.deal_id).where(
            DealInstitution.deal_id == deal.id, DealInstitution.institution_id == world.ut.id
        )
    )
    # Deriving coverage from the page does not clear the flag.
    assert deal.needs_curation is True
    assert deal.needs_curation_reason.startswith(REJECTED_PREFIX)
    assert await db.scalar(select(Deal).where(Deal.id == shadow.id)) is None


@requires_db
async def test_reconcile_retires_duplicate_guard_flags(db):
    """The JCT-only rows the old duplicate-sheet guard flagged on live."""
    dgb = await _publisher(db, "DGB")
    degruy = await _publisher(db, "DEGRUY")
    old = await _deal(
        db,
        degruy.id,
        esac_id="degruy2025kemoe",
        needs_curation=True,
        needs_curation_reason=(
            "JCT data CSV is a duplicate of dgb2026malmad2 (96% identical ISSNs)"
        ),
    )
    kept = await _deal(
        db,
        dgb.id,
        esac_id="dgb2026malmad2",
        needs_curation=True,
        needs_curation_reason="sheet lists no ISSN for 40 journals",
    )
    await db.commit()

    stats = await reconcile_deals(db)
    await db.commit()
    assert stats["duplicate_guard_flags_retired"] == 1
    old = await db.get(Deal, old.id)
    assert old.needs_curation is False and old.needs_curation_reason is None
    kept = await db.get(Deal, kept.id)
    assert kept.needs_curation_reason == "sheet lists no ISSN for 40 journals"
