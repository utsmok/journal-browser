"""Global publication-year filter (year_from/year_to): year-scoped
per-journal UT works counts on the search list, institution_works sort and
has_works facet; works tab, gap lists, author profile and CSV exports.

The year-scoped count sums institution_works_stats pure_canon rows — the
same pipeline the denormalized journal_flags.works_count column mirrors
(harvest.denorm WORKS_COUNT_SQL) — so the clamped full window reproduces
the column exactly and the openalex_institution_filter rows never fill the
count. Journal attributes (oa_type, deals, corpus cutoff) stay unfiltered;
from > to answers 400; the facet cache key carries the active range."""

import csv
import io

import pytest

from conftest import journal_factory, requires_db
from journal_browser.models import (
    Author,
    AuthorWork,
    HarvestRun,
    InstitutionWorksStats,
    JournalFlags,
    OpenalexWork,
    Work,
)

WINDOW_START = 2020
WINDOW_END = 2024
FACULTY = "Faculty of Science and Technology"

#: issn prefix -> (flags.works_count, {year: pure_canon count}). ISSNs
#: uppercase: the works/CSV routes resolve the path param via .upper().
JOURNALS = {
    "AAAA-AAAA": (10, {2021: 4, 2023: 6}),
    "BBBB-BBBB": (3, {2023: 3}),
    "CCCC-CCCC": (1, {2021: 1}),
    "DDDD-DDDD": (2, {2022: 2}),
    # The OpenAlex cross-check rows never fill the count (pure_canon
    # primary, exactly like the denormalized column).
    "EEEE-EEEE": (0, {}),
}


def _stat(inst_id, issn_l, year, n, source="pure_canon"):
    return InstitutionWorksStats(
        institution_id=inst_id, issn_l=issn_l, year=year, works_count=n, source=source
    )


def _store_work(inst_id, w_id, *, year, venue="AAAA-AAAA", doi=None, authorships=()):
    return OpenalexWork(
        institution_id=inst_id,
        w_id=w_id,
        doi_normalized=doi,
        title=f"Store work {w_id}",
        year=year,
        work_type="article",
        oa_status="gold",
        venue_issn_l=venue,
        venue_name="Journal One",
        authorships=list(authorships),
        source="works_stats",
    )


@pytest.fixture
async def year_api(client, db, institution_factory):
    """ut (window 2020-2024) with journals whose pure_canon stats rows sum
    to the denormalized flags counts, plus works-table/store rows for the
    works-tab, gap and author-profile paths."""
    ut = await institution_factory(
        code="ut", data_window_start=WINDOW_START, data_window_end=WINDOW_END
    )
    db.add_all(journal_factory(issn) for issn in JOURNALS)
    await db.flush()
    db.add_all(
        JournalFlags(
            institution_id=ut.id,
            issn_l=issn,
            works_count=count,
            works_window_plus=10,
        )
        for issn, (count, _by_year) in JOURNALS.items()
    )
    db.add_all(
        _stat(ut.id, issn, year, n)
        for issn, (_count, by_year) in JOURNALS.items()
        for year, n in by_year.items()
    )
    # Cross-check source only: stays out of every works count.
    db.add(_stat(ut.id, "EEEE-EEEE", 2022, 5, source="openalex_institution_filter"))

    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()

    def _work(uuid, year, doi=None):
        return Work(
            institution_id=ut.id,
            pure_uuid=uuid,
            title=f"Work {uuid}",
            norm_title=f"work {uuid}",
            year=year,
            doi_normalized=doi,
            work_type="info:eu-repo/semantics/article",
            journal_issn_l="AAAA-AAAA",
            first_seen_run=run.id,
            last_seen_run=run.id,
        )

    db.add_all(
        [
            _work("w2021", 2021, doi="10.0.0/w2021"),
            _work("w2023", 2023, doi="10.0.0/w2023"),
        ]
    )
    await db.flush()
    db.add(
        Author(
            institution_id=ut.id,
            pure_uuid="author-1",
            name="Test Author",
            faculty=FACULTY,
            confirmed=True,
            openalex_ids=["a1111111111"],
            n_works=2,
            # orgunit_detail reads the unit topic distribution from
            # authors.primary_topic; without one the unit has no entry.
            primary_topic="Quantum Chemistry",
        )
    )
    db.add_all(
        [
            AuthorWork(
                institution_id=ut.id,
                author_pure_uuid="author-1",
                work_pure_uuid="w2021",
            ),
            AuthorWork(
                institution_id=ut.id,
                author_pure_uuid="author-1",
                work_pure_uuid="w2023",
            ),
            # CRIS-gap store rows: DOI-free so the anti-join keeps them;
            # one inside a 2022+ range, one before it. The author-attributed
            # pair sits on another venue so the journal gap CSV stays the
            # W1/W2 population.
            _store_work(ut.id, "W1", year=2021),
            _store_work(ut.id, "W2", year=2023),
            _store_work(
                ut.id,
                "W3",
                year=2021,
                venue="BBBB-BBBB",
                authorships=[{"a": "A1111111111", "n": "Test Author"}],
            ),
            _store_work(
                ut.id,
                "W4",
                year=2023,
                venue="BBBB-BBBB",
                authorships=[{"a": "A1111111111", "n": "Test Author"}],
            ),
        ]
    )
    await db.commit()
    return client


