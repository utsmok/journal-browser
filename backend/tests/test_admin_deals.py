"""Admin deal CRUD: edits stick via manual_overrides, removals exclude,
ignored_issns hides journals from every listing."""

from datetime import date
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from conftest import requires_db
from journal_browser.db import get_session
from journal_browser.harvest.denorm import MATERIALIZE_SQL
from journal_browser.harvest.jct import _store_agreement
from journal_browser.main import app
from journal_browser.models import (
    Deal,
    DealJournal,
    Institution,
    IssnMap,
    Journal,
    ManualOverride,
    Publisher,
)
from journal_browser.services import search

PASSWORD = "test-admin-pw"


@pytest.fixture
async def admin_api(db_engine, monkeypatch):
    monkeypatch.setenv("JB_ADMIN_PASSWORD", PASSWORD)
    from journal_browser.config import reset_settings_cache

    reset_settings_cache()
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with maker() as session:
        session.add_all(
            [
                Institution(name="University of Twente", code="ut", active=True),
                Institution(name="RuG", code="rug", active=True),
                Publisher(name="Emerald Publishing group"),
            ]
        )
        await session.flush()
        pub_id = await session.scalar(select(Publisher.id))
        deal = Deal(
            publisher_id=pub_id,
            esac_id="em2019caul",
            status="current",
            corresponding_authors_only=False,
            cap_text="300 articles per year",
            cap_numbers={"2024": 300},
            provenance=[],
            needs_curation=True,
            needs_curation_reason="duplicate sheet",
        )
        session.add(deal)
        await session.flush()
        session.add_all(
            [
                Journal(issn_l="0000-0000", title="J Zero", type="journal"),
                Journal(issn_l="1111-1111", title="J One", type="journal"),
                IssnMap(issn="9999-8888", issn_l="0000-0000", source="test"),
                DealJournal(deal_id=deal.id, issn="0000-0000", issn_l="0000-0000", source="jct"),
                DealJournal(deal_id=deal.id, issn="1111-1111", issn_l="1111-1111", source="jct"),
            ]
        )
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.clear()
    reset_settings_cache()


async def _login(client: AsyncClient) -> dict[str, str]:
    r = await client.post("/api/v1/admin/login", json={"password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


@requires_db
async def test_list_and_detail(admin_api):
    headers = await _login(admin_api)
    deals = (await admin_api.get("/api/v1/admin/deals", headers=headers)).json()
    assert len(deals) == 1
    d = deals[0]
    assert d["publisher"] == "Emerald Publishing group"
    assert d["esac_id"] == "em2019caul"
    assert d["capped"] is True and d["cap_numbers"] == {"2024": 300}
    assert d["journal_count"] == 2
    assert d["participations"] == []
    assert d["needs_curation"] is True

    detail = (await admin_api.get(f"/api/v1/admin/deals/{d['id']}", headers=headers)).json()
    assert {(j["issn"], j["source"], j["excluded"]) for j in detail["journals"]} == {
        ("0000-0000", "jct", False),
        ("1111-1111", "jct", False),
    }
    assert detail["journals"][0]["issn_l"] == "0000-0000"

    r = await admin_api.get("/api/v1/admin/deals/99999", headers=headers)
    assert r.status_code == 404


@requires_db
async def test_create_deal(admin_api):
    headers = await _login(admin_api)
    r = await admin_api.post(
        "/api/v1/admin/deals",
        headers=headers,
        json={"publisher_name": "Wiley", "esac_id": "wiley2026nl", "start_year": 2026},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["publisher"] == "Wiley" and body["status"] == "current"

    # duplicate esac_id -> 409; missing publisher -> 422
    r = await admin_api.post(
        "/api/v1/admin/deals",
        headers=headers,
        json={"publisher_name": "X", "esac_id": "em2019caul"},
    )
    assert r.status_code == 409
    r = await admin_api.post("/api/v1/admin/deals", headers=headers, json={"esac_id": "x2026"})
    assert r.status_code == 422


@requires_db
async def test_update_deal_records_overrides(admin_api, db_engine):
    headers = await _login(admin_api)
    deal_id = (await admin_api.get("/api/v1/admin/deals", headers=headers)).json()[0]["id"]
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}",
        headers=headers,
        json={"summary": "Hand-fixed summary", "cap_numbers": None, "status": "archive"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "archive" and body["summary"] == "Hand-fixed summary"
    assert body["cap_numbers"] is None and body["capped"] is False
    assert body["needs_curation"] is False and body["needs_curation_reason"] is None

    async with async_sessionmaker(db_engine)() as session:
        assert str((await session.get(Deal, deal_id)).last_reviewed) == date.today().isoformat()
        fields = set(
            await session.scalars(
                select(ManualOverride.field).where(
                    ManualOverride.table_name == "deals",
                    ManualOverride.row_key == str(deal_id),
                )
            )
        )
        expected = {"summary", "cap_numbers", "status", "needs_curation", "needs_curation_reason"}
        assert expected <= fields

    # validation: bad status / bad cap_numbers key / unknown field / esac clash
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}", headers=headers, json={"status": "bogus"}
    )
    assert r.status_code == 400
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}", headers=headers, json={"cap_numbers": {"20x4": 1}}
    )
    assert r.status_code == 400
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}", headers=headers, json={"consortium": "nope"}
    )
    assert r.status_code == 400
    r = await admin_api.post(
        "/api/v1/admin/deals",
        headers=headers,
        json={"publisher_name": "Other", "esac_id": "zz2026"},
    )
    other_id = r.json()["id"]
    r = await admin_api.put(
        f"/api/v1/admin/deals/{other_id}", headers=headers, json={"esac_id": "em2019caul"}
    )
    assert r.status_code == 409


