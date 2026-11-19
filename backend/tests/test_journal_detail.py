"""Journal detail and works tab as served: the enrichment bundle the page
renders (OpenAlex venue card, OpenAIRE cross-check, canonical institution
metrics, DOAJ homepage preference, openaccess.nl publisher slug, green-OA
policy with matched repository links), the works tab's paging cap and its
store-metadata merge (most-open record wins merged-profile twins, Pure
OA status falls back for DOI-less works, raw authorships never leak), the
degraded-but-200 path when a journal has no enrichment rows at all, the
funder-fit tier decision as served through ?funder=, derived journal OA
colors from stored works, and the repo-name matcher table.

The per-DOI enricher (harvest.enrich) pins its failure isolation here too:
a 404 is a miss, other failures are isolated and counted, and only a
fully failed chunk fails the run.
"""

from datetime import UTC, datetime

import httpx
import pytest
from bibliofabric.exceptions import APIError, NotFoundError, RateLimitError
from sqlalchemy import select

from conftest import journal_factory, requires_db
from journal_browser.harvest.enrich import fetch_works_by_doi
from journal_browser.harvest.journal_oa import derive_oa_colors_local
from journal_browser.models import (
    Author,
    Deal,
    DealInstitution,
    DealJournal,
    HarvestRun,
    InstitutionWorksStats,
    JiscFunder,
    JiscRepository,
    Journal,
    OpenalexWork,
    Publisher,
    SourceRecord,
    Work,
    WorkIdentity,
    WorkPureAuthor,
)
from journal_browser.services.repo_links import match_repositories

MAIN = "1234-5678"
OTHER = "2222-2222"

POLICY = {
    "routes": {
        "submitted": {
            "locations": ["named_repo"],
            "repositories": ["RePEc", "arXiv", "Cosis", "Nowhere"],
        }
    },
    "open_access_prohibited": False,
    "urls": [],
    "policy_uri": "https://openpolicyfinder.jisc.ac.uk/policy/1",
}

#: Raw venue source object; topic counts deliberately unsorted with a NULL.
SOURCE_PAYLOAD = {
    "id": "S123456",
    "issn_l": MAIN,
    "cited_by_count": 100,
    "works_count": 42,
    "host_organization_name": "Widget Press",
    "counts_by_year": [
        {"year": 2023, "works_count": 5},
        {"year": 2021, "works_count": 7},
        {"year": 2019, "works_count": 2},
    ],
    "topics": [
        {
            "id": "T1",
            "display_name": "Small",
            "count": 2,
            "subfield": {"id": "sf", "display_name": "S"},
        },
        {"id": "T2", "display_name": "Big", "count": 9, "subfield": None},
        {"id": "T3", "display_name": "NullCount", "count": None, "subfield": None},
    ],
}

STRUCTURED = {"archiving_policy": {"when": {"when": "within_12_months"}, "where": {}}}


def _store_work(inst_id, w_id, *, doi, year, **kw):
    return OpenalexWork(
        institution_id=inst_id,
        w_id=w_id,
        doi_normalized=doi,
        title=kw.pop("title", f"Store {w_id}"),
        year=year,
        work_type="article",
        oa_status=kw.pop("oa_status", None),
        venue_issn_l=MAIN,
        venue_name="Widget Press Journal",
        cited_by_count=kw.pop("cited_by_count", 0),
        source="works_stats",
        **kw,
    )


def _pure_work(inst_id, run_id, uuid, title, year, *, doi=None, oa=None):
    return Work(
        institution_id=inst_id,
        pure_uuid=uuid,
        title=title,
        norm_title=title.lower(),
        year=year,
        work_type="info:eu-repo/semantics/article",
        doi_normalized=doi,
        oa_status=oa,
        journal_issn_l=MAIN,
        first_seen_run=run_id,
        last_seen_run=run_id,
    )


