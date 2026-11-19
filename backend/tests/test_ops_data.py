"""Data-integrity outcomes: ingest versioning/overrides/supersede, CHECK
constraints, log redaction, embedding-text composition, ISSN gating and
CSV boundary parsing, and deal reconcile merge/protection. Replaces
test_ingest.py, test_state_constraints.py, test_logging_setup.py,
test_embedding_text.py, test_common.py, test_issn.py and test_reconcile.py."""

import logging

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from conftest import requires_db
from journal_browser.harvest.common import (
    HarvestDataError,
    issn_checksum_ok,
    normalize_issn,
    parse_csv_rows,
    require_headers,
)
from journal_browser.harvest.openalex_journals import journal_values
from journal_browser.harvest.reconcile import derive_nl_deal_coverage, reconcile_deals
from journal_browser.harvest.scimagojr import issn_candidates
from journal_browser.ingest import IngestSession, _strip_nuls, apply_overrides, content_hash
from journal_browser.logging_setup import configure_logging
from journal_browser.models import (
    Deal,
    DealInstitution,
    DealJournal,
    Feedback,
    HarvestRun,
    HarvestState,
    Institution,
    Journal,
    ManualOverride,
    Publisher,
    SourceRecord,
    Work,
    WorkIdentity,
)
from journal_browser.services.embeddings import clean_title, embed_text

# ── Ingest core ───────────────────────────────────────────────────────────


def test_content_hash_and_nul_stripping():
    assert content_hash({"a": 1, "b": [1, 2]}) == content_hash({"b": [1, 2], "a": 1})
    assert content_hash({"a": 1}) != content_hash({"a": 2})
    payload = {"t": "a\x00b", "nested": ["x\x00", {"y": "\x00"}]}
    cleaned = _strip_nuls(payload)
    assert "\x00" not in str(cleaned) and cleaned["t"] == "ab"


@requires_db
async def test_ingest_record_dedupes_versions_and_races(db):
    ingest = IngestSession(db)
    run_id = await ingest.start_run("testsrc", "thing", "filter", {})
    kinds = [
        k
        for k, _ in [
            await ingest.ingest_record("pk1", {"v": 1}),
            await ingest.ingest_record("pk1", {"v": 1}),
            await ingest.ingest_record("pk1", {"v": 2}),
        ]
    ]
    assert kinds == ["new", "duplicate", "new"]
    # Race: another run committed the same version between dedupe and flush.
    payload, h = {"v": 1}, content_hash({"v": 1})
    db.add(
        SourceRecord(
            source="testsrc",
            entity_type="thing",
            source_pk="pk9",
            payload=payload,
            content_hash=h,
            harvest_run_id=run_id,
        )
    )
    await db.flush()
    ingest._pending.append(
        {
            "source": "testsrc",
            "entity_type": "thing",
            "source_pk": "pk9",
            "payload": payload,
            "publication_year": None,
            "content_hash": h,
            "harvest_run_id": run_id,
        }
    )
    await ingest._flush()  # must no-op, not abort on uq_source_records_version
    stats = await ingest.finish_run("completed")
    await db.commit()
    assert stats["records_stored"] == 3
    stored = await db.scalar(
        select(func.count())
        .select_from(SourceRecord)
        .where(SourceRecord.source == "testsrc", SourceRecord.source_pk == "pk9")
    )
    assert stored == 1


@requires_db
async def test_overrides_survive_reingestion(db):
    deal = Deal(esac_id="x1", summary="scraped text")
    db.add(deal)
    await db.flush()
    db.add(
        ManualOverride(
            table_name="deals",
            row_key=str(deal.id),
            field="summary",
            value="curated text",
            rationale="scraper mis-parse",
            set_by="sam",
        )
    )
    await db.flush()
    deal.summary = "scraped text v2"  # a re-ingestion writes new scraped values
    assert await apply_overrides(db, "deals", str(deal.id), deal, ["summary"]) == 1
    await db.commit()
    assert deal.summary == "curated text"