@requires_db
async def test_journals_add_remove_and_jct_survival(admin_api, db_engine):
    headers = await _login(admin_api)
    deal_id = (await admin_api.get("/api/v1/admin/deals", headers=headers)).json()[0]["id"]

    # remove: flagged, not deleted; count drops
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/journals", headers=headers, json={"remove": ["0000-0000"]}
    )
    assert r.status_code == 200
    detail = r.json()
    assert detail["journal_count"] == 1
    assert [(j["excluded"]) for j in detail["journals"] if j["issn"] == "0000-0000"] == [True]

    # add: variant ISSN resolves via issn_map, unknown stays NULL; re-adding
    # a removed ISSN clears the excluded flag
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/journals",
        headers=headers,
        json={
            "add": [
                {"issn": "9999-8888", "journal_name": "J Zero"},
                {"issn": "8888-7777"},
                {"issn": "0000-0000"},
            ],
            "remove": ["1111-1111"],
        },
    )
    assert r.status_code == 200
    rows = {j["issn"]: j for j in r.json()["journals"]}
    assert rows["9999-8888"]["issn_l"] == "0000-0000"
    assert rows["8888-7777"]["issn_l"] is None
    assert rows["0000-0000"]["excluded"] is False  # re-added
    assert rows["1111-1111"]["excluded"] is True

    # invalid ISSN -> 400
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/journals", headers=headers, json={"add": [{"issn": "nope"}]}
    )
    assert r.status_code == 400

    # removal survives a JCT-style re-upsert of the same ISSN
    async with async_sessionmaker(db_engine)() as session:
        await session.execute(
            update(DealJournal)
            .where(DealJournal.deal_id == deal_id, DealJournal.issn == "0000-0000")
            .values(excluded=True)
        )
        await session.commit()
        agreement = {
            "esac_id": "em2019caul",
            "end_date": "2026-12-31",
            "ca_only": "",
            "data_url": "https://example.com/em.csv",
            "last_reviewed": "2026-01-15",
        }
        journals = [
            {
                "Journal Name": "J Zero",
                "ISSN (Online)": "0000-0000",
                "ISSN (Print)": "",
                "Journal First Seen": "2024-01-01",
                "Journal Last Seen": "2025-01-01",
            }
        ]
        await _store_agreement(session, agreement, journals, [], "2026-10-26T00:00:00+00:00")
        await session.commit()
        row = await session.scalar(
            select(DealJournal).where(
                DealJournal.deal_id == deal_id, DealJournal.issn == "0000-0000"
            )
        )
        assert row is not None and row.excluded is True
        # cap_text override re-applied on top of the re-ingested deal
        deal = await session.get(Deal, deal_id)
        assert deal.cap_text == "300 articles per year"


