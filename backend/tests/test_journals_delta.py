"""harvest_journals_delta: works-referenced journal gaps via free singletons."""

from sqlalchemy import select

from conftest import requires_db
from journal_browser.harvest.openalex_journals import harvest_journals_delta
from journal_browser.models import HarvestRun, Journal, SourceRecord


class _FakeSourceEntity:
    """model_dump-shaped source payload, as aletheca entities expose."""

    def __init__(self, payload: dict):
        self._payload = payload

    def model_dump(self, mode: str = "json"):
        return self._payload


def _source_payload(pk: str) -> dict:
    return {
        "id": f"https://openalex.org/{pk}",
        "issn_l": "1234-5679",
        "issns": ["1234-5678", "1234-5679"],
        "display_name": "Delta Journal of Testing",
        "is_oa": True,
        "works_count": 10,
        "cited_by_count": 3,
        "counts_by_year": [],
        "topics": [],
    }


class _FakeSourcesClient:
    def __init__(self, payloads: dict[str, dict]):
        self.payloads = payloads
        self.calls: list[str] = []
        self.sources = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url: str):
        self.calls.append(url)
        pk = url.rsplit("/", 1)[-1]
        payload = self.payloads.get(pk)
        if payload is None:
            exc = type("E", (), {"response": type("R", (), {"status_code": 404})()})()
            raise exc
        return _FakeSourceEntity(payload)


@requires_db
async def test_delta_fetches_only_missing_journals(db):
    run = HarvestRun(source="test", entity_type="works", config_fingerprint="t")
    db.add(run)
    await db.flush()
    # One work raw citing a journal we do not have yet, and one we do.
    db.add(
        Journal(
            issn_l="2222-2227",
            openalex_id="S9999999999",
            title="Known",
            search_text="Known",
            type="journal",
        )
    )
    db.add(
        SourceRecord(
            source="openalex",
            entity_type="work",
            source_pk="doi:10.9999/x1",
            payload={"primary_location": {"source": {"id": "https://openalex.org/S1234567890"}}},
            content_hash="h1",
            harvest_run_id=run.id,
        )
    )
    db.add(
        SourceRecord(
            source="openalex",
            entity_type="work",
            source_pk="doi:10.9999/x2",
            payload={"primary_location": {"source": {"id": "https://openalex.org/S9999999999"}}},
            content_hash="h2",
            harvest_run_id=run.id,
        )
    )
    await db.commit()

    client = _FakeSourcesClient({"S1234567890": _source_payload("S1234567890")})
    stats = await harvest_journals_delta(client, db)

    assert stats["referenced"] == 2
    assert stats["todo"] == 1
    assert stats["ingested"] == 1
    assert client.calls == ["https://openalex.org/S1234567890"]

    journal = (
        await db.execute(select(Journal).where(Journal.openalex_id == "S1234567890"))
    ).scalar_one()
    assert journal.issn_l == "1234-5679"
    assert journal.title == "Delta Journal of Testing"

    # The fetched raw landed like a sweep page would.
    landed = (
        await db.execute(
            select(SourceRecord).where(
                SourceRecord.source == "openalex",
                SourceRecord.entity_type == "sources",
                SourceRecord.source_pk == "S1234567890",
            )
        )
    ).scalar_one()
    assert landed.payload["display_name"] == "Delta Journal of Testing"

    # Rerun: journal now known, nothing fetched.
    stats2 = await harvest_journals_delta(client, db)
    assert stats2["todo"] == 0
    assert len(client.calls) == 1