@requires_db
async def test_start_run_supersedes_stale_running_rows_scoped(db, institution_factory):
    stale_id = await IngestSession(db).start_run("src", "ent", "f1", {})
    await db.commit()
    fresh_id = await IngestSession(db).start_run("src", "ent", "f1", {})
    await db.commit()
    old = await db.get(HarvestRun, stale_id)
    assert old.status == "superseded" and old.finished_at is not None
    assert old.stats == {"error": "stale: superseded by a newer run of the same job"}
    assert (await db.get(HarvestRun, fresh_id)).status == "running"

    inst = await institution_factory(code="ut")
    scoped_id = await IngestSession(db).start_run("src", "ent", "f1", {}, institution_id=inst.id)
    await db.commit()
    await IngestSession(db).start_run("src", "ent", "f1", {})  # global run: different key
    await db.commit()
    assert (await db.get(HarvestRun, scoped_id)).status == "running"
    await IngestSession(db).start_run("src", "ent", "f1", {}, institution_id=inst.id)
    await db.commit()
    assert (await db.get(HarvestRun, scoped_id)).status == "superseded"


# ── CHECK constraints ─────────────────────────────────────────────────────


@requires_db
async def test_check_constraints_reject_illegal_states(db):
    bad_rows = [
        Feedback(title="t", description="d", category="bogus"),
        Deal(
            esac_id="x1",
            status="current",
            needs_curation=False,
            needs_curation_reason="orphan reason",
        ),  # reason without the flag
        Deal(
            esac_id="x2",
            status="current",
            needs_curation=True,
            needs_curation_reason="ambiguous cap numbers",
            curation_resolved_reason="previously dismissed",
        ),  # live flag with dismissal
        HarvestState(source="s", entity_type="e", filter_set="all", status="paused"),
    ]
    for row in bad_rows:
        db.add(row)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

    async def _work_fixture(pure_uuid):
        """Fresh institution + run each call: an IntegrityError rollback also
        discards the shared fixture rows."""
        inst = Institution(code=f"c{pure_uuid}", name=f"C {pure_uuid}")
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
        return inst, run

    await _work_fixture("u0")
    _, run0 = await _work_fixture("u0b")
    db.add(
        Work(
            institution_id=run0.institution_id,
            pure_uuid="u0c",
            title="t",
            norm_title="t",
            year=2024,
            first_seen_run=run0.id,
            last_seen_run=run0.id,
            oa_status="openAccess",
        )
    )
    with pytest.raises(IntegrityError):  # non-canonical oa_status spelling
        await db.commit()
    await db.rollback()

    inst1, _ = await _work_fixture("u1")
    db.add(
        WorkIdentity(
            institution_id=inst1.id,
            source="openalex",
            source_pk="doi:10.1/x",
            work_id="u1",
            matched_by="title-guess",
        )
    )
    with pytest.raises(IntegrityError):  # only registry matched_by values pass
        await db.commit()
    await db.rollback()

    inst2, _ = await _work_fixture("u2")
    db.add(
        WorkIdentity(
            institution_id=inst2.id,
            source="openalex",
            source_pk="doi:10.1/y",
            work_id="u2",
            matched_by="trgm:0.82+v",
        )
    )
    await db.commit()
    db.add(Feedback(title="t", description="d", category="data"))
    await db.commit()


# ── Log redaction ─────────────────────────────────────────────────────────


def test_configure_logging_redacts_emitted_records(caplog):
    configure_logging()
    # Log on the root logger: configure_logging installs RedactionFilter
    # there, so the emitted records are redacted before any handler sees
    # them — independent of what handlers the app import installed.
    with caplog.at_level(logging.INFO):
        logging.getLogger().info("auth with %s", "Bearer abc.def.ghi")
        logging.getLogger().info("login failed password=hunter2 attempts=1")
        logging.getLogger().info("served %d rows", 204)
    messages = [r.getMessage() for r in caplog.records]
    auth = next(m for m in messages if "auth with" in m)
    login = next(m for m in messages if "login failed" in m)
    served = next(m for m in messages if "served" in m)
    assert "Bearer ***" in auth and "abc.def.ghi" not in auth
    assert "password=***" in login and "hunter2" not in login
    assert served == "served 204 rows"  # lazy %d formatting preserved


# ── Embedding text composition ────────────────────────────────────────────


def test_embedding_text_golden():
    assert clean_title("International Journal of Plant Sciences") == "plant sciences"
    assert clean_title("Journal") == "Journal"  # all-boilerplate falls back to the raw string
    topics = [{"display_name": "Plant Science", "score": 0.9}]
    assert embed_text("Journal of Nematology", topics, ["A very cited worm paper"]) == (
        "nematology | Plant Science | A very cited worm paper"
    )
    many = embed_text(
        "Blood", [{"display_name": f"Topic {i}"} for i in range(8)], [f"Work {i}" for i in range(6)]
    )
    assert len(many.split(" | ")) == 9  # cleaned title + 5 topics + 3 works
    assert embed_text(None, [], []) is None