def _works_by_issn(body: dict) -> dict[str, int]:
    return {item["issn_l"]: item["works"] for item in body["items"]}


def _csv_years(text: str) -> list[str]:
    rows = list(csv.reader(io.StringIO(text)))
    year_col = rows[0].index("publication_year")
    return sorted(row[year_col] for row in rows[1:] if row)


@requires_db
async def test_full_window_sums_match_denormalized(year_api):
    """No params (default) and the window-covering range describe the same
    counts as the denormalized column."""
    full = (await year_api.get("/api/v1/ut/journals", params={"include_facets": "false"})).json()
    clamped = (
        await year_api.get(
            "/api/v1/ut/journals",
            params={"include_facets": "false", "year_from": WINDOW_START, "year_to": WINDOW_END},
        )
    ).json()
    expected = {issn: count for issn, (count, _by_year) in JOURNALS.items()}
    assert _works_by_issn(full) == expected
    assert _works_by_issn(clamped) == expected


@requires_db
async def test_narrowed_range_year_sums_items(year_api):
    r2023 = (
        await year_api.get(
            "/api/v1/ut/journals", params={"include_facets": "false", "year_from": 2023}
        )
    ).json()
    assert _works_by_issn(r2023) == {
        "AAAA-AAAA": 6,
        "BBBB-BBBB": 3,
        "CCCC-CCCC": 0,
        "DDDD-DDDD": 0,
        "EEEE-EEEE": 0,
    }
    r_21_22 = (
        await year_api.get(
            "/api/v1/ut/journals",
            params={"include_facets": "false", "year_from": 2021, "year_to": 2022},
        )
    ).json()
    assert _works_by_issn(r_21_22) == {
        "AAAA-AAAA": 4,
        "BBBB-BBBB": 0,
        "CCCC-CCCC": 1,
        "DDDD-DDDD": 2,
        "EEEE-EEEE": 0,
    }


@requires_db
async def test_institution_works_sort_year_scoped(year_api):
    top_2023 = (
        await year_api.get(
            "/api/v1/ut/journals",
            params={"sort": "institution_works", "include_facets": "false", "year_from": 2023},
        )
    ).json()
    assert [i["issn_l"] for i in top_2023["items"][:2]] == ["AAAA-AAAA", "BBBB-BBBB"]
    top_21_22 = (
        await year_api.get(
            "/api/v1/ut/journals",
            params={
                "sort": "institution_works",
                "include_facets": "false",
                "year_from": 2021,
                "year_to": 2022,
            },
        )
    ).json()
    assert [i["issn_l"] for i in top_21_22["items"][:3]] == ["AAAA-AAAA", "DDDD-DDDD", "CCCC-CCCC"]
    assert [i["works"] for i in top_21_22["items"][:3]] == [4, 2, 1]


@requires_db
async def test_has_works_facet_year_scoped(year_api):
    """The facet splits on the year-scoped counts, in both request orders
    (the cache key must distinguish the ranges)."""
    default_first = (
        await year_api.get("/api/v1/ut/journals", params={"include_facets": "true"})
    ).json()["facets"]["works"]
    assert default_first == {"true": 4, "false": 1}
    r2023 = (
        await year_api.get(
            "/api/v1/ut/journals", params={"include_facets": "true", "year_from": 2023}
        )
    ).json()["facets"]["works"]
    assert r2023 == {"true": 2, "false": 3}
    r_21_22 = (
        await year_api.get(
            "/api/v1/ut/journals",
            params={"include_facets": "true", "year_from": 2021, "year_to": 2022},
        )
    ).json()["facets"]["works"]
    assert r_21_22 == {"true": 3, "false": 2}
    # Back to the default view: must not serve a ranged cache entry.
    default_again = (
        await year_api.get("/api/v1/ut/journals", params={"include_facets": "true"})
    ).json()["facets"]["works"]
    assert default_again == {"true": 4, "false": 1}


@requires_db
async def test_has_works_filter_year_scoped(year_api):
    r2023 = (
        await year_api.get(
            "/api/v1/ut/journals",
            params={"has_works": "true", "include_facets": "false", "year_from": 2023},
        )
    ).json()
    assert {i["issn_l"] for i in r2023["items"]} == {"AAAA-AAAA", "BBBB-BBBB"}
    r_21_22 = (
        await year_api.get(
            "/api/v1/ut/journals",
            params={
                "has_works": "true",
                "include_facets": "false",
                "year_from": 2021,
                "year_to": 2022,
            },
        )
    ).json()
    assert {i["issn_l"] for i in r_21_22["items"]} == {"AAAA-AAAA", "CCCC-CCCC", "DDDD-DDDD"}


