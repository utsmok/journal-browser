"""Unit tests for the ingest core: hashing, versioned upserts, overrides."""

from conftest import requires_db
from journal_browser.ingest import IngestSession, _strip_nuls, apply_overrides, content_hash
from journal_browser.models import Deal, HarvestRun, ManualOverride


def test_content_hash_is_order_stable():
    assert content_hash({"a": 1, "b": [1, 2]}) == content_hash({"b": [1, 2], "a": 1})
    assert content_hash({"a": 1}) != content_hash({"a": 2})


def test_strip_nuls_removes_jsonb_unsafe_bytes():
    payload = {"t": "a\x00b", "nested": ["x\x00", {"y": "\x00"}]}
    cleaned = _strip_nuls(payload)
    assert "\x00" not in str(cleaned)
    assert cleaned["t"] == "ab"


@requires_db
async def test_ingest_record_dedupes_same_payload_versions(db):
    ingest = IngestSession(db)
    await ingest.start_run("testsrc", "thing", "filter", {})
    kind1, h1 = await ingest.ingest_record("pk1", {"v": 1})
    kind2, h2 = await ingest.ingest_record("pk1", {"v": 1})
    kind3, h3 = await ingest.ingest_record("pk1", {"v": 2})
    stats = await ingest.finish_run("completed")
    await db.commit()

    assert (kind1, kind2, kind3) == ("new", "duplicate", "new")
    assert h1 == h2 != h3
    assert stats["records_seen"] == 3
    assert stats["records_stored"] == 2


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

    # A re-ingestion writes new scraped values, then the normalizer re-applies
    # overrides — the curated value must win.
    deal.summary = "scraped text v2"
    applied = await apply_overrides(db, "deals", str(deal.id), deal, ["summary"])
    await db.flush()
    await db.refresh(deal)

    assert applied == 1
    assert deal.summary == "curated text"


@requires_db
async def test_start_run_supersedes_stale_running_rows(db):
    """A crashed run's 'running' row closes when the same job starts again.

    The key is (source, entity_type, institution): the runs table carries
    no filter_set, and every job finishes one run before starting the
    next, so a different filter_set never overlaps in practice.
    """
    stale = IngestSession(db)
    stale_id = await stale.start_run("src", "ent", "f1", {})
    await db.commit()

    fresh = IngestSession(db)
    fresh_id = await fresh.start_run("src", "ent", "f1", {})
    await db.commit()

    old = await db.get(HarvestRun, stale_id)
    assert old.status == "failed"
    assert old.finished_at is not None
    assert old.stats == {"error": "stale: superseded by a newer run of the same job"}
    new = await db.get(HarvestRun, fresh_id)
    assert new.status == "running"

    # A different entity_type or institution is a different key: untouched.
    other = IngestSession(db)
    other_id = await other.start_run("src", "ent2", "f1", {})
    await db.commit()
    third = IngestSession(db)
    await third.start_run("src", "ent", "f1", {})
    await db.commit()
    untouched = await db.get(HarvestRun, other_id)
    assert untouched.status == "running"


@requires_db
async def test_start_run_supersede_respects_institution_scope(db, institution_factory):
    inst = await institution_factory(code="ut")
    scoped = IngestSession(db)
    scoped_id = await scoped.start_run("src", "ent", "f1", {}, institution_id=inst.id)
    await db.commit()
    # A global run of the same job must not close the institution-scoped one.
    global_run = IngestSession(db)
    await global_run.start_run("src", "ent", "f1", {})
    await db.commit()
    assert (await db.get(HarvestRun, scoped_id)).status == "running"
    # ...but a same-scope run does.
    again = IngestSession(db)
    await again.start_run("src", "ent", "f1", {}, institution_id=inst.id)
    await db.commit()
    assert (await db.get(HarvestRun, scoped_id)).status == "failed"
