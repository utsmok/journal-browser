"""JISC normalizer: landing -> canon upserts, journal stamping, idempotency.

Uses synthetic source_records payloads shaped after the live OPF corpus
(phrases siblings included) so behavior is asserted literally.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from conftest import journal_factory, requires_db
from journal_browser.harvest.common import HarvestDataError
from journal_browser.harvest.jisc_normalize import normalize_jisc
from journal_browser.models import (
    HarvestRun,
    IssnMap,
    JiscFunder,
    JiscFunderGroup,
    JiscPolicy,
    JiscPublication,
    JiscPublisher,
    JiscRepository,
    Journal,
    SourceRecord,
)

POLICY_URI = "https://openpolicyfinder.jisc.ac.uk/publication/101"


def _pub_101() -> dict:
    """Journal matched via its issn_l; submitted route with embargo."""
    return {
        "id": 101,
        "type": "journal",
        "title": [
            {"title": "Journal One", "language": "en"},
            {"title": "Tijdschrift Een", "language": "nl"},
        ],
        "title_phrases": [{"value": "Journal"}],
        "url": "https://journalone.example",
        "listed_in_doaj": "yes",
        "issns": [{"type": "print", "issn": "1111-1111", "type_phrases": []}],
        "publishers": [
            {"relationship_type": "publisher", "publisher": {"id": 900, "name": "Example Pub"}}
        ],
        "publisher_policy": [
            {
                "id": 500,
                "open_access_prohibited": "no",
                "internal_moniker": "Standard policy",
                "urls": [
                    {
                        "url": "https://policies.example/500",
                        "description": "Policy",
                        "url_phrases": [],
                    }
                ],
                "permitted_oa": [
                    {
                        "id": 1,
                        "article_version": ["submitted"],
                        "license": [{"license": "cc_by"}],
                        "additional_oa_fee": "no",
                        "conditions": ["Deposit in any repository"],
                        "location": {
                            "location": ["any_repository"],
                            "named_repository": ["arXiv"],
                            "embargo": [{"amount_units": "12", "units": "months"}],
                        },
                    }
                ],
            }
        ],
        "system_metadata": {"date_modified": "2026-01-02 03:04:05"},
    }


def _pub_102() -> dict:
    """Same journal via a variant ISSN; accepted+published routes on a
    prohibiting policy (the OR rule)."""
    return {
        "id": 102,
        "type": "journal",
        "title": [{"title": "Journal One Online", "language": "en"}],
        "issns": [{"type": "electronic", "issn": "2222-2222"}],
        "publisher_policy": [
            {
                "id": 501,
                "open_access_prohibited": "yes",
                "internal_moniker": "Restricted",
                "urls": [],
                "permitted_oa": [
                    {
                        "id": 2,
                        "article_version": ["accepted"],
                        "license": [{"license": "cc_by_nc", "version": "4.0"}],
                        "additional_oa_fee": "yes",
                        "conditions": ["Publisher copyright notice"],
                        "location": {
                            "location": ["institutional_repository"],
                            "named_repository": ["arXiv"],
                            "embargo": [{"amount_units": "6", "units": "months"}],
                        },
                    },
                    {
                        "id": 3,
                        "article_version": ["published"],
                        "license": [{"license": "cc_by"}],
                        "additional_oa_fee": "no",
                        "conditions": [],
                        "location": {"location": ["this_journal"]},
                    },
                ],
            }
        ],
    }


def _pub_103() -> dict:
    """issn_l resolvable only through IssnMap; no journal row."""
    return {
        "id": 103,
        "type": "journal",
        "title": [{"title": "Journal Three", "language": "en"}],
        "issns": [{"type": "print", "issn": "3333-3333"}],
    }


def _pub_104() -> dict:
    """Journal whose issn_l appears in NO publication: variant-only match."""
    return {
        "id": 104,
        "type": "journal",
        "title": [{"title": "Journal Four", "language": "en"}],
        "issns": [{"type": "print", "issn": "4444-4444"}],
    }


def _expected_policy() -> dict:
    """The merged display object for journal 1111-1111 (publications 101+102)."""
    return {
        "routes": {
            "submitted": {
                "locations": ["any_repository"],
                "repositories": ["arXiv"],
                "licenses": ["cc_by"],
                "embargo_months": 12,
                "conditions": ["Deposit in any repository"],
                "additional_oa_fee": "no",
            },
            "accepted": {
                "locations": ["institutional_repository"],
                "repositories": ["arXiv"],
                "licenses": ["cc_by_nc"],
                "embargo_months": 6,
                "conditions": ["Publisher copyright notice"],
                "additional_oa_fee": "yes",
            },
            "published": {
                "locations": ["this_journal"],
                "repositories": [],
                "licenses": ["cc_by"],
                "embargo_months": None,
                "conditions": [],
                "additional_oa_fee": "no",
            },
        },
        "open_access_prohibited": True,
        "internal_moniker": "Standard policy",
        "urls": [{"url": "https://policies.example/500", "description": "Policy"}],
        "policy_uri": POLICY_URI,
    }


async def _land_corpus(db) -> dict:
    """Insert the synthetic landing corpus; returns the harvest run."""
    run = HarvestRun(source="jisc_opf", entity_type="publication", config_fingerprint="test")
    db.add(run)
    await db.flush()
    seq = {"n": 0}

    async def land(pk: int | str, entity_type: str, payload: dict, at: datetime | None = None):
        seq["n"] += 1
        db.add(
            SourceRecord(
                source="jisc_opf",
                entity_type=entity_type,
                source_pk=str(pk),
                payload=payload,
                content_hash=f"h{seq['n']}",
                harvest_run_id=run.id,
                **({"harvested_at": at} if at else {}),
            )
        )

    await land(101, "publication", _pub_101())
    await land(102, "publication", _pub_102())
    await land(103, "publication", _pub_103())
    await land(104, "publication", _pub_104())
    # Same publisher landed twice: the newer payload must win.
    await land(
        900,
        "publisher",
        {"id": 900, "name": [{"name": "Old Name", "language": "en"}], "name_phrases": []},
        at=datetime.now(UTC) - timedelta(hours=1),
    )
    await land(
        900,
        "publisher",
        {
            "id": 900,
            "name": [
                {
                    "name": "Example Publisher",
                    "language": "en",
                    "preferred": "name",
                    "name_phrases": [],
                }
            ],
            "url": "https://publisher.example",
            "country": "nl",
            "identifiers": [{"type": "ror", "identifier": "https://ror.org/0example"}],
            "publication_count": 5,
        },
    )
    await land(
        500,
        "publisher_policy",
        {
            "id": 500,
            "publisher": {"id": 900, "name": "Example Publisher"},
            "open_access_prohibited": "no",
            "internal_moniker": "Standard policy",
            "urls": [{"url": "https://policies.example/500", "description": "Policy"}],
            "permitted_oa": [{"id": 1, "article_version": ["submitted"]}],
            "publication_count": 5,
            "workflow_dates": {"policy_last_reviewed": "2026-02-06"},
        },
    )
    await land(
        700,
        "funder",
        {
            "id": 700,
            "funder_metadata": {
                "name": [{"name": "NWO", "language": "en"}],
                "url": [{"url": "https://nwo.example", "language": "en"}],
                "country": "nl",
                "identifiers": [{"type": "ror", "identifier": "https://ror.org/0nwo"}],
                "name_phrases": [],
            },
            "funder_metadata_phrases": [],
            "open_access_data_archiving_policy": {
                "requirement": "yes",
                "notes": "must deposit",
                "notes_phrases": [],
            },
            "open_access_publications_policy": {
                "archiving_policy": "can",
                "urls": [],
                "notes_phrases": ["x"],
                "policy_effective_date": "2020-01-01",
            },
        },
    )
    await land(
        800,
        "funder_group",
        {
            "id": 800,
            "funder_group_metadata": {"name": [{"name": "Coalition S", "language": "en"}]},
            "funders": [
                {
                    "id": 700,
                    "name": "NWO",
                    "type": "funder",
                    "uri": "https://nwo.example",
                    "name_phrases": [],
                }
            ],
        },
    )
    await land(
        421,
        "repository",
        {
            "id": 421,
            "repository_metadata": {
                "name": [{"name": "UT Repository", "language": "en"}],
                "type": "institutional",
                "url": "https://repo.example",
                "oai_url": "https://repo.example/oai",
                "software": {"name": "dspace", "name_phrases": []},
                "content_subjects": ["multidisciplinary"],
                "content_types": ["journal_articles"],
                "full_text_record_count": 100,
                "metadata_record_count": 200,
            },
        },
    )
    db.add(IssnMap(issn="3333-3333", issn_l="3333-3330", source="test"))
    db.add_all(
        [
            journal_factory("1111-1111", issns=["1111-1111", "2222-2222"]),
            journal_factory("4444-4440", issns=["4444-4444"]),
            journal_factory("9999-9999"),
        ]
    )
    await db.commit()
    return run


@requires_db
async def test_normalize_jisc_end_to_end(db):
    await _land_corpus(db)

    stats = await normalize_jisc(db)
    assert stats["jisc_publishers"] == 1
    assert stats["jisc_policies"] == 1
    assert stats["jisc_funders"] == 1
    assert stats["jisc_funder_groups"] == 1
    assert stats["jisc_repositories"] == 1
    assert stats["jisc_publications"] == 4
    assert stats["journals_matched"] == 2
    assert stats["embargo_present"] == 1

    # Publications: phrase-stripped fields, link ids, issn_l resolution.
    pubs = {p.id: p for p in (await db.execute(select(JiscPublication))).scalars()}
    assert set(pubs) == {101, 102, 103, 104}
    p101 = pubs[101]
    assert p101.title == "Journal One"
    assert p101.pub_type == "journal"
    assert p101.listed_in_doaj is True
    assert p101.issns == [{"type": "print", "issn": "1111-1111"}]
    assert p101.publisher_ids == [900]
    assert p101.policy_ids == [500]
    assert p101.issn_l == "1111-1111"
    assert p101.date_modified == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert pubs[102].issn_l == "1111-1111"  # variant ISSN -> journal issn_l
    assert pubs[103].issn_l == "3333-3330"  # IssnMap-only resolution
    assert pubs[104].issn_l == "4444-4440"  # variant ISSN -> that journal's issn_l

    # Publisher: the newer landing payload won; phrases stripped.
    pub900 = await db.get(JiscPublisher, 900)
    assert pub900.name == "Example Publisher"
    assert (pub900.url, pub900.country) == ("https://publisher.example", "nl")
    assert pub900.ror == "https://ror.org/0example"
    assert (pub900.publication_count, pub900.imprint_of_id) == (5, None)

    pol500 = await db.get(JiscPolicy, 500)
    assert (pol500.publisher_id, pol500.open_access_prohibited) == (900, False)
    assert pol500.internal_moniker == "Standard policy"
    assert pol500.permitted_oa == [{"id": 1, "article_version": ["submitted"]}]
    assert pol500.workflow_dates == {"policy_last_reviewed": "2026-02-06"}

    funder = await db.get(JiscFunder, 700)
    assert funder.name == "NWO"
    assert funder.url == "https://nwo.example"
    # Literal stripped shape: the notes_phrases sibling is gone.
    assert funder.publications_policy == {
        "archiving_policy": "can",
        "urls": [],
        "policy_effective_date": "2020-01-01",
    }
    assert funder.data_archiving_policy == {"requirement": "yes", "notes": "must deposit"}

    group = await db.get(JiscFunderGroup, 800)
    assert group.name == "Coalition S"
    assert group.funders == [
        {"id": 700, "name": "NWO", "type": "funder", "uri": "https://nwo.example"}
    ]

    repo = await db.get(JiscRepository, 421)
    assert repo.name == "UT Repository"
    assert repo.software == "dspace"
    assert repo.content_subjects == ["multidisciplinary"]
    assert (repo.full_text_record_count, repo.metadata_record_count) == (100, 200)

    # Journal 1111-1111: publications 101+102 merged into one display object.
    j = await db.get(Journal, "1111-1111")
    assert j.jisc_in_opf is True
    assert j.jisc_oa_prohibited is True  # policy 501 prohibits: OR across merges
    assert j.jisc_sherpa_id == 101
    assert (j.jisc_allows_sa_submitted, j.jisc_allows_sa_accepted, j.jisc_allows_sa_published) == (
        True,
        True,
        True,
    )
    assert j.jisc_embargo_accepted_months == 6
    assert j.jisc_policy == _expected_policy()
    assert j.jisc_harvested_at is not None

    # Journal 4444-4440 matched purely via its variant ISSN 4444-4444.
    j4 = await db.get(Journal, "4444-4440")
    assert j4.jisc_in_opf is True
    assert j4.jisc_sherpa_id == 104
    assert j4.jisc_allows_sa_submitted is False
    assert j4.jisc_allows_sa_accepted is False
    assert j4.jisc_allows_sa_published is False
    assert j4.jisc_policy["policy_uri"] == "https://openpolicyfinder.jisc.ac.uk/publication/104"

    # Never swept journal stays NULL (tri-state: NULL = no OPF match).
    assert (await db.get(Journal, "9999-9999")).jisc_in_opf is None

    # Idempotent rerun: same stats, same stamped values, no row growth.
    stats2 = await normalize_jisc(db)
    assert {k: v for k, v in stats2.items() if not k.startswith("records_")} == {
        k: v for k, v in stats.items() if not k.startswith("records_")
    }
    assert len((await db.execute(select(JiscPublication))).scalars().all()) == 4
    assert (await db.get(Journal, "1111-1111")).jisc_policy == _expected_policy()


@requires_db
async def test_normalize_jisc_fails_on_empty_landing(db):
    with pytest.raises(HarvestDataError, match="no jisc_opf source_records"):
        await normalize_jisc(db)
