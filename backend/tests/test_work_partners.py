"""Outcome tests for the work_partners derive: the payload extraction and
the per-institution rebuild (jobs/derive_work_partners.py)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update

from conftest import requires_db
from journal_browser.harvest import work_partners
from journal_browser.harvest.work_partners import (
    derive_work_partners,
    openaire_partners,
    openalex_partners,
)
from journal_browser.models import (
    HarvestRun,
    PartnerInstitution,
    SourceRecord,
    Work,
    WorkIdentity,
    WorkPartner,
)

HOME = "I94624287"
HOME_ROR = "006hf6230"


def _inst(iid: str, ror: str | None, *, lineage: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "id": f"https://openalex.org/{iid}",
        "ror": f"https://ror.org/{ror}" if ror else None,
        "type": "education",
        "lineage": [f"https://openalex.org/{x}" for x in lineage],
        "country_code": "NL",
        "display_name": f"Org {iid}",
    }


def _org(ror: str, name: str) -> dict[str, Any]:
    return {
        "id": f"openorgs____::{ror}",
        "pids": [{"scheme": "ROR", "value": f"https://ror.org/{ror}"}],
        "legalName": name,
        "countries": [{"code": "XX", "label": "Nowhere"}],
    }


def test_openalex_partners_skip_home_lineage_and_entries_without_ror():
    payload = {
        "authorships": [
            {"institutions": [_inst(HOME, HOME_ROR, lineage=(HOME,))], "is_corresponding": True},
            {"institutions": [_inst("I4387152645", "038v7xb98", lineage=(HOME, "I4387152645"))]},
            {
                "institutions": [_inst("I555", "01x111111", lineage=("I555",))],
                "is_corresponding": True,
            },
            {"institutions": [_inst("I555", "01x111111")], "is_corresponding": False},
            {"institutions": [_inst("I777", None)]},
        ]
    }

    partners, home_rors, without_ror, home_entries = openalex_partners(payload, HOME)

    assert list(partners) == ["01x111111"]
    assert partners["01x111111"] == {
        "name": "Org I555",
        "org_type": "education",
        "country_code": "NL",
        "openalex_id": "I555",
        "authorships": 2,
        "corresponding": True,
    }
    # The home institution and its child are left out; the child's ROR id
    # is remembered for the OpenAIRE pass.
    assert home_rors == {HOME_ROR, "038v7xb98"}
    assert (without_ror, home_entries) == (1, 2)


def test_openalex_partners_without_home_id_keep_every_ror():
    payload = {"authorships": [{"institutions": [_inst(HOME, HOME_ROR, lineage=(HOME,))]}]}

    partners, home_rors, _without_ror, home_entries = openalex_partners(payload, None)

    assert list(partners) == [HOME_ROR]
    assert (home_rors, home_entries) == (set(), 0)


def test_openaire_partners_need_a_ror_pid_and_skip_home():
    payload = {
        "organizations": [
            {
                **_org("012p63287", "University of Barcelona"),
                "pids": [
                    {"scheme": "Wikidata", "value": "Q42"},
                    {"scheme": "ROR", "value": "https://ror.org/012p63287"},
                ],
            },
            {"id": "pending_org_::9", "pids": None, "acronym": "Unresolved", "countries": []},
            _org(HOME_ROR, "University of Twente"),
        ]
    }

    partners = openaire_partners(payload, {HOME_ROR})

    assert list(partners) == ["012p63287"]
    assert partners["012p63287"] == {
        "name": "University of Barcelona",
        "org_type": None,
        "country_code": "XX",
        "openalex_id": None,
        "authorships": 1,
        "corresponding": False,
    }


async def _seed(db, ut) -> list[SourceRecord]:
    run = HarvestRun(
        source="openalex",
        entity_type="work",
        institution_id=ut.id,
        status="completed",
        config_fingerprint="test",
    )
    db.add(run)
    await db.flush()
    db.add_all(
        Work(
            institution_id=ut.id,
            pure_uuid=f"w{n}",
            title=f"Work {n}",
            norm_title=f"work {n}",
            year=2024,
            first_seen_run=run.id,
            last_seen_run=run.id,
        )
        for n in (1, 2, 3, 4)
    )
    db.add_all(
        WorkIdentity(
            institution_id=ut.id,
            source=source,
            source_pk=pk,
            work_id=work,
            matched_by="doi",
            status="confirmed",
        )
        for source, pk, work in (
            ("openalex", "https://openalex.org/W1", "w1"),
            ("openalex", "https://openalex.org/W3", "w3"),
            # w4 has an identity but no stored payload.
            ("openalex", "https://openalex.org/W4", "w4"),
            ("openaire", "oa::w1", "w1"),
            ("openaire", "oa::w2", "w2"),
            ("openaire", "oa::w3", "w3"),
        )
    )
    t0 = datetime(2026, 11, 1, tzinfo=UTC)
    home_only = {"authorships": [{"institutions": [_inst(HOME, HOME_ROR, lineage=(HOME,))]}]}
    records = [
        ("openalex", "https://openalex.org/W1", old_w1, t0),
        ("openalex", "https://openalex.org/W1", new_w1, t0 + timedelta(hours=1)),
        ("openalex", "https://openalex.org/W3", home_only, t0),
        # w1 has OpenAlex partners, so its OpenAIRE record is never read.
        ("openaire", "oa::w1", {"organizations": [_org("01x999999", "Never used")]}, t0),
        ("openaire", "oa::w2", {"organizations": [_org("013aaaaaa", "Uni Two")]}, t0),
        (
            "openaire",
            "oa::w3",
            {
                "organizations": [
                    _org(HOME_ROR, "University of Twente"),
                    _org("012p63287", "Uni Three"),
                ]
            },
            t0,
        ),
    ]
    added = [
        SourceRecord(
            source=source,
            entity_type="work",
            source_pk=pk,
            payload=payload,
            content_hash=f"h-{n}",
            harvested_at=at,
            harvest_run_id=run.id,
        )
        for n, (source, pk, payload, at) in enumerate(records)
    ]
    db.add_all(added)
    await db.flush()
    return added


old_w1 = {"authorships": [{"institutions": [_inst("I1", "01x000001")]}]}
new_w1 = {"authorships": [{"institutions": [_inst("I2", "01x000002")], "is_corresponding": True}]}


async def _rows(db) -> list[tuple]:
    rows = (
        (await db.execute(select(WorkPartner).order_by(WorkPartner.work_pure_uuid))).scalars().all()
    )
    return [
        (
            r.work_pure_uuid,
            r.partner_ror,
            r.source,
            r.corresponding,
            r.authorships,
            r.partner_openalex_id,
        )
        for r in rows
    ]


@requires_db
async def test_derive_rebuilds_rows_and_stubs_idempotently(db, institution_factory, monkeypatch):
    """OpenAlex wins per work and per version, OpenAIRE fills the rest,
    stubs never overwrite a ROR record, and a rerun replaces stale rows."""
    monkeypatch.setattr(work_partners, "STREAM_PARTITION", 1)
    monkeypatch.setattr(work_partners, "INSERT_CHUNK", 2)
    ut = await institution_factory(
        code="ut",
        openalex_id=f"https://openalex.org/{HOME}",
        ror=f"https://ror.org/{HOME_ROR}",
    )
    records = await _seed(db, ut)
    # A partner the ROR harvest already filled keeps its record.
    db.add(
        PartnerInstitution(
            ror="01x000002",
            name="ROR name",
            org_type="education",
            country_code="DE",
            city="Berlin",
            lat=1.0,
            lng=2.0,
            payload={"id": "https://ror.org/01x000002"},
        )
    )
    await db.flush()

    stats = await derive_work_partners(db)

    assert stats["works"] == 4
    assert stats["openalex_works_with_partner"] == 1
    assert stats["openaire_works_with_partner"] == 2
    assert stats["works_without_partner"] == 1
    assert stats["partners"] == 3
    expected = [
        ("w1", "01x000002", "openalex", True, 1, "I2"),
        ("w2", "013aaaaaa", "openaire", False, 1, None),
        ("w3", "012p63287", "openaire", False, 1, None),
    ]
    assert await _rows(db) == expected
    db.expire_all()
    partners = {p.ror: p for p in (await db.execute(select(PartnerInstitution))).scalars().all()}
    assert set(partners) == {"01x000002", "013aaaaaa", "012p63287"}
    filled = partners["01x000002"]
    # ROR's name and place stay; the stub fills only the missing OpenAlex id.
    assert (filled.name, filled.city, filled.openalex_id) == ("ROR name", "Berlin", "I2")
    assert partners["013aaaaaa"].name == "Uni Two"
    assert partners["012p63287"].country_code == "XX"

    # The newest W1 version disappears: the rerun drops its partner row.
    await db.delete(records[1])
    await db.flush()
    again = await derive_work_partners(db)

    assert again["openalex_works_with_partner"] == 1
    assert (await _rows(db))[0] == ("w1", "01x000001", "openalex", False, 1, "I1")
    assert len(await _rows(db)) == 3


@requires_db
async def test_stub_rerun_leaves_the_ror_record_age_alone(db, institution_factory):
    """harvest_ror fetches a stored ROR record again once it is 30 days
    old. A derive run stamps a partner only when the stub gives it a value
    it lacked; a rerun that changes nothing leaves the stamp, so the
    monthly refresh still finds the record."""
    ut = await institution_factory(
        code="ut",
        openalex_id=f"https://openalex.org/{HOME}",
        ror=f"https://ror.org/{HOME_ROR}",
    )
    await _seed(db, ut)
    fetched_in_october = datetime.now(UTC) - timedelta(days=40)
    db.add(
        PartnerInstitution(
            ror="01x000002",
            name="ROR name",
            payload={"id": "https://ror.org/01x000002"},
            updated_at=fetched_in_october,
        )
    )
    await db.flush()
    stale = select(PartnerInstitution.ror).where(
        PartnerInstitution.updated_at < func.now() - timedelta(days=30)
    )

    await derive_work_partners(db)  # the stub adds the OpenAlex id: stamped
    assert "01x000002" not in (await db.execute(stale)).scalars()

    # Forty days later nothing is left to gain.
    await db.execute(
        update(PartnerInstitution)
        .where(PartnerInstitution.ror == "01x000002")
        .values(updated_at=fetched_in_october)
    )
    await db.commit()
    await derive_work_partners(db)
    assert (await db.execute(stale)).scalars().all() == ["01x000002"]