# ── ISSN gating and boundary parsers ──────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("0043-1397", "0043-1397"),
        ("00431397", "0043-1397"),
        ("1234-567X", "1234-567X"),
        ("123456789", None),
        ("not-an-issn", None),
        (None, None),
        ("", None),
    ],
)
def test_normalize_issn(raw, want):
    assert normalize_issn(raw) == want


@pytest.mark.parametrize(
    ("issn", "want"),
    [
        ("0043-1354", True),
        ("1234-5679", True),
        ("2434-561X", True),
        ("1234561X", True),
        ("0043-1355", False),
        ("1234-567X", False),
        ("not-an-issn", False),
        (None, False),
        ("", False),
    ],
)
def test_issn_checksum_ok(issn, want):
    assert issn_checksum_ok(issn) is want
    if want:
        assert issn_checksum_ok(normalize_issn(issn.replace("-", "")))


def test_boundary_parsers():
    assert issn_candidates("00431354;1234567X;2434561X") == ["0043-1354", "2434-561X"]
    assert issn_candidates("") == []
    assert parse_csv_rows("\ufeffa;b\n1;two\n".encode(), delimiter=";") == [{"a": "1", "b": "two"}]
    good = journal_values({"id": "S1", "issn_l": "0043-1354", "display_name": "WR"})
    assert good is not None and good["issn_l"] == "0043-1354"
    assert journal_values({"id": "S2", "issn_l": "1234-567X", "display_name": "X"}) is None
    mixed = journal_values(
        {"id": "S3", "issn_l": "1234-5679", "issn": ["1234-5679", "1234-567X"], "display_name": "M"}
    )
    assert mixed is not None and mixed["issns"] == ["1234-5679"]  # bogus variant dropped
    with pytest.raises(HarvestDataError, match=r"doaj journals.*Journal URL"):
        require_headers([{"Journal title": "x"}], {"Journal title", "Journal URL"}, "doaj journals")
    with pytest.raises(HarvestDataError, match="no rows"):
        require_headers([], {"a"}, "scimagojr export")
    require_headers([{"a": "1", "b": "2"}], {"a", "b"}, "openapc ta")  # complete: passes


# ── Deal reconcile ────────────────────────────────────────────────────────


async def _publisher(db, name, slug=None):
    p = Publisher(name=name, openaccess_nl_slug=slug)
    db.add(p)
    await db.flush()
    return p


async def _deal(db, publisher_id, **kw):
    d = Deal(
        publisher_id=publisher_id,
        status="current",
        corresponding_authors_only=False,
        provenance=[],
        **kw,
    )
    db.add(d)
    await db.flush()
    return d


@requires_db
async def test_reconcile_merges_and_is_idempotent(db):
    pub_o = await _publisher(db, "Karger", slug="karger")
    pub_j = await _publisher(db, "KAR")
    inst = Institution(
        name="University of Twente", ror="https://ror.org/006hf6230", code="ut", active=True
    )
    db.add(inst)
    await db.flush()
    oanl = await _deal(
        db, pub_o.id, openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/karger"
    )
    oanl.start_year, oanl.end_year = 2025, 2027
    jct = await _deal(
        db, pub_j.id, esac_id="kar2026caul", jct_data_url="https://jct.example/kar.csv"
    )
    jct.start_year, jct.end_year = 2026, 2027
    db.add(DealInstitution(deal_id=jct.id, institution_id=inst.id))
    db.add(DealJournal(deal_id=jct.id, issn="0250-6807", journal_name="Gerontology", source="jct"))
    await db.commit()

    stats = await reconcile_deals(db)
    await db.commit()
    assert stats["matched"] == 1 and stats["unmatched_oanl"] == 0
    assert (await db.get(Deal, oanl.id)).esac_id == "kar2026caul"  # jct fields merged in
    journals = (await db.execute(select(DealJournal))).scalars().all()
    assert len(journals) == 1 and journals[0].deal_id == oanl.id  # journal moved to the oanl row
    assert len((await db.execute(select(Deal))).scalars().all()) == 1  # jct shadow row gone

    again = await reconcile_deals(db)
    await db.commit()
    assert again["matched"] == 0 and again["unmatched_oanl"] == 0  # rerun: nothing left to do


