"""Global publication-year filter on the detail views: journal detail
(UT authorship, OpenAIRE matches, the canonical institution metrics and
the CRIS gap narrow to the clamped range while the OpenAlex-side venue
metrics keep the data window), publisher detail (header works sum +
journal table works column via the scoped snapshot/base_query swap,
journal attributes stay) and orgunit detail (unit header, member authors'
n_works, deal-usage work set; euro math follows the narrowed work set,
works_by_year stays full-window rows). No params: byte-identical default
serving; from > to answers 400."""

from urllib.parse import quote

import pytest

from conftest import journal_factory, requires_db
from journal_browser.models import (
    ApcEvidence,
    Author,
    AuthorWork,
    HarvestRun,
    InstitutionWorksStats,
    JournalFlags,
    OpenalexWork,
    Work,
    WorkIdentity,
    WorkPureAuthor,
)

TNW = "Faculty of Science and Technology"
GROUP = "Quantum Matter"
MAIN = "AAAA-AAAA"  # Alpha Group, deal-covered
OTHER = "BBBB-BBBB"  # Beta House
ALPHA = "Alpha Group"

WINDOW_START = 2020
WINDOW_END = 2024


def _stat(inst_id, issn_l, year, n, source="pure_canon"):
    return InstitutionWorksStats(
        institution_id=inst_id, issn_l=issn_l, year=year, works_count=n, source=source
    )


@pytest.fixture
async def details_api(client, db, institution_factory):
    """ut (window 2020-2024): deal-covered journal MAIN (Alpha Group) with
    pure_canon stats 2021:4 + 2023:6, two Pure works (2021 + 2023) by one
    confirmed TNW author, store rows for both (one retracted, FWCI-carrying)
    plus two DOI-free gap rows on each venue (2021 + 2023, author-tagged),
    an OpenAIRE identity per Pure work, and APC evidence on the 2021 work's
    DOI only. OTHER (Beta House) keeps the gap-venue population separate."""
    ut = await institution_factory(
        code="ut", data_window_start=WINDOW_START, data_window_end=WINDOW_END
    )
    db.add_all(
        [
            journal_factory(MAIN, publisher_name=ALPHA),
            journal_factory(OTHER, publisher_name="Beta House"),
        ]
    )
    await db.flush()
    db.add_all(
        [
            JournalFlags(
                institution_id=ut.id,
                issn_l=MAIN,
                works_count=10,
                works_window_plus=10,
                deal_covered=True,
            ),
            JournalFlags(institution_id=ut.id, issn_l=OTHER, works_count=3, works_window_plus=10),
        ]
    )
    db.add_all([_stat(ut.id, MAIN, 2021, 4), _stat(ut.id, MAIN, 2023, 6)])

    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()

    def _work(uuid, year):
        return Work(
            institution_id=ut.id,
            pure_uuid=uuid,
            title=f"Work {uuid}",
            norm_title=f"work {uuid}",
            year=year,
            doi_normalized=f"10.0.0/{uuid}",
            work_type="info:eu-repo/semantics/article",
            journal_issn_l=MAIN,
            first_seen_run=run.id,
            last_seen_run=run.id,
        )

    db.add_all([_work("pw2021", 2021), _work("pw2023", 2023)])
    db.add(
        Author(
            institution_id=ut.id,
            pure_uuid="author-1",
            name="Test Author",
            faculty=TNW,
            research_group=GROUP,
            confirmed=True,
            openalex_ids=["a1111111111"],
            n_works=2,
            primary_topic="Quantum Chemistry",
        )
    )
    await db.flush()
    db.add_all(
        [
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="pw2021", person_uuid="author-1"),
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="pw2023", person_uuid="author-1"),
            AuthorWork(institution_id=ut.id, author_pure_uuid="author-1", work_pure_uuid="pw2021"),
            AuthorWork(institution_id=ut.id, author_pure_uuid="author-1", work_pure_uuid="pw2023"),
            WorkIdentity(
                institution_id=ut.id,
                source="openaire",
                source_pk="O1",
                work_id="pw2021",
                matched_by="doi",
            ),
            WorkIdentity(
                institution_id=ut.id,
                source="openaire",
                source_pk="O2",
                work_id="pw2023",
                matched_by="doi",
            ),
            # APC evidence attaches to the 2021 work's DOI only (latest
            # period), so a 2023+ range narrows the euro sum to zero.
            ApcEvidence(institution_id=ut.id, doi="10.0.0/pw2021", period=2024, euro=50),
            # Store rows: the Pure-matched pair (enrichment) and the DOI-free
            # gap pair per venue, author-tagged so the org-unit gap query
            # sees them too.
            OpenalexWork(
                institution_id=ut.id,
                w_id="W1",
                doi_normalized="10.0.0/pw2021",
                title="Matched Old",
                year=2021,
                work_type="article",
                oa_status="gold",
                venue_issn_l=MAIN,
                venue_name="Journal AAAA",
                cited_by_count=5,
                fwci=1.5,
                source="works_stats",
            ),
            OpenalexWork(
                institution_id=ut.id,
                w_id="W2",
                doi_normalized="10.0.0/pw2023",
                title="Matched New",
                year=2023,
                work_type="article",
                oa_status="closed",
                venue_issn_l=MAIN,
                venue_name="Journal AAAA",
                cited_by_count=9,
                fwci=2.0,
                is_retracted=True,
                source="works_stats",
            ),
            OpenalexWork(
                institution_id=ut.id,
                w_id="W5",
                title="Gap Old",
                year=2021,
                work_type="article",
                venue_issn_l=MAIN,
                venue_name="Journal AAAA",
                authorships=[{"a": "A1111111111", "n": "Test Author"}],
                source="works_stats",
            ),
            OpenalexWork(
                institution_id=ut.id,
                w_id="W6",
                title="Gap New",
                year=2023,
                work_type="article",
                venue_issn_l=MAIN,
                venue_name="Journal AAAA",
                authorships=[{"a": "A1111111111", "n": "Test Author"}],
                source="works_stats",
            ),
            OpenalexWork(
                institution_id=ut.id,
                w_id="W3",
                title="Beta Gap Old",
                year=2021,
                work_type="article",
                venue_issn_l=OTHER,
                venue_name="Journal BBBB",
                authorships=[{"a": "A1111111111", "n": "Test Author"}],
                source="works_stats",
            ),
            OpenalexWork(
                institution_id=ut.id,
                w_id="W4",
                title="Beta Gap New",
                year=2023,
                work_type="article",
                venue_issn_l=OTHER,
                venue_name="Journal BBBB",
                authorships=[{"a": "A1111111111", "n": "Test Author"}],
                source="works_stats",
            ),
        ]
    )
    await db.commit()
    return client


