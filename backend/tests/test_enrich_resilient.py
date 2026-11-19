"""Per-entity DOI fetching: a 404 is a miss; any other failure is isolated,
counted, and never faked as a match or a missing identity. A chunk where
every lookup fails fails the run loudly instead of silently no-oping."""

import httpx
import pytest
from bibliofabric.exceptions import APIError, RateLimitError
from sqlalchemy import select

from conftest import requires_db
from journal_browser.harvest.enrich import enrich_openalex, fetch_works_by_doi


def _api_error(status: int) -> APIError:
    return APIError(
        f"API request failed with status {status}",
        response=httpx.Response(status_code=status, request=httpx.Request("GET", "https://x.test")),
    )


class _FakeOA:
    def __init__(self, status: str):
        self.oa_status = status


class _FakeWork:
    """Shape _openalex_work_fields reads (object open_access, model_dump)."""

    def __init__(self, wid: str, oa_status: str | None = None):
        self.id = wid
        self.open_access = _FakeOA(oa_status) if oa_status else None
        self.primary_location = None
        self.locations = []

    def model_dump(self, mode: str = "json"):
        return {"id": self.id}


class _FakeWorks:
    def __init__(self, behavior: dict):
        self.behavior = behavior
        self.urls: list[str] = []

    async def get(self, url: str):
        self.urls.append(url)
        doi = url.removeprefix("https://doi.org/")
        outcome = self.behavior.get(doi)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome if outcome is not None else _FakeWork(f"W-for-{doi}")


class _FakeClient:
    def __init__(self, behavior: dict):
        self.works = _FakeWorks(behavior)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


# ── fetch_works_by_doi ────────────────────────────────────────────────────


async def test_404_is_a_miss_not_an_error():
    client = _FakeClient({"10.1/gone": _api_error(404)})
    found, errored, first_error = await fetch_works_by_doi(client, ["10.1/a", "10.1/gone"])
    assert found["10.1/a"] is not None
    assert found["10.1/gone"] is None
    assert errored == set()
    assert first_error is None


async def test_other_errors_are_isolated_and_counted():
    client = _FakeClient({"10.1/bad": _api_error(500), "10.1/slow": RateLimitError("slow down")})
    stats: dict[str, int] = {}
    found, errored, first_error = await fetch_works_by_doi(
        client, ["10.1/a", "10.1/bad", "10.1/slow"], stats
    )
    assert found["10.1/a"] is not None
    assert errored == {"10.1/bad", "10.1/slow"}
    assert stats["fetch_errors"] == 2
    assert isinstance(first_error, APIError)


async def test_every_doi_gets_its_own_single_get():
    client = _FakeClient({})
    await fetch_works_by_doi(client, ["10.1/a", "10.1/b", "10.1/c"])
    assert client.works.urls == [
        "https://doi.org/10.1/a",
        "https://doi.org/10.1/b",
        "https://doi.org/10.1/c",
    ]


async def test_fully_failed_chunk_fails_loudly():
    client = _FakeClient({d: _api_error(503) for d in ("10.1/a", "10.1/b")})
    with pytest.raises(RuntimeError):
        await fetch_works_by_doi(client, ["10.1/a", "10.1/b"])


# ── refresh selection + reprocessing (DB) ─────────────────────────────────


@requires_db
async def test_refresh_matched_reprocesses_already_matched_works(
    db, institution_factory, monkeypatch
):
    from journal_browser.models import HarvestRun, Work, WorkIdentity

    inst = await institution_factory(code="ut")
    run = HarvestRun(source="test", entity_type="works", config_fingerprint="t")
    db.add(run)
    await db.flush()

    async def land(uuid: str, doi: str) -> Work:
        work = Work(
            institution_id=inst.id,
            pure_uuid=uuid,
            doi_normalized=doi,
            title="t",
            norm_title="t",
            year=2024,
            first_seen_run=run.id,
            last_seen_run=run.id,
        )
        db.add(work)
        await db.commit()
        return work

    matched = await land("uuid-a", "10.1/matched")
    fresh = await land("uuid-b", "10.1/fresh")
    gone = await land("uuid-c", "10.1/gone")
    db.add(
        WorkIdentity(
            institution_id=inst.id,
            source="openalex",
            source_pk="W1",
            work_id=matched.pure_uuid,
            matched_by="doi",
            confidence=1.0,
            status="confirmed",
        )
    )
    await db.commit()

    behavior = {
        "10.1/matched": _FakeWork("W1", oa_status="gold"),
        "10.1/fresh": _FakeWork("W2", oa_status="green"),
        "10.1/gone": _api_error(404),
    }
    monkeypatch.setattr("aletheca.AlethecaClient", lambda **kw: _FakeClient(behavior))
    stats = await enrich_openalex(db, inst.id, refresh_matched=True)

    assert stats["works"] == 3
    assert stats["matched"] == 2
    await db.commit()
    await db.refresh(matched)
    await db.refresh(fresh)
    assert matched.oa_status == "gold"
    assert fresh.oa_status == "green"
    pk_rows = (
        (
            await db.execute(
                select(WorkIdentity.source_pk).where(WorkIdentity.work_id == matched.pure_uuid)
            )
        )
        .scalars()
        .all()
    )
    assert set(pk_rows) == {"W1"}
    fresh_pks = (
        (
            await db.execute(
                select(WorkIdentity.source_pk).where(WorkIdentity.work_id == fresh.pure_uuid)
            )
        )
        .scalars()
        .all()
    )
    assert set(fresh_pks) == {"W2"}
    miss = (
        await db.execute(select(WorkIdentity.status).where(WorkIdentity.work_id == gone.pure_uuid))
    ).scalar_one()
    assert miss == "missing"