@pytest.fixture
async def detail_api(client, db, institution_factory):
    """ut: journal MAIN carries every enrichment input (source payload,
    store rows incl. a merged-profile twin and a store-only row, a Pure
    population with UT authors, OpenAIRE identities, per-year stats, DOAJ
    homepage, publisher slug, OPF policy); OTHER stays bare."""
    ut = await institution_factory(code="ut")
    db.add_all(
        [
            journal_factory(
                MAIN,
                publisher_name="Alpha Press",
                publisher_canonical="Alpha Press",
                homepage_url="https://openalex.example/journal",
                doaj_homepage_url="https://doaj.example/journal",
                jisc_in_opf=True,
                jisc_allows_sa_submitted=True,
                jisc_policy=POLICY,
                jisc_harvested_at=datetime(2026, 11, 2, 12, 0, tzinfo=UTC),
            ),
            journal_factory(OTHER),
        ]
    )
    db.add(Publisher(name="Alpha Press", openaccess_nl_slug="alpha-press"))
    db.add_all(
        [
            JiscRepository(
                id=1, name="RePEc: Research Papers in Economics", url="https://repec.example"
            ),
            JiscRepository(id=2, name="Cosis", url=None),
            JiscRepository(id=3, name="arXivSpace", url="https://wrong.example"),
        ]
    )
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    oa_run = HarvestRun(
        source="openaire", entity_type="work", config_fingerprint="t", institution_id=ut.id
    )
    db.add_all([run, oa_run])
    await db.flush()
    db.add(
        SourceRecord(
            source="openalex",
            entity_type="sources",
            source_pk="S123456",
            payload=SOURCE_PAYLOAD,
            content_hash="v1",
            harvest_run_id=run.id,
        )
    )
    db.add_all(
        [
            _pure_work(ut.id, run.id, "pw1", "Pure One", 2021, doi="10.1/w1", oa="green"),
            _pure_work(ut.id, run.id, "pw2", "Pure Two", 2023, doi="10.5/w2", oa="closed"),
            _pure_work(ut.id, run.id, "pw3", "Pure Three", 2020, oa="green"),
            # OpenAIRE: two confirmed identities on the journal -> facts derive.
            _pure_work(ut.id, run.id, "u1", "T u1", 2021),
            _pure_work(ut.id, run.id, "u2", "T u2", 2021),
        ]
    )
    db.add_all(
        [
            Author(
                institution_id=ut.id,
                pure_uuid="a1",
                name="Alice Alpha",
                research_group="Group X",
                confirmed=True,
                n_works=2,
            ),
            Author(
                institution_id=ut.id,
                pure_uuid="a2",
                name="Bob Beta",
                confirmed=True,
                n_works=1,
            ),
        ]
    )
    await db.flush()
    db.add_all(
        [
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="pw1", person_uuid="a1"),
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="pw2", person_uuid="a1"),
            WorkPureAuthor(institution_id=ut.id, work_pure_uuid="pw3", person_uuid="a2"),
            WorkIdentity(
                institution_id=ut.id,
                source="openaire",
                source_pk="OA1",
                work_id="u1",
                matched_by="doi",
                status="confirmed",
            ),
            WorkIdentity(
                institution_id=ut.id,
                source="openaire",
                source_pk="OA2",
                work_id="u2",
                matched_by="doi",
                status="confirmed",
            ),
            SourceRecord(
                source="openaire",
                entity_type="work",
                source_pk="OA1",
                payload={"id": "OA1"},
                content_hash="h1",
                harvest_run_id=oa_run.id,
            ),
            SourceRecord(
                source="openaire",
                entity_type="work",
                source_pk="OA2",
                payload={"id": "OA2"},
                content_hash="h2",
                harvest_run_id=oa_run.id,
            ),
            InstitutionWorksStats(
                institution_id=ut.id, source="pure_canon", issn_l=MAIN, year=2021, works_count=10
            ),
            InstitutionWorksStats(
                institution_id=ut.id,
                source="openalex_institution_filter",
                issn_l=MAIN,
                year=2021,
                works_count=12,
                oa_gold=3,
                oa_hybrid=2,
                oa_green=4,
                oa_bronze=1,
                oa_diamond=1,
                oa_closed=1,
            ),
            InstitutionWorksStats(
                institution_id=ut.id,
                source="openalex_institution_filter",
                issn_l=MAIN,
                year=2022,
                works_count=5,
                oa_green=5,
            ),
        ]
    )
    # Store rows: W1b is a closed merged-profile twin of W1 and must lose
    # to the gold record; W9 is store-only (not in Pure).
    db.add_all(
        [
            _store_work(
                ut.id, "W1", doi="10.1/w1", year=2021, oa_status="gold", cited_by_count=5, fwci=1.5
            ),
            _store_work(
                ut.id, "W1b", doi="10.1/w1", year=2021, oa_status="closed", cited_by_count=5
            ),
            _store_work(
                ut.id,
                "W2",
                doi="10.5/w2",
                year=2023,
                oa_status="closed",
                cited_by_count=9,
                is_retracted=True,
            ),
            _store_work(ut.id, "W9", doi="10.9/store-only", year=2021, cited_by_count=7),
        ]
    )
    await db.commit()

    from journal_browser.harvest.openaire_facts import derive_openaire_facts

    await derive_openaire_facts(db, ut)
    await db.commit()
    return client