@requires_db
async def test_reconcile_override_protects(db):
    pub = await _publisher(db, "ACM", slug="acm")
    deal = await _deal(
        db, pub.id, openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/acm"
    )
    deal.start_year, deal.end_year = 2026, 2028
    db.add(
        ManualOverride(
            table_name="deals",
            row_key=str(deal.id),
            field="needs_curation",
            value=False,
            rationale="checked: local ACM deal",
            set_by="sam",
        )
    )
    await db.commit()
    assert (await reconcile_deals(db))["matched"] == 0
    await db.commit()
    d = await db.get(Deal, deal.id)
    assert d.needs_curation is False and d.needs_curation_reason is None


@requires_db
async def test_reconcile_dismissal_protects(db):
    """A reason-aware admin dismissal (no override row) also blocks re-flagging."""
    pub = await _publisher(db, "ACM", slug="acm")
    deal = await _deal(
        db, pub.id, openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/acm"
    )
    deal.start_year, deal.end_year = 2026, 2028
    deal.needs_curation = False
    deal.curation_resolved_reason = "checked: local ACM deal"
    await db.commit()
    assert (await reconcile_deals(db))["matched"] == 0
    await db.commit()
    d = await db.get(Deal, deal.id)
    assert d.needs_curation is False and d.needs_curation_reason is None
    assert d.curation_resolved_reason == "checked: local ACM deal"


# ── NL deal coverage re-derive (folded from test_harvest2_reconcile_rederive.py)


ACM = "Association for Computing Machinery"


async def _pattern_deal(db) -> int:
    """A deal whose coverage list derives from the publisher pattern (the
    openaccess.nl ACM page naming Twente, duration in the conditions)."""
    pub = Publisher(name=ACM)
    db.add(pub)
    await db.flush()
    deal = Deal(
        publisher_id=pub.id,
        status="current",
        corresponding_authors_only=False,
        provenance=[],
        openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/acm-2021-2030",
        conditions_text=(
            "License and conditions: ... University of Twente ... (duration 2026-2028)"
        ),
    )
    db.add(deal)
    await db.flush()
    return deal.id


@requires_db
async def test_pattern_coverage_gains_new_journals(db):
    db.add(
        Institution(
            name="University of Twente", ror="https://ror.org/006hf6230", code="ut", active=True
        )
    )
    deal_id = await _pattern_deal(db)
    for issn in ("0001-0001", "0002-0002"):
        db.add(Journal(issn_l=issn, title=f"J{issn}", publisher_name=ACM))
    await db.commit()

    stats = await derive_nl_deal_coverage(db)
    await db.commit()
    assert stats["covered"] == 1 and stats["pattern_journals"] == 2

    # A new journal of the same publisher joins the corpus later (e.g. ACM
    # TOIS after the first derivation): each run re-derives the pattern.
    db.add(
        Journal(
            issn_l="0003-0003", title="ACM Transactions on Information Systems", publisher_name=ACM
        )
    )
    await db.commit()
    stats2 = await derive_nl_deal_coverage(db)
    await db.commit()
    assert stats2["pattern_journals"] == 1 and stats2["covered"] == 1
    rows = (
        (await db.execute(select(DealJournal).where(DealJournal.deal_id == deal_id)))
        .scalars()
        .all()
    )
    assert {r.issn for r in rows} == {"0001-0001", "0002-0002", "0003-0003"}

    # A third run with nothing new adds nothing (idempotent).
    stats3 = await derive_nl_deal_coverage(db)
    await db.commit()
    assert stats3["pattern_journals"] == 0 and stats3["covered"] == 0


@requires_db
async def test_manual_coverage_freezes_pattern_derivation(db):
    db.add(
        Institution(
            name="University of Twente", ror="https://ror.org/006hf6230", code="ut", active=True
        )
    )
    deal_id = await _pattern_deal(db)
    db.add(Journal(issn_l="0001-0001", title="J1", publisher_name=ACM))
    await db.commit()
    await derive_nl_deal_coverage(db)
    await db.commit()

    # ManualOverride precedence: a hand-added coverage row freezes the
    # pattern list; pattern rows never join on top of a curated deal.
    db.add(
        DealJournal(
            deal_id=deal_id,
            issn="0009-0009",
            issn_l="0009-0009",
            journal_name="Hand-picked",
            source="manual",
        )
    )
    db.add(Journal(issn_l="0004-0004", title="J4", publisher_name=ACM))
    await db.commit()
    stats = await derive_nl_deal_coverage(db)
    await db.commit()
    assert stats["pattern_journals"] == 0 and stats["covered"] == 0
    rows = (
        (await db.execute(select(DealJournal).where(DealJournal.deal_id == deal_id)))
        .scalars()
        .all()
    )
    assert {r.issn for r in rows} == {"0001-0001", "0009-0009"}