# --- Journal detail ---


@requires_db
async def test_journal_detail_default_full_window(details_api):
    """No params and the window-covering range serve identical detail
    sections; the numbers are the pre-filter behavior."""
    client = details_api
    default = (await client.get(f"/api/v1/ut/journals/{MAIN}")).json()
    clamped = (
        await client.get(
            f"/api/v1/ut/journals/{MAIN}",
            params={"year_from": WINDOW_START, "year_to": WINDOW_END},
        )
    ).json()
    for section in ("ut_authorship", "openalex_only", "openaire", "institution_metrics"):
        assert default[section] == clamped[section], section
    assert default["ut_authorship"]["n_ut_works"] == 2
    assert default["openaire"]["matched_works"] == 2
    assert default["openalex_only"]["total"] == 2
    assert default["institution_metrics"]["canonical_total"] == 2


@requires_db
async def test_journal_detail_works_sections_scoped(details_api):
    """2023+: UT authorship, OpenAIRE matches, the CRIS gap and the
    canonical metrics narrow to the in-range works."""
    client = details_api
    body = (await client.get(f"/api/v1/ut/journals/{MAIN}", params={"year_from": 2023})).json()
    authorship = body["ut_authorship"]
    assert authorship["n_ut_works"] == 1
    assert authorship["faculties"] == [{"name": TNW, "works": 1}]
    assert authorship["research_groups"] == [{"name": GROUP, "works": 1}]
    assert [a["works"] for a in authorship["top_authors"]] == [1]
    assert body["openaire"]["matched_works"] == 1
    assert body["openalex_only"]["total"] == 1
    assert [i["title"] for i in body["openalex_only"]["items"]] == ["Gap New"]
    metrics = body["institution_metrics"]
    assert metrics["canonical_total"] == 1
    assert metrics["canonical_retracted"] == 1
    assert metrics["canonical_oa"]["closed"] == 1
    assert metrics["canonical_oa"]["gold"] == 0


@requires_db
async def test_journal_detail_venue_metrics_keep_window(details_api):
    """The OpenAlex-side venue metrics stay the data-window cross-check
    under an active range (registry convention)."""
    client = details_api
    default = (await client.get(f"/api/v1/ut/journals/{MAIN}")).json()
    scoped = (await client.get(f"/api/v1/ut/journals/{MAIN}", params={"year_from": 2023})).json()
    for key in ("openalex_matched", "fwci_avg", "fwci_n", "retracted", "cited_total"):
        assert scoped["institution_metrics"][key] == default["institution_metrics"][key], key
    assert default["institution_metrics"]["fwci_n"] == 2
    assert default["institution_metrics"]["cited_total"] == 14


