"""The global publication-year lens (year_from/year_to) across every
serving surface it reaches: journals list (year-scoped per-journal works,
works facet, institution_works sort), the journals search with an active
q, funders list + detail (n_ut_works joins works on the clamped range),
publishers list + detail (stats-sum swap flips the works order), orgunits
list + faculty detail (scoped works columns), and the journal detail's
canonical institution metrics.

The scoped sums read institution_works_stats pure_canon rows — the same
population the denormalized journal_flags.works_count mirrors — so the
default view (no params) and the window-covering range serve identical
numbers, out-of-window bounds clamp onto the data window, and inverted
ranges answer 400. The facet cache key carries the active range, so a
ranged call never poisons the default entry.
"""

from urllib.parse import quote

import pytest

from conftest import journal_factory, requires_db
from journal_browser.models import (
    Author,
    AuthorWork,
    FunderLink,
    HarvestRun,
    InstitutionWorksStats,
    JiscFunder,
    JournalFlags,
    Work,
    WorkFunder,
)

WINDOW_START = 2020
WINDOW_END = 2024
FACULTY = "Science"
AAAA = "AAAA-AAAA"

#: issn -> (title, publisher, denormalized flags works_count,
#: {year: pure_canon works}). flags equals the pure_canon window sum.
JOURNALS = {
    AAAA: ("Cancer Research", "AlphaPress", 6, {2023: 6}),
    "BBBB-BBBB": ("Cancer Reports", "BetaPress", 7, {2021: 4, 2023: 3}),
    "CCCC-CCCC": ("Cancer Letters", "BetaPress", 1, {2021: 1}),
    "DDDD-DDDD": ("Cancer Notes", "GammaPress", 2, {2021: 2}),
}

#: bare openalex funder id -> {work uuid: year} (works live on AAAA).
WORK_FUNDERS = {
    "F1": {"w1": 2021, "w2": 2023},  # jisc funder 701, Alpha Foundation
    "F2": {"w0": 2020, "w1": 2021},  # jisc funder 702, Beta Fund
}


def _work_row(inst_id: int, run_id: int, uuid: str, year: int) -> Work:
    return Work(
        institution_id=inst_id,
        pure_uuid=uuid,
        title=f"Work {uuid}",
        norm_title=f"work {uuid}",
        year=year,
        doi_normalized=f"10.0.0/{uuid}",
        work_type="info:eu-repo/semantics/article",
        journal_issn_l=AAAA,
        first_seen_run=run_id,
        last_seen_run=run_id,
    )


@pytest.fixture
async def lens_api(client, db, institution_factory):
    """ut (window 2020-2024): four journals whose pure_canon stats span
    the window edges, three works on AAAA carrying the funder links, and
    one confirmed Science author edged to the 2021 + 2023 works."""
    ut = await institution_factory(
        code="ut", data_window_start=WINDOW_START, data_window_end=WINDOW_END
    )
    db.add_all(
        journal_factory(
            issn,
            title=f"{title}",
            search_text=f"{title}",
            publisher_name=publisher,
        )
        for issn, (title, publisher, _count, _by_year) in JOURNALS.items()
    )
    await db.flush()
    db.add_all(
        JournalFlags(institution_id=ut.id, issn_l=issn, works_count=count, works_window_plus=10)
        for issn, (_title, _publisher, count, _by_year) in JOURNALS.items()
    )
    db.add_all(
        InstitutionWorksStats(
            institution_id=ut.id, issn_l=issn, year=year, works_count=n, source="pure_canon"
        )
        for issn, (_title, _publisher, _count, by_year) in JOURNALS.items()
        for year, n in by_year.items()
    )
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()
    uuid_year = {uuid: year for rows in WORK_FUNDERS.values() for uuid, year in rows.items()}
    db.add_all(_work_row(ut.id, run.id, uuid, year) for uuid, year in uuid_year.items())
    db.add(
        Author(
            institution_id=ut.id,
            pure_uuid="author-1",
            name="Test Author",
            faculty=FACULTY,
            confirmed=True,
            openalex_ids=["a1111111111"],
            n_works=2,
        )
    )
    await db.flush()
    db.add_all(
        AuthorWork(institution_id=ut.id, author_pure_uuid="author-1", work_pure_uuid=uuid)
        for uuid in ("w1", "w2")
    )
    db.add_all(
        [
            JiscFunder(id=701, name="Alpha Foundation", country="NL"),
            JiscFunder(id=702, name="Beta Fund", country="NL"),
        ]
    )
    await db.flush()  # the funder FK must exist before the canon links
    db.add_all(
        FunderLink(
            funder_id=fid,
            source="openalex",
            source_id=f"https://openalex.org/{bare}",
            via="ror",
        )
        for fid, bare in ((701, "F1"), (702, "F2"))
    )
    db.add_all(
        WorkFunder(
            institution_id=ut.id,
            pure_uuid=uuid,
            funder_openalex_id=bare,
            funder_name=f"Funder {bare}",
        )
        for bare, rows in WORK_FUNDERS.items()
        for uuid in rows
    )
    await db.commit()
    return client