@requires_db
async def test_detail_carries_enrichment_fields(detail_api):
    """The detail bundle serves every enrichment block from stored data."""
    r = await detail_api.get(f"/api/v1/ut/journals/{MAIN}")
    assert r.status_code == 200
    body = r.json()
    # DOAJ is the canon homepage source; OpenAlex fills the gap.
    assert body["homepage_url"] == "https://doaj.example/journal"
    assert body["doaj_homepage_url"] == "https://doaj.example/journal"
    # Publisher registry link joins through the canonical publisher name.
    assert body["openaccess_nl_slug"] == "alpha-press"
    assert body["journal"]["works"] == 15  # pure_canon 10 + openalex-only year 5

    openalex = body["openalex"]
    assert openalex["id"] == "S123456"
    assert openalex["url"] == "https://openalex.org/S123456"
    assert openalex["cited_by_count"] == 100
    assert openalex["works_count"] == 42
    assert openalex["host_organization_name"] == "Widget Press"
    assert openalex["first_publication_year"] == 2019
    assert openalex["last_publication_year"] == 2023
    assert [t["display_name"] for t in openalex["topics"]] == ["Big", "Small", "NullCount"]
    assert openalex["topics"][0]["subfield"] is None
    assert openalex["topics"][1]["subfield"] == {"id": "sf", "display_name": "S"}

    assert body["openaire"]["matched_works"] == 2
    assert body["openaire"]["with_usage"] == 0

    stats = {s["year"]: s for s in body["stats"]}
    assert stats[2021]["works_count"] == 10
    assert stats[2021]["works_count_source"] == "pure_canon"
    assert (stats[2021]["oa_gold"], stats[2021]["oa_hybrid"], stats[2021]["oa_green"]) == (3, 2, 4)
    # An OpenAlex-only year keeps its own count and is labeled as such.
    assert stats[2022]["works_count"] == 5
    assert stats[2022]["works_count_source"] == "openalex_institution_filter"

    green = body["green_oa"]
    assert green["in_opf"] is True
    assert green["routes"]["submitted"]["repositories"] == ["RePEc", "arXiv", "Cosis", "Nowhere"]
    # Only the canon row with a word-boundary name match and a url links.
    assert green["repository_links"] == {"RePEc": "https://repec.example"}
    for key in ("openalex", "openaire", "works", "green_oa"):
        assert key in body["attribution"]


@requires_db
async def test_works_tab_pages_and_unknown_journal_404s(detail_api):
    # page_size validates against the 50 cap.
    over = await detail_api.get(f"/api/v1/ut/journals/{MAIN}/works", params={"page_size": 51})
    assert over.status_code == 422
    assert (await detail_api.get("/api/v1/ut/journals/0000-0000/works")).status_code == 404
    assert (await detail_api.get("/api/v1/ut/journals/0000-0000")).status_code == 404

    body = (
        await detail_api.get(f"/api/v1/ut/journals/{MAIN}/works", params={"page_size": 2})
    ).json()
    assert body["total"] == 5
    assert body["page"] == 1 and body["page_size"] == 2
    assert [i["title"] for i in body["items"]] == ["Pure Two", "Pure One"]