@requires_db
async def test_participations(admin_api):
    headers = await _login(admin_api)
    deal_id = (await admin_api.get("/api/v1/admin/deals", headers=headers)).json()[0]["id"]
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/participations",
        headers=headers,
        json={"add": ["ut", "rug"]},
    )
    assert r.status_code == 200
    assert r.json()["participations"] == ["rug", "ut"]
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/participations", headers=headers, json={"remove": ["rug"]}
    )
    assert r.json()["participations"] == ["ut"]
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/participations", headers=headers, json={"add": ["nope"]}
    )
    assert r.status_code == 404


# ── ignored_issns consumption ───────────────────────────────────────────────


@pytest.fixture
async def search_api(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _override():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    async with maker() as session:
        session.add(
            Institution(
                name="University of Twente", code="ut", active=True
            )
        )
        await session.flush()
        session.add_all(
            [
                Journal(
                    issn_l="0000-0000", title="J Zero", type="journal", publisher_name="Alpha",
                    works_2020_plus=10,
                ),
                Journal(
                    issn_l="1111-1111", title="J One", type="journal", publisher_name="Beta",
                    works_2020_plus=10,
                ),
            ]
        )
        await session.commit()
        await session.execute(
            MATERIALIZE_SQL, {"iid": (await session.scalar(select(Institution.id)))}
        )
        await session.execute(
            text("UPDATE journal_flags SET works_window_plus = 10")
        )
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    app.dependency_overrides.clear()


def _ignore(monkeypatch, issns: list[str]) -> None:
    monkeypatch.setattr(
        search,
        "get_settings",
        lambda: SimpleNamespace(ignored_issns=issns),
    )


@requires_db
async def test_ignored_issns_filter_and_cache(search_api, monkeypatch):
    r = await search_api.get("/api/v1/ut/journals")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["facets"]["publisher"]["Alpha"] == 1

    _ignore(monkeypatch, ["0000-0000"])
    body = (await search_api.get("/api/v1/ut/journals")).json()
    assert body["total"] == 1
    assert [i["issn_l"] for i in body["items"]] == ["1111-1111"]
    assert "Alpha" not in body["facets"]["publisher"]

    # cache invalidation: removing the entry restores results immediately
    _ignore(monkeypatch, [])
    body = (await search_api.get("/api/v1/ut/journals")).json()
    assert body["total"] == 2


@requires_db
async def test_clear_nullable_fields_with_null(admin_api):
    """The editor sends null to clear cap_text/summary/esac_id (P2 finding)."""
    headers = await _login(admin_api)
    deal_id = (await admin_api.get("/api/v1/admin/deals", headers=headers)).json()[0]["id"]
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}",
        headers=headers,
        json={"cap_text": None, "summary": None},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["cap_text"] is None and body["summary"] is None