@requires_db
async def test_year_params_clamp_to_window(year_api):
    full = {issn: count for issn, (count, _by_year) in JOURNALS.items()}
    wide = (
        await year_api.get(
            "/api/v1/ut/journals",
            params={"include_facets": "false", "year_from": 1900, "year_to": 2100},
        )
    ).json()
    assert _works_by_issn(wide) == full
    below = (
        await year_api.get(
            "/api/v1/ut/journals", params={"include_facets": "false", "year_from": 2019}
        )
    ).json()
    assert _works_by_issn(below) == full
    above = (
        await year_api.get(
            "/api/v1/ut/journals",
            params={"include_facets": "false", "year_from": 2022, "year_to": 2030},
        )
    ).json()
    assert _works_by_issn(above) == {
        "AAAA-AAAA": 6,
        "BBBB-BBBB": 3,
        "CCCC-CCCC": 0,
        "DDDD-DDDD": 2,
        "EEEE-EEEE": 0,
    }


@requires_db
async def test_from_after_to_is_400(year_api):
    response = await year_api.get(
        "/api/v1/ut/journals", params={"year_from": 2023, "year_to": 2021}
    )
    assert response.status_code == 400


@requires_db
async def test_works_tab_year_scoped(year_api):
    default = (await year_api.get("/api/v1/ut/journals/AAAA-AAAA/works")).json()
    assert default["total"] == 2
    narrowed = (
        await year_api.get("/api/v1/ut/journals/AAAA-AAAA/works", params={"year_from": 2022})
    ).json()
    assert narrowed["total"] == 1
    assert narrowed["items"][0]["year"] == 2023


@requires_db
async def test_journal_gap_csv_year_scoped(year_api):
    default = await year_api.get("/api/v1/ut/journals/AAAA-AAAA/openalex-only.csv")
    assert default.status_code == 200
    assert _csv_years(default.text) == ["2021", "2023"]
    narrowed = await year_api.get(
        "/api/v1/ut/journals/AAAA-AAAA/openalex-only.csv", params={"year_from": 2022}
    )
    assert _csv_years(narrowed.text) == ["2023"]


@requires_db
async def test_author_profile_year_scoped(year_api):
    default = (await year_api.get("/api/v1/ut/authors/author-1")).json()
    assert [w["year"] for w in default["works"]] == [2023, 2021]
    assert default["openalex_only_count"] == 2
    narrowed = (
        await year_api.get("/api/v1/ut/authors/author-1", params={"year_from": 2022})
    ).json()
    assert [w["year"] for w in narrowed["works"]] == [2023]
    assert [bucket["year"] for bucket in narrowed["oa_by_year"]] == [2023]
    assert narrowed["openalex_only_count"] == 1
    assert narrowed["openalex_only"]["total"] == 1


@requires_db
async def test_author_works_csv_year_scoped(year_api):
    missed = await year_api.get(
        "/api/v1/ut/authors/author-1/works.csv", params={"scope": "missed", "year_from": 2022}
    )
    assert _csv_years(missed.text) == ["2023"]
    canon = await year_api.get(
        "/api/v1/ut/authors/author-1/works.csv",
        params={"scope": "canon", "year_from": 2022, "year_to": 2023},
    )
    assert _csv_years(canon.text) == ["2023"]
    canon_default = await year_api.get(
        "/api/v1/ut/authors/author-1/works.csv", params={"scope": "canon"}
    )
    assert _csv_years(canon_default.text) == ["2021", "2023"]


@requires_db
async def test_orgunit_detail_year_scoped(year_api, db):
    from sqlalchemy import select

    from journal_browser.models import Institution
    from journal_browser.services import orgunits as orgunits_service

    ut = await db.scalar(select(Institution).where(Institution.code == "ut"))
    default = await orgunits_service.orgunit_detail(db, ut, "faculty", FACULTY)
    assert default is not None
    assert default["journals"] == [
        {
            "issn_l": "AAAA-AAAA",
            "title": "Journal AAAA-AAAA",
            "n_works": 2,
            "deal_covered": False,
            "oa_type": "subscription",
            "quartile": None,
        }
    ]
    assert default["openalex_only"]["total"] == 2

    narrowed = await orgunits_service.orgunit_detail(
        db, ut, "faculty", FACULTY, year_range=(2022, WINDOW_END)
    )
    assert narrowed is not None
    assert narrowed["journals"][0]["n_works"] == 1
    assert narrowed["openalex_only"]["total"] == 1