@requires_db
async def test_journal_detail_from_after_to_is_400(details_api):
    response = await details_api.get(
        f"/api/v1/ut/journals/{MAIN}", params={"year_from": 2023, "year_to": 2021}
    )
    assert response.status_code == 400


# --- Publisher detail ---


@requires_db
async def test_publisher_detail_scoped(details_api):
    """2023+: the header works sum and the journal table's works column
    swap to the year-scoped pure_canon sums; journal counts and deal
    attributes stay, and the default matches the full-window range."""
    client = details_api
    name = quote(ALPHA)
    default = (await client.get(f"/api/v1/ut/publishers/{name}")).json()
    clamped = (
        await client.get(
            f"/api/v1/ut/publishers/{name}",
            params={"year_from": WINDOW_START, "year_to": WINDOW_END},
        )
    ).json()
    assert default["publisher"]["n_works"] == clamped["publisher"]["n_works"] == 10
    assert default["journals"][0]["works"] == clamped["journals"][0]["works"] == 10

    scoped = (
        await client.get(
            f"/api/v1/ut/publishers/{name}", params={"year_from": 2023, "year_to": 2024}
        )
    ).json()
    assert scoped["publisher"]["n_works"] == 6  # 2023 pure_canon sum
    assert scoped["publisher"]["n_journals"] == 1  # attribute stays
    assert scoped["publisher"]["deal_journals"] == 1  # attribute stays
    assert scoped["journals"][0]["issn_l"] == MAIN
    assert scoped["journals"][0]["works"] == 6


@requires_db
async def test_publisher_detail_from_after_to_is_400(details_api):
    response = await details_api.get(
        f"/api/v1/ut/publishers/{quote(ALPHA)}", params={"year_from": 2023, "year_to": 2021}
    )
    assert response.status_code == 400


# --- Orgunit detail ---


@requires_db
async def test_orgunit_detail_default_unchanged(details_api):
    """No params: snapshot header, denormalized member counts, full-window
    deal usage — exactly the pre-filter behavior."""
    client = details_api
    body = (await client.get(f"/api/v1/ut/orgunits/faculty/{quote(TNW)}")).json()
    unit = body["unit"]
    assert unit["n_authors"] == 1
    assert unit["n_works"] == 2
    assert unit["deal_works"] == 2
    assert unit["apc_euro_total"] == 50.0  # APC rollup stays evidence-based
    assert unit["apc_n"] == 1
    assert body["authors"] == [
        {
            "pure_uuid": "author-1",
            "name": "Test Author",
            "n_works": 2,
            "orcid": None,
            "primary_topic": "Quantum Chemistry",
        }
    ]
    assert body["deal_usage"] == [{"label": ALPHA, "n_works": 2, "euro": 50.0}]
    assert [j["n_works"] for j in body["journals"]] == [2]
    assert [row["year"] for row in body["works_by_year"]] == [2023, 2021]  # full window


@requires_db
async def test_orgunit_detail_scoped(details_api):
    """2023+: the unit header, member n_works, venues and the deal-usage
    work set narrow to the in-range works; euro follows the narrowed set
    (the 2021 DOI's evidence drops out) and works_by_year stays
    full-window rows for the client to filter."""
    client = details_api
    body = (
        await client.get(f"/api/v1/ut/orgunits/faculty/{quote(TNW)}", params={"year_from": 2023})
    ).json()
    unit = body["unit"]
    assert unit["n_authors"] == 1
    assert unit["n_works"] == 1
    assert unit["deal_works"] == 1
    assert unit["apc_euro_total"] == 50.0  # attribute rollup stays snapshot
    assert body["authors"][0]["n_works"] == 1
    assert [j["n_works"] for j in body["journals"]] == [1]
    assert body["deal_usage"] == [{"label": ALPHA, "n_works": 1, "euro": 0.0}]
    assert [row["year"] for row in body["works_by_year"]] == [2023, 2021]
    # The member-author gap spans venues: the two in-range DOI-free rows
    # (MAIN + OTHER), regardless of venue.
    assert body["openalex_only"]["total"] == 2


@requires_db
async def test_orgunit_detail_from_after_to_is_400(details_api):
    response = await details_api.get(
        f"/api/v1/ut/orgunits/faculty/{quote(TNW)}", params={"year_from": 2023, "year_to": 2021}
    )
    assert response.status_code == 400