@requires_db
async def test_participation_tombstone_blocks_jct(admin_api, db_engine):
    """Removing a participation records a tombstone the JCT harvester
    respects; re-adding clears it (P2 finding)."""
    from journal_browser.harvest.jct import _store_agreement
    from journal_browser.models import Deal, DealInstitution, ManualOverride

    headers = await _login(admin_api)
    deal_id = (await admin_api.get("/api/v1/admin/deals", headers=headers)).json()[0]["id"]
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/participations",
        headers=headers,
        json={"add": ["ut"]},
    )
    assert r.status_code == 200 and r.json()["participations"] == ["ut"]

    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/participations",
        headers=headers,
        json={"remove": ["ut"]},
    )
    assert r.status_code == 200 and r.json()["participations"] == []

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        deal = await session.scalar(select(Deal).where(Deal.id == deal_id))
        inst = await session.scalar(select(Institution).where(Institution.code == "ut"))
        # The exact JCT upsert path: must NOT resurrect a removed participation.
        await _store_agreement(
            session,
            {
                "esac_id": deal.esac_id or "em2019caul",
                "end_date": "",
                "ca_only": "no",
                "data_url": "https://jct.example/em",
                "last_reviewed": "",
            },
            journals=[],
            institutions=[{"ROR ID": "https://ror.org/006hf6230",
                           "Institution Name": "University of Twente",
                           "Institution First Seen": "2026", "Institution Last Seen": "2026"}],
            fetched_at="2026-10-26",
        )
        await session.commit()
        assert await session.scalar(
            select(DealInstitution).where(
                DealInstitution.deal_id == deal_id,
                DealInstitution.institution_id == inst.id,
            )
        ) is None
        assert await session.scalar(select(ManualOverride).where(
            ManualOverride.table_name == "deal_institutions",
            ManualOverride.row_key == f"{deal_id}:{inst.id}")) is not None

    # Re-add clears the tombstone.
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/participations",
        headers=headers,
        json={"add": ["ut"]},
    )
    assert r.status_code == 200 and r.json()["participations"] == ["ut"]
    async with maker() as session:
        assert await session.scalar(select(ManualOverride).where(
            ManualOverride.table_name == "deal_institutions",
            ManualOverride.row_key == f"{deal_id}:{inst.id}")) is None


@requires_db
async def test_excluded_journal_hidden_from_public_deal_counts(admin_api, db_engine):
    """Admin-excluded journals leave public deal counts and detail coverage."""
    from journal_browser.models import DealJournal

    headers = await _login(admin_api)
    deal_id = (await admin_api.get("/api/v1/admin/deals", headers=headers)).json()[0]["id"]
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/journals",
        headers=headers,
        json={"remove": ["0000-0000"]},
    )
    assert r.status_code == 200
    assert r.json()["journal_count"] == 1

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        row = await session.scalar(
            select(DealJournal).where(
                DealJournal.deal_id == deal_id, DealJournal.issn == "0000-0000"
            )
        )
        assert row.excluded is True  # removed, not deleted

    # The public list only shows deals the institution participates in.
    r = await admin_api.put(
        f"/api/v1/admin/deals/{deal_id}/participations",
        headers=headers,
        json={"add": ["ut"]},
    )
    assert r.status_code == 200

    public = await admin_api.get("/api/v1/ut/deals")
    assert public.status_code == 200
    mine = [d for d in public.json() if d["id"] == deal_id]
    assert mine and mine[0]["journal_count"] == 1


@requires_db
async def test_ignored_issns_normalized_and_validated(admin_api, tmp_path, monkeypatch):
    """Entries are ISSN-shaped on write; junk is a 400 (P3 finding)."""
    monkeypatch.setenv("JB_SETTINGS_YAML", str(tmp_path / "settings.yaml"))
    from journal_browser.config import reset_settings_cache

    reset_settings_cache()
    headers = await _login(admin_api)
    r = await admin_api.put(
        "/api/v1/admin/settings",
        headers=headers,
        json={"values": {"ignored_issns": ["12345678"]}},
    )
    assert r.status_code == 200
    assert r.json()["values"]["ignored_issns"] == ["1234-5678"]
    r = await admin_api.put(
        "/api/v1/admin/settings",
        headers=headers,
        json={"values": {"ignored_issns": ["not-an-issn"]}},
    )
    assert r.status_code == 400
    r = await admin_api.put(
        "/api/v1/admin/settings", headers=headers, json={"values": {"ignored_issns": []}}
    )
    assert r.status_code == 200
    reset_settings_cache()