def _works_by_issn(body: dict) -> dict[str, int]:
    return {i["issn_l"]: i["works"] for i in body["items"]}


def _works_by_name(body: dict, key: str) -> dict[str, int]:
    return {i["name"]: i[key] for i in body["items"]}


JOURNAL_EXPECTED = {
    "default": {issn: count for issn, (_t, _p, count, _y) in JOURNALS.items()},
    "from2023": {AAAA: 6, "BBBB-BBBB": 3, "CCCC-CCCC": 0, "DDDD-DDDD": 0},
}

SURFACES = [
    {
        "name": "journals-list-works",
        "url": "/api/v1/ut/journals",
        "params": {"include_facets": "false"},
        "pick": _works_by_issn,
        "default": JOURNAL_EXPECTED["default"],
        "ranged": JOURNAL_EXPECTED["from2023"],
    },
    {
        "name": "journals-search-works",
        "url": "/api/v1/ut/journals",
        "params": {"include_facets": "false", "q": "cancer"},
        "pick": _works_by_issn,
        "default": JOURNAL_EXPECTED["default"],
        "ranged": JOURNAL_EXPECTED["from2023"],
    },
    {
        "name": "journals-works-facet",
        "url": "/api/v1/ut/journals",
        "params": {"include_facets": "true"},
        "pick": lambda b: b["facets"]["works"],
        "default": {"true": 4, "false": 0},
        "ranged": {"true": 2, "false": 2},
    },
    {
        "name": "journals-institution-works-sort",
        "url": "/api/v1/ut/journals",
        "params": {"include_facets": "false", "sort": "institution_works"},
        "pick": lambda b: [i["issn_l"] for i in b["items"]],
        "default": ["BBBB-BBBB", AAAA, "DDDD-DDDD", "CCCC-CCCC"],
        # Zero-works ties follow the cursor tiebreak (issn_l desc).
        "ranged": [AAAA, "BBBB-BBBB", "DDDD-DDDD", "CCCC-CCCC"],
    },
    {
        "name": "funders-list-works",
        "url": "/api/v1/ut/funders",
        "params": {},
        "pick": lambda b: _works_by_name(b, "n_ut_works"),
        "default": {"Alpha Foundation": 2, "Beta Fund": 2},
        "ranged": {"Alpha Foundation": 1, "Beta Fund": 0},
    },
    {
        "name": "publishers-works-order",
        "url": "/api/v1/ut/publishers",
        "params": {"include_facets": "false"},
        "pick": lambda b: [i["name"] for i in b["items"]],
        "default": ["BetaPress", "AlphaPress", "GammaPress"],
        "ranged": ["AlphaPress", "BetaPress", "GammaPress"],
    },
    {
        "name": "publishers-works",
        "url": "/api/v1/ut/publishers",
        "params": {"include_facets": "false"},
        "pick": lambda b: _works_by_name(b, "n_works"),
        "default": {"AlphaPress": 6, "BetaPress": 8, "GammaPress": 2},
        "ranged": {"AlphaPress": 6, "BetaPress": 3, "GammaPress": 0},
    },
    {
        "name": "publishers-has-works-facet",
        "url": "/api/v1/ut/publishers",
        "params": {"include_facets": "true"},
        "pick": lambda b: b["facets"]["has_works"],
        "default": {"true": 3, "false": 0},
        "ranged": {"true": 2, "false": 1},
    },
    {
        "name": "orgunits-list-works",
        "url": "/api/v1/ut/orgunits",
        "params": {},
        "pick": lambda b: _works_by_name(b, "n_works"),
        "default": {FACULTY: 2},
        "ranged": {FACULTY: 1},
    },
    {
        "name": "journal-detail-canonical",
        "url": f"/api/v1/ut/journals/{AAAA}",
        "params": {},
        "pick": lambda b: {"canonical_total": b["institution_metrics"]["canonical_total"]},
        "default": {"canonical_total": 3},
        "ranged": {"canonical_total": 1},
    },
    {
        "name": "funder-detail-works",
        "url": "/api/v1/ut/funders/701",
        "params": {},
        "pick": lambda b: {"n_ut_works": b["n_ut_works"]},
        "default": {"n_ut_works": 2},
        "ranged": {"n_ut_works": 1},
    },
    {
        "name": "publisher-detail-works",
        "url": "/api/v1/ut/publishers/BetaPress",
        "params": {},
        "pick": lambda b: {"n_works": b["publisher"]["n_works"]},
        "default": {"n_works": 8},
        "ranged": {"n_works": 3},
    },
    {
        "name": "orgunit-detail-works",
        "url": f"/api/v1/ut/orgunits/faculty/{quote(FACULTY)}",
        "params": {},
        "pick": lambda b: {"n_works": b["unit"]["n_works"]},
        "default": {"n_works": 2},
        "ranged": {"n_works": 1},
    },
]