@requires_db
async def test_works_tab_merges_store_metadata(detail_api):
    """Store enrichment merges per DOI (most-open record wins the twin),
    Pure's own OA status serves DOI-less works, and raw authorships never
    surface; the canonical metrics describe the same population the tab
    lists."""
    r = await detail_api.get(f"/api/v1/ut/journals/{MAIN}/works")
    assert r.status_code == 200
    items = {i["title"]: i for i in r.json()["items"]}
    assert items["Pure Two"] == {
        "id": "W2",
        "url": "https://openalex.org/W2",
        "doi": "https://doi.org/10.5/w2",
        "title": "Pure Two",
        "year": 2023,
        "oa_status": "closed",
        "fwci": None,
        "cited_by_count": 9,
        "is_retracted": True,
        "type": "article",
        "work_type": "article",
        "in_openalex": True,
        "ut_authors": [{"id": "a1", "name": "Alice Alpha"}],
        "ut_groups": [{"name": "Group X"}],
        "openaire": None,
    }
    w1 = items["Pure One"]
    assert w1["id"] == "W1"  # gold record beats the closed twin W1b
    assert w1["oa_status"] == "gold" and w1["fwci"] == 1.5
    assert items["Pure Three"]["in_openalex"] is False
    assert items["Pure Three"]["id"] is None
    assert items["Pure Three"]["oa_status"] == "green"  # Pure's own fallback
    assert items["Pure Three"]["ut_authors"] == [{"id": "a2", "name": "Bob Beta"}]
    assert "authorships" not in r.text

    metrics = (await detail_api.get(f"/api/v1/ut/journals/{MAIN}")).json()["institution_metrics"]
    assert metrics["canonical_total"] == r.json()["total"] == 5
    assert metrics["canonical_retracted"] == 1
    assert metrics["canonical_oa"] == {
        "gold": 1,
        "hybrid": 0,
        "green": 1,
        "bronze": 0,
        "diamond": 0,
        "closed": 1,
        "unknown": 2,
    }
    assert metrics["openalex_matched"] == 4  # W1, W1b, W2, W9 (twin kept distinct)
    assert metrics["fwci_n"] == 1 and metrics["retracted"] == 1
    assert metrics["cited_total"] == 26


@requires_db
async def test_detail_serves_when_enrichment_missing(detail_api):
    """A journal without any enrichment rows (no source payload, no store
    rows, no facts) degrades to empty cards instead of erroring."""
    r = await detail_api.get(f"/api/v1/ut/journals/{OTHER}")
    assert r.status_code == 200
    body = r.json()
    assert body["openalex"] is None
    assert body["openaire"]["matched_works"] == 0
    metrics = body["institution_metrics"]
    assert metrics["canonical_total"] == metrics["openalex_matched"] == 0
    assert metrics["fwci_avg"] is None and metrics["cited_total"] == 0
    assert set(metrics["canonical_oa"].values()) == {0}
    assert body["ut_authorship"]["n_ut_works"] == 0
    # The store ran for this institution (MAIN holds store rows), so the
    # gap card is available and simply empty for this venue.
    assert body["openalex_only"]["total"] == 0
    assert body["openalex_only"]["entries_total"] == 0
    works = await detail_api.get(f"/api/v1/ut/journals/{OTHER}/works")
    assert works.json()["total"] == 0


# ── Per-DOI enricher: failure isolation ───────────────────────────────────


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

    async def get(self, url: str):
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


def _api_error(status: int) -> APIError:
    cls = NotFoundError if status == 404 else APIError
    return cls(
        f"API request failed with status {status}",
        response=httpx.Response(status_code=status, request=httpx.Request("GET", "https://x.test")),
    )


async def test_enrich_fetch_isolates_failures():
    """A 404 is a miss (no error, no fake match); other failures are
    isolated and counted; only a fully failed chunk fails loudly."""
    behavior = {
        "10.1/ok": _FakeWork("W1", oa_status="gold"),
        "10.1/gone": _api_error(404),
        "10.1/bad": _api_error(500),
        "10.1/slow": RateLimitError("slow down"),
    }
    stats: dict[str, int] = {}
    found, errored, first_error = await fetch_works_by_doi(
        _FakeClient(behavior), ["10.1/ok", "10.1/gone", "10.1/bad", "10.1/slow"], stats
    )
    assert found["10.1/ok"] is not None
    assert found["10.1/gone"] is None
    assert errored == {"10.1/bad", "10.1/slow"}
    assert stats["fetch_errors"] == 2
    assert isinstance(first_error, APIError)
    with pytest.raises(RuntimeError):
        await fetch_works_by_doi(
            _FakeClient({d: _api_error(503) for d in ("10.1/a", "10.1/b")}), ["10.1/a", "10.1/b"]
        )


# ── Funder fit: tier decision served through ?funder= ─────────────────────


GOLD = "5150-5150"
DEAL = "5151-5151"

#: (case id, journal issn, funder id, expected served tier + reasons).
FIT_TIERS = [
    ("gold-journal", GOLD, 901, "compliant", ["Fully OA journal (DOAJ-registered)"]),
    (
        "deal-covered",
        DEAL,
        901,
        "compliant",
        ["Covered by a transformative agreement (Deal Press)"],
    ),
    ("prohibited", "5152-5152", 901, "no", ["Publisher prohibits OA deposit"]),
    (
        "green-route",
        "5153-5153",
        901,
        "check",
        [
            "Green route available; publisher embargo is unstated, "
            "verify the funder's deposit timing"
        ],
    ),
    ("no-route", "5154-5154", 901, "no", ["No OA route or agreement found for this journal"]),
    ("text-only-policy", GOLD, 902, None, ["Funder policy is text-only; check manually"]),
]


