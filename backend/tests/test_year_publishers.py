"""Global publication-year filter on the publishers list: the snapshot's
per-journal works counts swap to year-summed institution_works_stats
pure_canon rows, flowing into n_works, the works sort, the has_works
facet and the topic works-weighting. The roster membership (browsable
cutoffs), journal counts and every other attribute stay unfiltered, so
the size facet (journal-count basis) is range-invariant; the clamped full
window reproduces the denormalized flags counts and OpenAlex cross-check
rows never fill the count; from > to answers 400."""

from httpx import AsyncClient

from conftest import journal_factory, requires_db
from journal_browser.models import InstitutionWorksStats, JournalFlags

WINDOW_START = 2020
WINDOW_END = 2024

#: (issn_l, publisher, flags works_count, {year: pure_canon works}).
#: flags.works_count equals the pure_canon window sum, so the clamped
#: full window reproduces the denormalized column exactly.
JOURNALS = [
    ("1111-1111", "Alpha Press", 9, {2021: 4, 2023: 5}),
    ("2222-2222", "Alpha Press", 8, {2022: 8}),
    ("3333-3333", "Beta Press", 6, {2023: 6}),
    ("4444-4444", "Beta Press", 2, {2021: 2}),
    ("5555-5555", "Gamma Press", 1, {2021: 1}),
]

TOPICS = {
    "1111-1111": [{"display_name": "Physics", "count": 1, "subfield": "Physics"}],
    "2222-2222": [{"display_name": "Chemistry", "count": 1, "subfield": "Chemistry"}],
}


async def _seed(client: AsyncClient, db, institution_factory) -> int:
    ut = await institution_factory(
        code="ut", data_window_start=WINDOW_START, data_window_end=WINDOW_END
    )
    db.add_all(
        # topics kwarg omitted (not None): explicit None stores JSON null,
        # which jsonb_array_elements cannot explode (scalar, not SQL NULL).
        journal_factory(
            issn,
            publisher_name=publisher,
            **({"topics": TOPICS[issn]} if issn in TOPICS else {}),
        )
        for issn, publisher, _count, _by_year in JOURNALS
    )
    await db.flush()
    db.add_all(
        JournalFlags(institution_id=ut.id, issn_l=issn, works_count=count, works_window_plus=10)
        for issn, _publisher, count, _by_year in JOURNALS
    )
    db.add_all(
        InstitutionWorksStats(
            institution_id=ut.id, issn_l=issn, year=year, works_count=n, source="pure_canon"
        )
        for issn, _publisher, _count, by_year in JOURNALS
        for year, n in by_year.items()
    )
    # OpenAlex cross-check rows never fill the count (pure_canon primary,
    # exactly like the denormalized column).
    db.add(
        InstitutionWorksStats(
            institution_id=ut.id,
            issn_l="5555-5555",
            year=2023,
            works_count=99,
            source="openalex_institution_filter",
        )
    )
    await db.commit()
    return ut.id


@requires_db
async def test_default_serves_denormalized_counts(client, db, institution_factory):
    """No year params: byte-identical default behavior (denorm n_works,
    works desc with the name tiebreak)."""
    await _seed(client, db, institution_factory)
    r = await client.get("/api/v1/ut/publishers", params={"include_facets": "false"})
    assert r.status_code == 200
    body = r.json()
    assert [(i["name"], i["n_works"], i["n_journals"]) for i in body["items"]] == [
        ("Alpha Press", 17, 2),
        ("Beta Press", 8, 2),
        ("Gamma Press", 1, 1),
    ]


@requires_db
async def test_year_scoped_n_works_and_works_sort(client, db, institution_factory):
    """year_from=2023: Alpha drops to 5, Beta keeps 6 — the works sort
    flips; roster membership and journal counts stay unfiltered."""
    await _seed(client, db, institution_factory)
    r = await client.get(
        "/api/v1/ut/publishers",
        params={"include_facets": "false", "year_from": 2023, "year_to": 2024},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert [(i["name"], i["n_works"], i["n_journals"]) for i in body["items"]] == [
        ("Beta Press", 6, 2),
        ("Alpha Press", 5, 2),
        ("Gamma Press", 0, 1),
    ]


@requires_db
async def test_year_has_works_facet_and_filter(client, db, institution_factory):
    """Scoped works re-scope has_works: Gamma's in-range zero moves it to
    the false bucket and the filter matches it."""
    await _seed(client, db, institution_factory)
    r = await client.get("/api/v1/ut/publishers", params={"include_facets": "true"})
    assert r.json()["facets"]["has_works"] == {"true": 3, "false": 0}

    r = await client.get(
        "/api/v1/ut/publishers",
        params={"include_facets": "true", "year_from": 2023, "year_to": 2024},
    )
    facets = r.json()["facets"]
    assert facets["has_works"] == {"true": 2, "false": 1}
    # Attribute facets stay evaluated over the same scoped list; the size
    # facet is journal-count based, hence range-invariant.
    assert facets["size"] == {"1": 1, "2-4": 2, "5-9": 0, "10+": 0}

    r = await client.get(
        "/api/v1/ut/publishers",
        params={"has_works": "false", "include_facets": "false", "year_from": 2023},
    )
    assert [(i["name"], i["n_works"]) for i in r.json()["items"]] == [("Gamma Press", 0)]


@requires_db
async def test_year_topic_works_weighting(client, db, institution_factory):
    """Topic mass is works-weighted per journal: scoping to 2022 zeroes
    Alpha's 2021-only journal, so Chemistry overtakes Physics."""
    await _seed(client, db, institution_factory)
    r = await client.get("/api/v1/ut/publishers", params={"include_facets": "false"})
    alpha = r.json()["items"][0]
    assert alpha["topics"] == [{"name": "Physics", "n": 9.0}, {"name": "Chemistry", "n": 8.0}]

    r = await client.get(
        "/api/v1/ut/publishers",
        params={"include_facets": "false", "year_from": 2022, "year_to": 2022},
    )
    alpha = next(i for i in r.json()["items"] if i["name"] == "Alpha Press")
    assert alpha["n_works"] == 8
    assert alpha["topics"] == [{"name": "Chemistry", "n": 8.0}, {"name": "Physics", "n": 0.0}]


@requires_db
async def test_year_range_clamped_to_window(client, db, institution_factory):
    """Open bounds clamp to the institution window, reproducing the
    denormalized flags counts; out-of-range cross-check rows stay out."""
    await _seed(client, db, institution_factory)
    r = await client.get(
        "/api/v1/ut/publishers",
        params={"include_facets": "false", "year_from": 1900, "year_to": 2100},
    )
    assert [(i["name"], i["n_works"]) for i in r.json()["items"]] == [
        ("Alpha Press", 17),
        ("Beta Press", 8),
        ("Gamma Press", 1),
    ]


@requires_db
async def test_year_from_after_to_is_400(client, db, institution_factory):
    await _seed(client, db, institution_factory)
    r = await client.get("/api/v1/ut/publishers", params={"year_from": 2023, "year_to": 2021})
    assert r.status_code == 400