SURF = {s["name"]: s for s in SURFACES}

YEAR_400_PATHS = [
    "/api/v1/ut/journals",
    f"/api/v1/ut/journals/{AAAA}",
    f"/api/v1/ut/journals/{AAAA}/works",
    f"/api/v1/ut/journals/{AAAA}/openalex-only.csv",
    "/api/v1/ut/funders",
    "/api/v1/ut/funders/701",
    "/api/v1/ut/publishers",
    "/api/v1/ut/publishers/BetaPress",
    "/api/v1/ut/publishers/BetaPress/openalex-only.csv",
    "/api/v1/ut/orgunits",
    f"/api/v1/ut/orgunits/faculty/{quote(FACULTY)}",
    "/api/v1/ut/authors",
]


async def _pick(client, surface: dict, extra: dict | None = None):
    params = {**surface["params"], **(extra or {})}
    return surface["pick"]((await client.get(surface["url"], params=params)).json())


@pytest.mark.parametrize("surface", SURFACES, ids=lambda s: s["name"])
@requires_db
async def test_year_window_rescopes_each_surface(lens_api, surface):
    """One assertion per surface pair: the default view serves the
    denormalized numbers, 2023+ the in-range sums (counts, facets and
    sort order all move with the range)."""
    assert await _pick(lens_api, surface) == surface["default"]
    assert await _pick(lens_api, surface, {"year_from": 2023}) == surface["ranged"]


@requires_db
async def test_year_bounds_clamp_to_data_window(lens_api):
    """Wide and below-window bounds clamp onto 2020-2024 and reproduce the
    default numbers on every list surface; an above-window `to` truncates."""
    journals = SURF["journals-list-works"]
    default = await _pick(lens_api, journals)
    wide = await _pick(lens_api, journals, {"year_from": 1900, "year_to": 2100})
    below = await _pick(lens_api, journals, {"year_from": 2019})
    assert wide == below == default
    above = await _pick(lens_api, journals, {"year_from": 2022, "year_to": 2030})
    assert above == journals["ranged"]
    for name in ("funders-list-works", "publishers-works", "orgunits-list-works"):
        surface = SURF[name]
        assert (
            await _pick(lens_api, surface, {"year_from": 1900, "year_to": 2100})
            == (surface["default"])
        )


@pytest.mark.parametrize("path", YEAR_400_PATHS)
@requires_db
async def test_inverted_range_is_400(lens_api, path):
    r = await lens_api.get(path, params={"year_from": 2023, "year_to": 2021})
    assert r.status_code == 400


@requires_db
async def test_default_serves_full_window(lens_api):
    """No params and the window-covering range serve identical numbers; a
    ranged facet call must not poison the default cache entry."""
    for name in (
        "journals-list-works",
        "journals-works-facet",
        "publishers-works",
        "orgunits-list-works",
    ):
        surface = SURF[name]
        clamped = await _pick(lens_api, surface, {"year_from": WINDOW_START, "year_to": WINDOW_END})
        assert clamped == surface["default"]
        assert await _pick(lens_api, surface) == surface["default"]