@pytest.fixture
async def fit_api(client, db, institution_factory):
    """ut: one journal per funder-fit tier plus a structured and a
    text-only OPF funder; the deal tier joins through a current deal."""
    ut = await institution_factory(code="ut")
    db.add_all(
        [
            journal_factory(GOLD, publisher_name="Gold Press", is_in_doaj=True, doaj_has_apc=True),
            journal_factory(DEAL, publisher_name="Deal Press"),
            journal_factory("5152-5152", publisher_name="P Press", jisc_oa_prohibited=True),
            journal_factory("5153-5153", publisher_name="G Press", jisc_allows_sa_published=True),
            journal_factory("5154-5154", publisher_name="N Press"),
        ]
    )
    db.add_all(
        [
            JiscFunder(id=901, name="Structured Funder", publications_policy=STRUCTURED),
            JiscFunder(id=902, name="Text Funder", publications_policy={"title_only": True}),
        ]
    )
    deal = Deal(status="current")
    db.add(deal)
    await db.flush()
    db.add_all(
        [
            DealInstitution(deal_id=deal.id, institution_id=ut.id, participation="named"),
            DealJournal(deal_id=deal.id, issn=DEAL, issn_l=DEAL, source="manual"),
        ]
    )
    await db.commit()
    return client


@pytest.mark.parametrize(
    "case,issn,funder_id,status,reasons", FIT_TIERS, ids=[c[0] for c in FIT_TIERS]
)
@requires_db
async def test_funder_fit_tiers_served(fit_api, case, issn, funder_id, status, reasons):
    r = await fit_api.get(f"/api/v1/ut/journals/{issn}", params={"funder": funder_id})
    assert r.status_code == 200
    assert r.json()["funder_fit"] == {"status": status, "reasons": reasons}


@requires_db
async def test_funder_fit_requires_funder_param(fit_api):
    body = (await fit_api.get(f"/api/v1/ut/journals/{GOLD}")).json()
    assert body["funder_fit"] is None


# ── Derived OA colors ──────────────────────────────────────────────────────


@requires_db
async def test_derive_oa_colors_from_stored_works(db, institution_factory):
    """derive_oa_colors_local fills journals.oa_status_observed from the
    stored works' modal non-green color (ties by fixed priority), stores
    'green' for all-green venues, never overwrites existing colors, and is
    a no-op on rerun."""
    inst = await institution_factory()
    run = HarvestRun(source="test", entity_type="works", config_fingerprint="t")
    db.add_all(
        [
            journal_factory("1111-1111"),  # 3 gold + 1 green -> gold
            journal_factory("2222-2222"),  # green-only -> 'green'
            journal_factory("3333-3333", oa_status_observed="bronze"),  # never overwritten
            journal_factory("4444-4444"),  # status-less works only -> stays None
            journal_factory("5555-5555"),  # diamond/gold tie -> priority order
        ]
    )
    db.add(run)
    await db.flush()

    def _work(uuid: str, issn: str, status: str | None) -> Work:
        return Work(
            institution_id=inst.id,
            pure_uuid=uuid,
            title=f"Work {uuid}",
            norm_title=f"work {uuid}",
            year=2020,
            oa_status=status,
            journal_issn_l=issn,
            first_seen_run=run.id,
            last_seen_run=run.id,
        )

    db.add_all(
        [
            *[_work(f"g{i}", "1111-1111", "gold") for i in range(3)],
            _work("gg", "1111-1111", "green"),
            _work("gr", "2222-2222", "green"),
            _work("br", "3333-3333", "gold"),
            _work("ns", "4444-4444", None),
            _work("td", "5555-5555", "diamond"),
            _work("tg", "5555-5555", "gold"),
        ]
    )
    await db.commit()

    stats = await derive_oa_colors_local(db)
    await db.commit()
    assert stats["colored"] == 3

    observed = {
        issn: await db.scalar(select(Journal.oa_status_observed).where(Journal.issn_l == issn))
        for issn in ("1111-1111", "2222-2222", "3333-3333", "4444-4444", "5555-5555")
    }
    assert observed == {
        "1111-1111": "gold",
        "2222-2222": "green",  # all-green evidence = venue color unknown
        "3333-3333": "bronze",
        "4444-4444": None,
        "5555-5555": "gold",  # tie resolves by priority, not sample order
    }
    assert (await derive_oa_colors_local(db))["colored"] == 0


