"""Unit tests for the ingest core: hashing, versioned upserts, overrides."""

from conftest import requires_db
from journal_browser.ingest import IngestSession, _strip_nuls, apply_overrides, content_hash
from journal_browser.models import Deal, ManualOverride


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