# ── Green-route repository matcher ─────────────────────────────────────────

CANON = [
    ("RePEc: Research Papers in Economics", "https://repec.example"),
    ("arXiv.org", "https://arxiv.example"),
    ("PubMed Central", "https://pmc.example"),
    ("Dryad Digital Repository", "https://dryad.example"),
]

MATCHER_CASES = [
    (
        "exact-normalized",
        ["PubMed Central", "pubmed  central", "ARXIV.ORG!"],
        {
            "PubMed Central": "https://pmc.example",
            "pubmed  central": "https://pmc.example",
            "ARXIV.ORG!": "https://arxiv.example",
        },
    ),
    (
        "first-canon-row-wins",
        ["PubMed Central"],
        {"PubMed Central": "first"},
    ),
    (
        "containment",
        ["RePEc", "arXiv", "Dryad"],
        {
            "RePEc": "https://repec.example",
            "arXiv": "https://arxiv.example",
            "Dryad": "https://dryad.example",
        },
    ),
    ("word-boundaries", ["repo", "Xiv"], {}),
    ("unmatched", ["Cosis", "EathArXiv"], {}),
]


@pytest.mark.parametrize("case,names,expected", MATCHER_CASES, ids=[c[0] for c in MATCHER_CASES])
async def test_repository_matcher_table(case, names, expected):
    canon = list(CANON)
    if case == "first-canon-row-wins":
        canon = [("PubMed Central", "first"), ("PubMed  Central", "second")]
    assert match_repositories(names, canon) == expected


# ── Canonical metrics population (folded from test_correct_journal_metrics.py)


@requires_db
async def test_metrics_canonical_venue_cross_check(db, institution_factory):
    """The FWCI/retracted tiles ride the canonical UT works population
    (decision 22): an author-sweep venue row joins only the separately
    named cross-check fields, never the canonical tiles."""
    from journal_browser.services.detail_enrichment import institution_metrics

    ut = await institution_factory(code="ut", data_window_start=2020)
    db.add(journal_factory("1234-5678"))
    run = HarvestRun(source="pure", entity_type="works", status="completed", config_fingerprint="t")
    db.add(run)
    await db.flush()
    db.add_all(
        [
            Work(
                institution_id=ut.id,
                pure_uuid="w-a",
                title="w-a",
                norm_title="w-a",
                year=2023,
                doi_normalized="10.0.0/a",
                journal_issn_l="1234-5678",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            Work(
                institution_id=ut.id,
                pure_uuid="w-b",
                title="w-b",
                norm_title="w-b",
                year=2022,
                journal_issn_l="1234-5678",
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            # Venue-side only: not a works-table row (author sweep row of
            # the same venue).
            OpenalexWork(
                institution_id=ut.id,
                w_id="W-sweep",
                title="sweep-only",
                year=2023,
                fwci=0.5,
                authorships=[],
                venue_issn_l="1234-5678",
                venue_name="Journal 1234-5678",
                source="author-sweep:1",
            ),
        ]
    )
    db.add(
        OpenalexWork(
            institution_id=ut.id,
            w_id="W-a",
            title="w-a",
            year=2023,
            doi_normalized="10.0.0/a",
            fwci=2.0,
            is_retracted=True,
            cited_by_count=4,
            authorships=[],
            venue_issn_l="1234-5678",
            venue_name="Journal 1234-5678",
            source="works_stats",
        )
    )
    await db.commit()

    m = await institution_metrics(db, "1234-5678", ut)
    # Canonical tiles: two works, one store-matched with fwci 2.0, retracted.
    assert m["canonical_total"] == 2
    assert m["fwci_n"] == 1 and m["fwci_avg"] == 2.0
    assert m["retracted"] == 1 == m["canonical_retracted"]
    # Venue cross-check keeps its own numbers (2 venue rows, fwci 0.5+2.0).
    assert m["openalex_matched"] == 2
    assert m["venue_fwci_n"] == 2
    assert m["venue_fwci_avg"] == pytest.approx(1.25)
    assert m["venue_retracted"] == 1
    assert m["cited_total"] == 4
