"""Harvest sources, one outcome test each: a small recorded payload lands in
stored rows (or served rows for the JISC green-OA facet), and every source's
fail-loud guard fires. Payloads live in tests/fixtures/*.json, moved from the
old per-source test files.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import aletheca
import httpx
import pytest
from jobs.backfill_pure_authors import backfill_pure_work_authors
from jobs.import_pure_export import import_pure_export
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

import journal_browser.harvest.common as harvest_common
from conftest import journal_factory, requires_db
from journal_browser.config import get_settings, reset_settings_cache
from journal_browser.harvest import jisc_opf as jisc
from journal_browser.harvest.common import HarvestDataError, openalex_budget_ok
from journal_browser.harvest.denorm import MATERIALIZE_SQL
from journal_browser.harvest.doaj import harvest_doaj
from journal_browser.harvest.enrich import enrich_openalex
from journal_browser.harvest.funders import _upsert as upsert_canon
from journal_browser.harvest.funders import refresh_funder_links
from journal_browser.harvest.institution_stats import harvest_institution_stats
from journal_browser.harvest.jisc_normalize import normalize_jisc
from journal_browser.harvest.openaccess_nl import _upsert_deal, _upsert_publisher, parse_deal_page
from journal_browser.harvest.openaire_facts import derive_openaire_facts
from journal_browser.harvest.openalex_journals import _upsert_journal_page, harvest_journals_delta
from journal_browser.harvest.openalex_works import rebuild_openalex_works
from journal_browser.harvest.pure.cerif import publication_contributors
from journal_browser.harvest.pure.entities import (
    latest_publication_records,
    mine_publication_entities,
    parse_metadata_xml,
    rebuild_pure_orgs,
    rebuild_pure_persons,
)
from journal_browser.harvest.pure_portal import (
    apply_portal_tree,
    parse_portal_feed,
    walk_portal_orgs,
)
from journal_browser.harvest.work_funders import (
    _prune,
    _upsert,
    grants_rows,
    harvest_work_funders,
)
from journal_browser.ingest import IngestSession, content_hash
from journal_browser.models import (
    Deal,
    FunderLink,
    HarvestRun,
    HarvestState,
    Institution,
    IssnMap,
    JiscFunder,
    JiscPublication,
    JiscPublisher,
    JiscRepository,
    Journal,
    OpenaireWorkFacts,
    OpenalexFunder,
    OpenalexWork,
    OpenalexWorkAuthor,
    Publisher,
    PureOrg,
    PureOrgParent,
    PurePerson,
    SourceRecord,
    Work,
    WorkFunder,
    WorkIdentity,
    WorkPureAuthor,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


async def _run(db, source, entity_type, inst=None, **kw):
    kw.setdefault("config_fingerprint", "test")
    run = HarvestRun(
        source=source, entity_type=entity_type, institution_id=inst.id if inst else None, **kw
    )
    db.add(run)
    await db.flush()
    return run


def _mk_work(db, inst, uuid, run, *, doi=None, issn=None, title=None, year=2021, **kw):
    title = title or f"T {uuid}"
    work = Work(
        institution_id=inst.id,
        pure_uuid=uuid,
        doi_normalized=doi,
        title=title,
        norm_title=title.lower(),
        year=year,
        journal_issn_l=issn,
        first_seen_run=run.id,
        last_seen_run=run.id,
        **kw,
    )
    db.add(work)
    return work


async def _land(db, run, source, entity_type, pk, payload, *, harvested_at=None):
    db.add(
        SourceRecord(
            source=source,
            entity_type=entity_type,
            source_pk=str(pk),
            payload=payload,
            content_hash=content_hash(payload),
            harvest_run_id=run.id,
            **({"harvested_at": harvested_at} if harvested_at else {}),
        )
    )


# ── DOAJ journal CSV ──────────────────────────────────────────────────────


@requires_db
async def test_doaj_harvest(db, monkeypatch):
    """The DOAJ CSV stamps matched journals (direct and variant ISSN) and
    marks swept-but-unlisted OA candidates; a renamed column or a page
    without usable ISSNs fails the run instead of landing silent zeros."""
    db.add_all(
        [
            journal_factory("1569-8432", is_oa=True, search_text=None),
            journal_factory(
                "0303-2434", is_oa=True, issns=["0303-2434", "1569-8432"], search_text=None
            ),
            journal_factory("9999-9991", is_oa=True, search_text=None),
            journal_factory("3333-3339", search_text=None),
        ]
    )
    await db.commit()
    payload = _load("doaj_page.json")

    def _download(csv: bytes):
        async def _d(*a, **kw):
            return csv, True

        return _d

    doaj_dl = "journal_browser.harvest.doaj.download_to_landing"
    monkeypatch.setattr(doaj_dl, _download(payload["csv"].encode()))
    stats = await harvest_doaj(db)
    assert stats["journals_matched"] == 2 and stats["stamped_not_listed"] == 1
    rows = {j.issn_l: j for j in (await db.execute(select(Journal))).scalars()}
    for issn in ("1569-8432", "0303-2434"):
        row = rows[issn]
        assert (row.doaj_in_doaj, row.doaj_has_apc) == (True, True)
        assert (row.doaj_apc_max, row.doaj_apc_currency) == (3610.0, "USD")
        assert row.doaj_homepage_url == "https://www.sciencedirect.com/journal/jag"
        assert row.doaj_harvested_at is not None
    assert rows["9999-9991"].doaj_in_doaj is False  # OA candidate, not listed
    assert rows["3333-3339"].doaj_in_doaj is None  # no OA evidence, untouched

    for csv, match in (
        (payload["renamed_column"], "missing columns"),
        (payload["no_issn"], "zero ISSN-bearing rows"),
    ):
        monkeypatch.setattr(doaj_dl, _download(csv.encode()))
        with pytest.raises(HarvestDataError, match=match):
            await harvest_doaj(db)
        await db.rollback()


# ── OpenAlex source page upsert ───────────────────────────────────────────


@requires_db
async def test_openalex_page_upsert(db):
    """Bulk page upsert: last payload wins per issn_l, variants land in
    issn_map, later pages update in place, and an upstream issn_l re-key of
    a known openalex_id is skipped instead of aborting the page."""
    page = _load("openalex_source_page.json")
    assert await _upsert_journal_page(db, page["old_key"]) == 1
    await db.flush()
    # Same openalex_id under a new issn_l: journals row skipped, page survives.
    assert await _upsert_journal_page(db, page["rekey_page"]) == 1
    await db.flush()
    assert await db.get(Journal, "2227-2437") is None
    assert (await db.get(Journal, "0043-1354")).title == "Old key"

    assert await _upsert_journal_page(db, page["page"]) == 2
    await db.flush()
    row = await db.get(Journal, "0043-1354")
    assert (row.title, row.openalex_id, row.search_text) == ("Second", "S2", "Second")
    maps = (await db.execute(select(IssnMap).where(IssnMap.issn_l == "0043-1354"))).scalars()
    assert {m.issn: m.issn_l for m in maps} == {
        "0043-1354": "0043-1354",
        "1234-5679": "0043-1354",
    }


# ── OpenAlex works rebuild ────────────────────────────────────────────────

_PRIMARY = {
    "source": {
        "id": "https://openalex.org/S123",
        "display_name": "Journal One",
        "type": "journal",
    }
}


def _work(w_id, *, title="Work One", type_="article", doi="10.1234/abc", oa="gold", cited=9):
    return {
        "id": f"https://openalex.org/{w_id}",
        "doi": doi and f"https://doi.org/{doi}",
        "display_name": title,
        "publication_year": 2023,
        "type": type_,
        "open_access": {"oa_status": oa},
        "primary_location": _PRIMARY,
        "language": "en",
        "authorships": [
            {"author": {"id": f"https://openalex.org/{a}", "display_name": f"Author {a}"}}
            for a in ("A1", "A2")
        ],
        "cited_by_count": cited,
        "fwci": 1.2,
        "is_retracted": False,
    }


async def _seed_sweep(db, inst, records, *, filter_set):
    run = await _run(db, "openalex", "works_stats", inst, status="completed")
    db.add(
        HarvestState(
            source="openalex",
            entity_type="works_stats",
            filter_set=filter_set,
            institution_id=inst.id,
            last_run_id=run.id,
        )
    )
    base = datetime.now(UTC) - timedelta(hours=24)
    for i, (pk, payload) in enumerate(records):
        db.add(
            SourceRecord(
                source="openalex",
                entity_type="works_stats",
                source_pk=pk,
                payload=payload,
                publication_year=payload.get("publication_year"),
                content_hash=f"h-{pk}-{i}",
                harvested_at=base + timedelta(minutes=i),
                harvest_run_id=run.id,
            )
        )
    await db.flush()
    return run


@requires_db
async def test_openalex_works_rebuild(db, institution_factory):
    """Latest payload wins per W-id, excluded types and other institutions'
    records stay out, attribution edges ride along, and works rows frozen at
    enrichment time fold the store's fresh oa_status in."""
    ut = await institution_factory(code="ut")
    rug = await institution_factory(code="rug")
    db.add(journal_factory("1234-5678", openalex_id="S123"))
    await db.flush()
    await _seed_sweep(
        db,
        ut,
        [
            ("W1", _work("W1", title="Old")),
            ("W1", _work("W1", title="New", oa="green", doi="10.1234/went-green")),
        ],
        filter_set="institutions.id=UT",
    )
    await _seed_sweep(db, ut, [("W2", _work("W2"))], filter_set="author-sweep:0")
    await _seed_sweep(db, ut, [("W3", _work("W3", type_="preprint"))], filter_set="author-sweep:1")
    await _seed_sweep(
        db,
        ut,
        [("W4", _work("W4", oa="closed", doi="10.1234/reversed"))],
        filter_set="institutions.id=UT,from_publication_date:2026",
    )
    await _seed_sweep(db, rug, [("W9", _work("W9"))], filter_set="institutions.id=RUG")
    run = await _run(db, "test", "works", ut)
    db.add_all(
        [
            _mk_work(
                db,
                ut,
                "w-stale",
                run,
                doi="10.1234/went-green",
                title="W w-stale",
                year=2024,
                oa_status="closed",
            ),
            _mk_work(
                db,
                ut,
                "w-rev",
                run,
                doi="10.1234/reversed",
                title="W w-rev",
                year=2024,
                oa_status="green",
            ),
        ]
    )
    await db.flush()

    stats = await rebuild_openalex_works(db, ut)
    assert stats["works"] == 3  # W1+W2+W4; preprint excluded, rug's W9 out of scope
    assert stats["excluded_types"] == 1 and stats["author_sweep_rows"] == 1
    assert stats["works_oa_synced"] == 2  # w-stale closed->green, w-rev green->closed
    rows = {r.w_id: r for r in (await db.execute(select(OpenalexWork))).scalars()}
    assert set(rows) == {"W1", "W2", "W4"}
    assert rows["W1"].title == "New" and rows["W1"].cited_by_count == 9
    assert rows["W1"].source == "works_stats" and rows["W2"].source == "author-sweep"
    pairs = (await db.execute(select(OpenalexWorkAuthor))).scalars()
    assert {(p.w_id, p.author_id) for p in pairs} == {
        (w, a) for w in ("W1", "W2", "W4") for a in ("a1", "a2")
    }
    works = {r.pure_uuid: r.oa_status for r in (await db.execute(select(Work))).scalars()}
    assert works == {"w-stale": "green", "w-rev": "closed"}


@requires_db
async def test_foldback_openalex_wins_oa_colour_conflict(db, institution_factory):
    """Precedence (owner decision 2026-11-20, evidence in
    scripts/analyze_oa_conflicts.py): when openaire_work_facts states a
    colour that conflicts with the OpenAlex store, the fold-back keeps the
    OpenAlex colour. The OpenAIRE claim never writes works.oa_status, and
    the sync stays idempotent on rerun."""
    ut = await institution_factory(code="ut")
    work_run = await _run(db, "pure", "work", ut)
    _mk_work(db, ut, "w-conflict", work_run, doi="10.1234/conflict", oa_status="gold")
    await db.flush()
    db.add(
        OpenaireWorkFacts(
            institution_id=ut.id, pure_uuid="w-conflict", source_pk="openaire::1", oa_color="gold"
        )
    )
    await _seed_sweep(
        db,
        ut,
        [("W1", _work("W1", doi="10.1234/conflict", oa="green"))],
        filter_set="institutions.id=UT",
    )
    await db.flush()

    stats = await rebuild_openalex_works(db, ut)
    assert stats["works_oa_synced"] == 1
    stored = dict(
        (
            await db.execute(
                select(Work.pure_uuid, Work.oa_status).where(Work.institution_id == ut.id)
            )
        ).all()
    )
    assert stored == {"w-conflict": "green"}

    # Rerunning the fold-back never flips the colour to the OpenAIRE claim.
    await rebuild_openalex_works(db, ut)
    stored = dict(
        (
            await db.execute(
                select(Work.pure_uuid, Work.oa_status).where(Work.institution_id == ut.id)
            )
        ).all()
    )
    assert stored == {"w-conflict": "green"}


@requires_db
async def test_foldback_oa_colour_passthrough_without_conflict(db, institution_factory):
    """Non-conflict passthrough: an agreeing OpenAIRE colour and a silent
    (NULL) one both leave the OpenAlex store colour in place."""
    ut = await institution_factory(code="ut")
    work_run = await _run(db, "pure", "work", ut)
    _mk_work(db, ut, "w-agree", work_run, doi="10.1234/agree")
    _mk_work(db, ut, "w-silent", work_run, doi="10.1234/silent")
    await db.flush()
    db.add_all(
        [
            OpenaireWorkFacts(
                institution_id=ut.id, pure_uuid="w-agree", source_pk="openaire::1", oa_color="gold"
            ),
            OpenaireWorkFacts(
                institution_id=ut.id, pure_uuid="w-silent", source_pk="openaire::2", oa_color=None
            ),
        ]
    )
    await _seed_sweep(
        db,
        ut,
        [
            ("W2", _work("W2", doi="10.1234/agree", oa="gold")),
            ("W3", _work("W3", doi="10.1234/silent", oa="hybrid")),
        ],
        filter_set="institutions.id=UT",
    )
    await db.flush()

    stats = await rebuild_openalex_works(db, ut)
    assert stats["works_oa_synced"] == 2
    stored = dict(
        (
            await db.execute(
                select(Work.pure_uuid, Work.oa_status).where(Work.institution_id == ut.id)
            )
        ).all()
    )
    assert stored == {"w-agree": "gold", "w-silent": "hybrid"}


# ── JISC Open Policy Finder normalize ─────────────────────────────────────


@requires_db
async def test_jisc_normalize(db):
    """The OPF landing corpus normalizes into the canon tables, resolves
    issn_l through journals, variants and issn_map, merges the per-journal
    policy display object, and reruns idempotently. An empty landing is a
    loud failure, not a zero-row success."""
    with pytest.raises(HarvestDataError, match="no jisc_opf source_records"):
        await normalize_jisc(db)
    await db.rollback()

    corpus = _load("jisc_opf_corpus.json")
    run = await _run(db, "jisc_opf", "publication")
    for kind, pk, key in (
        ("publication", 101, "pub_101"),
        ("publication", 102, "pub_102"),
        ("publication", 103, "pub_103"),
        ("publisher_policy", 500, "policy_500"),
        ("funder", 700, "funder_700"),
        ("funder_group", 800, "funder_group_800"),
        ("repository", 421, "repository_421"),
    ):
        await _land(db, run, "jisc_opf", kind, pk, corpus[key])
    await _land(
        db,
        run,
        "jisc_opf",
        "publisher",
        900,
        corpus["publisher_old"],
        harvested_at=datetime.now(UTC) - timedelta(hours=1),
    )
    await _land(db, run, "jisc_opf", "publisher", 900, corpus["publisher_new"])
    db.add(IssnMap(issn="3333-3333", issn_l="3333-3330", source="test"))
    db.add_all(
        [
            journal_factory("1111-1111", issns=["1111-1111", "2222-2222"]),
            journal_factory("9999-9999"),
        ]
    )
    await db.commit()

    stats = await normalize_jisc(db)
    await db.commit()
    assert stats["jisc_publications"] == 3 and stats["journals_matched"] == 1
    assert stats["embargo_present"] == 1
    pubs = {p.id: p for p in (await db.execute(select(JiscPublication))).scalars()}
    assert pubs[101].title == "Journal One" and pubs[101].listed_in_doaj is True
    assert pubs[101].policy_ids == [500]
    assert pubs[102].issn_l == "1111-1111"  # variant ISSN -> journal issn_l
    assert pubs[103].issn_l == "3333-3330"  # issn_map-only resolution
    assert (await db.get(JiscPublisher, 900)).name == "Example Publisher"  # newer payload wins
    assert (await db.get(JiscRepository, 421)).software == "dspace"
    funder = await db.get(JiscFunder, 700)
    assert funder.name == "NWO"
    assert funder.publications_policy == {  # notes_phrases sibling stripped
        "archiving_policy": "can",
        "urls": [],
        "policy_effective_date": "2020-01-01",
    }

    j = await db.get(Journal, "1111-1111")
    assert j.jisc_in_opf is True and j.jisc_oa_prohibited is True  # policy 501 prohibits
    flags = (j.jisc_allows_sa_submitted, j.jisc_allows_sa_accepted, j.jisc_allows_sa_published)
    assert flags == (True, False, True)  # accepted is fee-only
    assert j.jisc_embargo_accepted_months == 6
    assert j.jisc_policy == corpus["expected_policy"]
    assert (await db.get(Journal, "9999-9999")).jisc_in_opf is None  # tri-state: unswept

    assert (await normalize_jisc(db))["jisc_publications"] == 3  # rerun: no growth
    await db.commit()
    pubs = await db.scalar(select(func.count()).select_from(JiscPublication))
    assert pubs == 3


# ── JISC OPF retrieve sweep (mocked transport) ────────────────────────────


class _FakeIngest:
    def __init__(self) -> None:
        self.pks: list[str] = []

    async def ingest_records(self, records):
        self.pks.extend(pk for pk, _ in records)
        return len(records)

    async def commit(self):
        return None


async def test_jisc_opf_sweep_pagination_and_cap():
    pages = _load("jisc_opf_pages.json")
    seen: list[dict] = []

    async def paginated(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=pages["pages"][len(seen) - 1])

    ingest = _FakeIngest()
    async with httpx.AsyncClient(transport=httpx.MockTransport(paginated)) as client:
        stats = await jisc.sweep_type(client, ingest, "publisher", sleep_s=0)
    assert ingest.pks == ["1", "2", "3"]
    assert [p.get("search_after") for p in seen] == [None, "[9]"]
    assert seen[0]["item-type"] == "publisher" and seen[0]["format"] == "Json"
    assert stats == {"item_type": "publisher", "pages": 2, "records": 3, "skipped": 0}

    served = 0

    async def endless(request: httpx.Request) -> httpx.Response:
        nonlocal served
        served += 1
        return httpx.Response(200, json=pages["cap_page"])

    ingest = _FakeIngest()
    async with httpx.AsyncClient(transport=httpx.MockTransport(endless)) as client:
        stats = await jisc.sweep_type(client, ingest, "publisher", sleep_s=0, max_records=2)
    assert ingest.pks == ["10", "11"] and served == 1
    assert stats == {"item_type": "publisher", "pages": 1, "records": 2, "skipped": 0}


# ── JISC green-OA serving outcome ─────────────────────────────────────────


@pytest.fixture
async def jisc_api(client, db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        policy = {"routes": {}, "policy_uri": "https://openpolicyfinder.jisc.ac.uk/publication/1"}
        session.add_all(
            [
                journal_factory(
                    "1111-1111",
                    title="Accepted",
                    search_text=None,
                    jisc_in_opf=True,
                    jisc_allows_sa_accepted=True,
                    jisc_policy=policy,
                    jisc_harvested_at=datetime(2026, 11, 2, 12, 0, tzinfo=UTC),
                ),
                journal_factory(
                    "2222-2222",
                    title="Submitted",
                    search_text=None,
                    jisc_in_opf=True,
                    jisc_allows_sa_submitted=True,
                ),
                journal_factory(
                    "3333-3333",
                    title="Prohibited",
                    search_text=None,
                    jisc_in_opf=True,
                    jisc_oa_prohibited=True,
                ),
                journal_factory(
                    "4444-4444",
                    title="Published",
                    search_text=None,
                    jisc_in_opf=True,
                    jisc_allows_sa_published=True,
                ),
                journal_factory("5555-5555", title="Unswept", search_text=None),
                journal_factory(
                    "6666-6666",
                    title="Prohibited With Route",
                    search_text=None,
                    jisc_in_opf=True,
                    jisc_oa_prohibited=True,
                    jisc_allows_sa_submitted=True,
                ),
            ]
        )
        home = Institution(name="University of Twente", code="ut", active=True)
        session.add(home)
        await session.flush()
        await session.execute(MATERIALIZE_SQL, {"iid": home.id})
        await session.execute(
            text("UPDATE journal_flags SET works_window_plus = 10 WHERE institution_id = :iid"),
            {"iid": home.id},
        )
        await session.commit()
    return client


@requires_db
async def test_jisc_green_oa_serving(jisc_api):
    def issns(r):
        return {i["issn_l"] for i in r.json()["items"]}

    assert issns(await jisc_api.get("/api/v1/ut/journals", params={"green_oa": "accepted"})) == {
        "1111-1111"
    }
    # "none" = in OPF but no permitted route; unswept is not a bucket.
    assert issns(await jisc_api.get("/api/v1/ut/journals", params={"green_oa": "none"})) == {
        "3333-3333",
        "6666-6666",
    }
    # Prohibition wins over a permitted route.
    body = await jisc_api.get("/api/v1/ut/journals", params={"green_oa": "submitted"})
    assert "6666-6666" not in issns(body)
    plain = (await jisc_api.get("/api/v1/ut/journals")).json()
    assert plain["facets"]["green_oa"] == {"submitted": 1, "accepted": 1, "published": 1, "none": 2}
    junk = await jisc_api.get("/api/v1/ut/journals", params={"green_oa": "banana"})
    assert junk.status_code == 422


# ── openaccess.nl deal pages ──────────────────────────────────────────────

DEAL_URL = "https://www.openaccess.nl/en/publisherdeal/elsevier-2025-2027"


@requires_db
async def test_openaccess_nl_deal_upsert(db):
    """Parsed deal pages upsert on the natural key (update in place, never a
    duplicate), flag parse gaps for curation, and a reason-aware dismissal
    only suppresses the same reason."""
    pages = _load("openaccess_nl_pages.json")
    page = parse_deal_page(pages["deal"], DEAL_URL)
    assert page["cap_numbers"] == {"2024": 733, "2025": 707, "2026": 680}
    assert page["contract_url"].endswith("contract.pdf")
    missing = parse_deal_page(pages["deal_missing"], DEAL_URL)
    assert missing["curation_reasons"] == [
        "missing summary",
        "missing 'How does it work?' section",
        "ambiguous cap numbers",
    ]

    item = {
        "duration_text": "2025-2027",
        "start_year": 2025,
        "end_year": 2027,
        "per_year_oa_counts": {"2025": 7429},
        "status": "current",
    }
    pub = await _upsert_publisher(db, "elsevier", "Elsevier")
    assert await _upsert_deal(db, pub.id, item, page) is False  # created
    flagged = dict(page, summary=None, curation_reasons=["missing summary"])
    assert await _upsert_deal(db, pub.id, item, flagged) is True  # same key: updated
    await db.flush()
    deal = await db.scalar(select(Deal))
    assert deal.needs_curation is True and deal.needs_curation_reason == "missing summary"
    assert deal.provenance[0]["source"] == "openaccess.nl"

    deal.needs_curation = False
    deal.needs_curation_reason = None
    deal.curation_resolved_reason = "missing summary"
    await db.flush()
    assert await _upsert_deal(db, pub.id, item, flagged) is False  # dismissal suppresses
    await db.flush()
    await db.refresh(deal)
    assert deal.needs_curation is False and deal.curation_resolved_reason == "missing summary"
    reflagged = dict(flagged, curation_reasons=["ambiguous cap numbers"])
    assert await _upsert_deal(db, pub.id, item, reflagged) is True  # new reason re-flags
    await db.flush()
    await db.refresh(deal)
    assert deal.needs_curation_reason == "ambiguous cap numbers"
    assert deal.curation_resolved_reason is None
    assert await db.scalar(select(func.count()).select_from(Deal)) == 1


@requires_db
async def test_openaccess_nl_upsert_matches_page_url_and_owner_window(db):
    """The page URL is the global identity: a canonical agreement on a
    differently named publisher row is updated in place instead of forked,
    and an owner-curated local period window survives the refresh."""
    pages = _load("openaccess_nl_pages.json")
    page = parse_deal_page(pages["deal"], DEAL_URL)
    item = {
        "duration_text": "2025-2027",
        "start_year": 2025,
        "end_year": 2027,
        "per_year_oa_counts": {"2025": 7429},
        "status": "current",
    }
    # Canonical on the JCT placeholder publisher ("ELS", no slug): only
    # the URL finds it.
    placeholder = Publisher(name="ELS")
    db.add(placeholder)
    await db.flush()
    canonical = Deal(
        publisher_id=placeholder.id,
        status="current",
        corresponding_authors_only=False,
        provenance=[{"source": "jct", "url": "https://jct.example/els.csv"}],
        duration_text="2025-2027",
        openaccess_nl_url=DEAL_URL,
    )
    db.add(canonical)
    await db.flush()
    display = await _upsert_publisher(db, "elsevier", "Elsevier")
    assert await _upsert_deal(db, display.id, item, page) is False  # updated, not created
    await db.flush()
    await db.refresh(canonical)
    assert await db.scalar(select(func.count()).select_from(Deal)) == 1
    assert canonical.publisher_id == placeholder.id  # stays on the JCT row
    assert canonical.summary == page["summary"]
    assert canonical.provenance is not None
    assert {p["source"] for p in canonical.provenance} == {"jct", "openaccess.nl"}

    # Owner-curated window: the page's programme period does not win.
    acm_page = dict(
        page, openaccess_nl_url="https://www.openaccess.nl/en/publisherdeal/acm-2021-2030"
    )
    acm_item = {
        "duration_text": "2021-2030",
        "start_year": 2021,
        "end_year": 2030,
        "per_year_oa_counts": {},
        "status": "current",
    }
    local = Deal(
        publisher_id=display.id,
        status="current",
        corresponding_authors_only=False,
        provenance=[{"source": "owner_curation", "date": "2026-10-22"}],
        duration_text="2026-2028 (Twente local deal)",
        start_year=2026,
        end_year=2028,
        openaccess_nl_url=acm_page["openaccess_nl_url"],
    )
    db.add(local)
    await db.flush()
    assert await _upsert_deal(db, display.id, acm_item, acm_page) is False
    await db.flush()
    await db.refresh(local)
    assert (local.start_year, local.end_year) == (2026, 2028)
    assert "Twente local deal" in local.duration_text
    assert local.provenance is not None
    assert {p["source"] for p in local.provenance} == {"owner_curation", "openaccess.nl"}


# ── OpenAIRE work facts ───────────────────────────────────────────────────


@requires_db
async def test_openaire_facts_derive_idempotent_and_served(db, institution_factory, client):
    payload = _load("openaire_work_payload.json")
    inst = await institution_factory(code="tu")
    db.add(journal_factory("1234-5678"))
    run = await _run(db, "test", "works", inst)
    _mk_work(db, inst, "pw1", run, doi="10.1/w1", issn="1234-5678", work_type="article")
    oa_run = await _run(db, "openaire", "work", inst)
    await _land(db, oa_run, "openaire", "work", "oa-1", payload)
    db.add(
        WorkIdentity(
            institution_id=inst.id,
            source="openaire",
            source_pk="oa-1",
            work_id="pw1",
            matched_by="doi",
            confidence=1.0,
            status="confirmed",
        )
    )
    await db.commit()

    stats = await derive_openaire_facts(db, inst)
    await db.commit()
    assert stats["upserted"] == 1 and stats["diamond"] == 1 and stats["with_usage"] == 1
    r = await client.get("/api/v1/tu/journals/1234-5678/works")
    assert r.status_code == 200
    item = next(i for i in r.json()["items"] if i["title"] == "T pw1")
    assert item["openaire"] == {
        "views": 12,
        "downloads": 3,
        "oa_url": "https://example.org/final.pdf",
        "license": "cc-by-4.0",
        "oa_color": "gold",
        "diamond": True,
        "embargo_end": "2027-03-15",
        "fos": ["0101 mathematics", "0102 computer and information sciences"],
        "projects": [
            {"id": "nwo_________::a1", "funder": "NWO", "code": "13544", "acronym": "COPD"},
            {"id": "ec_________::a2", "funder": "EC", "code": None, "acronym": None},
        ],
    }

    stats = await derive_openaire_facts(db, inst)
    await db.commit()
    assert stats["upserted"] == 1 and stats["pruned"] == 0
    assert await db.scalar(select(func.count()).select_from(OpenaireWorkFacts)) == 1
    # An unconfirmed identity prunes the derived row on the next refresh.
    await db.execute(
        WorkIdentity.__table__.update()
        .where(WorkIdentity.source_pk == "oa-1")
        .values(status="missing")
    )
    await db.commit()
    assert (await derive_openaire_facts(db, inst))["pruned"] == 1
    await db.commit()
    assert await db.scalar(select(func.count()).select_from(OpenaireWorkFacts)) == 0


# ── Work funders (OpenAlex awards) ────────────────────────────────────────


def _award(funder_id, name=None, award_id=None):
    return {
        "funder_id": f"https://openalex.org/{funder_id}" if funder_id else None,
        "funder_display_name": name,
        "funder_award_id": award_id,
    }


@requires_db
async def test_work_funders_upsert_and_raw_payloads(db, institution_factory, monkeypatch):
    inst = await institution_factory(code="ut")
    run = await _run(db, "test", "works", inst)
    _mk_work(db, inst, "uuid-a", run, doi="10.1234/abc", title="t", year=2020)
    await db.commit()

    rows = grants_rows(inst.id, "uuid-a", [_award("F1", "NWO", "100"), _award("F2", "EC", "200")])
    assert await _upsert(db, rows) == 2
    await db.commit()
    rows[0]["award"] = "100b"
    assert await _upsert(db, rows) == 2  # rerun: refresh in place, no growth
    await db.commit()
    fresh = grants_rows(inst.id, "uuid-a", [_award("F1", "NWO", "100b")])
    stored_work = (await db.execute(select(Work))).scalar_one()
    assert await _prune(db, [stored_work], fresh) == 1
    await db.commit()
    stored = (
        (await db.execute(select(WorkFunder).execution_options(populate_existing=True)))
        .scalars()
        .all()
    )
    assert [f.funder_openalex_id for f in stored] == ["F1"]


@requires_db
async def test_harvest_work_funders_stores_raw_payload(db, institution_factory, monkeypatch):
    """The sweep stores the fetched work payload verbatim in source_records
    under a completed run (deduped by content hash in production)."""
    from journal_browser.harvest import work_funders as wfm

    inst = await institution_factory(code="ut")
    run = await _run(db, "test", "works", inst)
    _mk_work(db, inst, "uuid-raw", run, doi="10.1234/wf-raw", title="t", year=2020)
    await db.commit()

    class _FakeAwardWork:
        id = "W999"

        def __init__(self):
            self.awards = []

        def model_dump(self, mode="json"):
            return {"id": self.id, "awards": self.awards}

    async def _fake_fetch(client, dois, stats=None):
        return {doi: _FakeAwardWork() for doi in dois}, set(), None

    class _FakeClient:
        def __init__(self, **kwargs): ...

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(wfm, "fetch_works_by_doi", _fake_fetch)
    monkeypatch.setattr(wfm, "AlethecaClient", _FakeClient)
    stats = await harvest_work_funders(db)
    assert stats["rows_upserted"] == 0 and stats["records_stored"] == 1
    raw = (
        await db.execute(
            select(SourceRecord).where(
                SourceRecord.source == "openalex",
                SourceRecord.entity_type == "work",
                SourceRecord.source_pk == "W999",
            )
        )
    ).scalar_one()
    assert raw.payload["id"] == "W999"  # raw awards payload kept verbatim
    assert (await db.get(HarvestRun, raw.harvest_run_id)).status == "completed"


# ── Funder canon normalization ────────────────────────────────────────────


@requires_db
async def test_funder_normalization_idempotent(db):
    run = await _run(db, "jisc_opf", "funder")
    await _land(
        db, run, "jisc_opf", "funder", 701, _load("jisc_opf_corpus.json")["funder_with_ids"]
    )
    await db.commit()

    assert (await normalize_jisc(db))["jisc_funders"] == 1
    funder = await db.get(JiscFunder, 701)
    assert (funder.ror, funder.fundref) == ("04ad7pn51", "100009795")
    await db.commit()
    assert (await normalize_jisc(db))["jisc_funders"] == 1  # rerun: still one row
    await db.commit()
    rows = (await db.execute(select(JiscFunder).where(JiscFunder.id == 701))).scalars().all()
    assert len(rows) == 1

    row = {
        "openalex_id": "F4320330286",
        "ror": None,
        "fundref": None,
        "display_name": "NWO",
        "country_code": "nl",
        "description": None,
        "grant_count": 1,
        "works_count": 2,
        "cited_by_count": 3,
    }
    assert await upsert_canon(db, OpenalexFunder, "openalex_id", [row]) == 1
    assert await upsert_canon(db, OpenalexFunder, "openalex_id", [dict(row, grant_count=9)]) == 1
    await db.commit()
    of = (
        await db.execute(select(OpenalexFunder).where(OpenalexFunder.openalex_id == "F4320330286"))
    ).scalar_one()
    assert of.grant_count == 9

    # One OpenAlex twin matching a jisc funder via BOTH keys links once, ror
    # wins (used to violate funder_links_pkey on the fundref insert).
    db.add(JiscFunder(id=702, ror="04ad7pn51", fundref="100009795"))
    db.add(OpenalexFunder(openalex_id="F1", ror="04ad7pn51", fundref="100009795"))
    await db.flush()
    assert await refresh_funder_links(db) == 2  # 701 and 702, one link each
    links = (
        (await db.execute(select(FunderLink).where(FunderLink.funder_id == 702))).scalars().all()
    )
    assert [(x.source, x.source_id, x.via) for x in links] == [("openalex", "F1", "ror")]


# ── Journals delta (free singleton gap-fill) ──────────────────────────────


class _SourceEntity:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self, mode="json"):
        return self._payload


class _NotFound(Exception):
    def __init__(self):
        self.response = SimpleNamespace(status_code=404)


class _FakeSourcesClient:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls: list[str] = []
        self.sources = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url: str):
        self.calls.append(url)
        payload = self.payloads.get(url.rsplit("/", 1)[-1])
        if payload is None:
            raise _NotFound()
        return _SourceEntity(payload)


@requires_db
async def test_journals_delta_fetches_only_missing(db):
    run = await _run(db, "test", "works")
    db.add(
        Journal(
            issn_l="2222-2227",
            openalex_id="S9999999999",
            title="Known",
            search_text="Known",
            type="journal",
        )
    )
    for pk, source_id in (("doi:10.9999/x1", "S1234567890"), ("doi:10.9999/x2", "S9999999999")):
        db.add(
            SourceRecord(
                source="openalex",
                entity_type="work",
                source_pk=pk,
                payload={
                    "primary_location": {"source": {"id": f"https://openalex.org/{source_id}"}}
                },
                content_hash=f"h-{pk}",
                harvest_run_id=run.id,
            )
        )
    await db.commit()

    payload = {
        "id": "https://openalex.org/S1234567890",
        "issn_l": "1234-5679",
        "issns": ["1234-5678", "1234-5679"],
        "display_name": "Delta Journal of Testing",
        "counts_by_year": [],
        "topics": [],
    }
    client = _FakeSourcesClient({"S1234567890": payload})
    stats = await harvest_journals_delta(client, db)
    assert stats["referenced"] == 2 and stats["todo"] == 1 and stats["ingested"] == 1
    assert client.calls == ["https://openalex.org/S1234567890"]
    journal = (
        await db.execute(select(Journal).where(Journal.openalex_id == "S1234567890"))
    ).scalar_one()
    assert (journal.issn_l, journal.title) == ("1234-5679", "Delta Journal of Testing")
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
    stats2 = await harvest_journals_delta(client, db)
    assert stats2["todo"] == 0 and len(client.calls) == 1  # rerun fetches nothing


# ── Pure portal org tree ──────────────────────────────────────────────────

EEMCS = "Faculty of Electrical Engineering, Mathematics and Computer Science"


async def test_pure_portal_walk_dedupes():
    def channel(items: list[str]) -> bytes:
        body = "".join(items)
        return (
            '<?xml version="1.0" encoding="utf-8"?><rss version="2.0">'
            f"<channel><title>Research units</title>{body}</channel></rss>"
        ).encode()

    def raw_item(name, slug):
        return (
            f"<item><title>{name}</title>"
            f"<link>https://research.utwente.nl/en/organisations/{slug}/</link>"
            "<description></description></item>"
        )

    pages = [
        channel([raw_item("Alpha", "a"), raw_item("Beta", "b")]),
        channel([raw_item("Beta", "b"), raw_item("Gamma", "c")]),
        channel([]),
    ]

    async def fetch_page(page: int) -> bytes:
        return pages[page - 1]

    units = await walk_portal_orgs(fetch_page, page_delay=0)
    assert [(u.slug, u.name) for u in units] == [("a", "Alpha"), ("b", "Beta"), ("c", "Gamma")]


@requires_db
async def test_pure_portal_apply_tree_contract(db, institution_factory):
    """Edges fill gaps only, institutes stay root-pinned, already-parented
    orgs are untouched, and UT-side org types upgrade from the feed."""
    inst = await institution_factory(
        code="ut", name="University of Twente", ror="https://ror.org/006hf6230"
    )
    db.add_all(
        [
            PureOrg(
                institution_id=inst.id,
                uuid="ut-root",
                name="University of Twente",
                org_type="university",
            ),
            PureOrg(institution_id=inst.id, uuid="eemcs-uuid", name=EEMCS, org_type="faculty"),
            PureOrg(institution_id=inst.id, uuid="sor-uuid", name="Stochastic Operations Research"),
            PureOrg(institution_id=inst.id, uuid="moai-uuid", name="Mathematics of Imaging & AI"),
            PureOrg(
                institution_id=inst.id,
                uuid="dsi-uuid",
                name="Digital Society Institute",
                org_type="institute",
            ),
            PureOrg(
                institution_id=inst.id,
                uuid="mesa-uuid",
                name="MESA+ Institute",
                org_type="institute",
            ),
            PureOrgParent(
                institution_id=inst.id,
                org_uuid="mesa-uuid",
                parent_uuid="ut-root",
                parent_name="University of Twente",
            ),
            PureOrg(institution_id=inst.id, uuid="old-uuid", name="Old Closed Unit"),
        ]
    )
    await db.flush()

    feed = parse_portal_feed(_load("pure_portal_feed.json")["feed"])
    stats = await apply_portal_tree(db, inst, feed, IngestSession(db), store_payloads=False)
    await db.commit()
    assert stats["matched"] == 5 and stats["edges_added"] == 2  # SOR + MoAI -> EEMCS
    assert stats["already_parented"] == 1 and stats["institute_pinned"] == 1  # MESA+, DSI
    assert stats["no_parent_in_portal"] == 1 and stats["unmatched"] == 0
    assert stats["types_updated"] == 3  # SOR + Old + MoAI -> department
    parents = {
        r.org_uuid: r.parent_uuid for r in (await db.execute(select(PureOrgParent))).scalars()
    }
    assert parents["sor-uuid"] == "eemcs-uuid" and parents["moai-uuid"] == "eemcs-uuid"
    assert "dsi-uuid" not in parents and parents["mesa-uuid"] == "ut-root"
    orgs = {r.uuid: r.org_type for r in (await db.execute(select(PureOrg))).scalars()}
    assert orgs["sor-uuid"] == "department" and orgs["old-uuid"] == "department"
    assert orgs["dsi-uuid"] == "institute" and orgs["mesa-uuid"] == "institute"


# ── Pure backend export import ────────────────────────────────────────────

UUID_1 = "46a63e16-5680-45ff-a9a3-4edc78159aa7"
UUID_2 = "1b2e9d44-22c2-4a44-9e03-0d59c6611b3f"
UUID_3 = "5f3a1c02-8a41-4d3f-9d3e-2c2f55f57c10"
UUID_4 = "9e7b3a11-4f52-4c48-a2b6-7a1d0e9f6d21"


def _export_xml(*records: tuple[str, str]) -> str:
    body = "".join(
        f"<record><header><identifier>{uuid}</identifier>"
        "<datestamp>2026-10-30T14:21:46Z</datestamp>"
        "<setSpec>openaire_cris_publications</setSpec></header>"
        f"<metadata>{xml}</metadata></record>"
        for uuid, xml in records
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">'
        f"<ListRecords>{body}</ListRecords></OAI-PMH>"
    )


def _stream_pk(uuid: str) -> str:
    return f"oai:ris.utwente.nl:publications/{uuid}"


@requires_db
async def test_pure_export_import_and_backfill(db, institution_factory, tmp_path):
    """The backend export stores full-author versions (content-hash deduped),
    the version helper prefers full over the stream's truncated cerif rows
    per uuid and per institution, and the authorship backfill reads through
    it: 3 edges from the full version where the stream kept 1."""
    xml = _load("pure_export_records.json")
    inst = await institution_factory(code="ut", name="University of Twente")
    file = tmp_path / "export.xml"
    file.write_text(_export_xml((UUID_1, xml["full"]), (UUID_2, xml["minimal"])))

    stats = await import_pure_export(db, file, inst)
    assert stats["records_seen"] == 2 and stats["records_stored"] == 2
    rows = (
        (
            await db.execute(
                select(SourceRecord).where(SourceRecord.entity_type == "work_cerif_full")
            )
        )
        .scalars()
        .all()
    )
    assert {r.source_pk for r in rows} == {UUID_1, UUID_2}
    full = next(r for r in rows if r.source_pk == UUID_1)
    assert full.payload["cerif"]["doi"] == "10.1234/full.1"
    authors = publication_contributors(parse_metadata_xml(full.payload["metadata_xml"]), "Author")
    assert len(authors) == 3
    assert authors[2]["affiliations"] == [
        {"affiliation_id": "openaire_cris_orgunits/o-ext", "affiliation_name": "External Institute"}
    ]
    assert (await import_pure_export(db, file, inst))["records_stored"] == 0  # deduped
    await db.commit()

    rug = await institution_factory(code="rug", name="RUG")
    run_full = await _run(db, "pure", "work_cerif_full", inst)
    run_stream = await _run(db, "pure", "work_cerif", inst)
    run_rug = await _run(db, "pure", "work_cerif_full", rug)
    await _land(db, run_rug, "pure", "work_cerif_full", UUID_4, {"metadata_xml": xml["full"]})
    await _land(
        db, run_stream, "pure", "work_cerif", _stream_pk(UUID_1), {"metadata_xml": xml["stream"]}
    )
    await _land(
        db, run_stream, "pure", "work_cerif", _stream_pk(UUID_3), {"metadata_xml": xml["stream"]}
    )
    await db.commit()

    latest = await latest_publication_records(db, inst.id)
    assert set(latest) == {UUID_1, UUID_2, UUID_3}  # rug's UUID_4 invisible
    # UUID_1 came from the import: its cerif-carrying full version wins over
    # the stream row despite the stream being ingested later.
    assert "cerif" in latest[UUID_1] and latest[UUID_1]["cerif"]["doi"] == "10.1234/full.1"
    assert "Second work" in latest[UUID_2]["metadata_xml"]  # import re-serializes
    assert latest[UUID_3]["metadata_xml"] == xml["stream"]  # stream rows keep raw xml

    db.add(
        Work(
            institution_id=inst.id,
            pure_uuid=UUID_1,
            title="Full-author work",
            norm_title="full author work",
            year=2026,
            first_seen_run=run_full.id,
            last_seen_run=run_full.id,
        )
    )
    await db.commit()
    stats = await backfill_pure_work_authors(db, inst)
    # UUID_1: 3 edges from the full version; UUID_3's stream record has an
    # author but no Work row, so works_with_authors counts 2 with 3 edges.
    assert stats["edges"] == 3 and stats["works_with_authors"] == 2
    edges = (
        (await db.execute(select(WorkPureAuthor).where(WorkPureAuthor.work_pure_uuid == UUID_1)))
        .scalars()
        .all()
    )
    assert {e.person_uuid for e in edges} == {"p-a", "p-b", "p-ext"}  # full beat the stream's 1


# ── Pure entity mining ────────────────────────────────────────────────────


@requires_db
async def test_pure_entity_mining_rebuild_contract(db, institution_factory):
    """Mined publication entities insert-if-absent with the origin marker,
    set-derived rows win uuid collisions, and reruns change nothing."""
    records = _load("pure_entity_records.json")
    inst = await institution_factory(code="ut", name="University of Twente")
    run = await _run(db, "pure", "persons", inst)
    await _land(
        db,
        run,
        "pure",
        "work_cerif",
        "oai:ris.utwente.nl:publications/pub-1",
        {"metadata_xml": records["publication"]},
    )
    await _land(
        db,
        run,
        "pure",
        "persons",
        "openaire_cris_persons/p-ut",
        {"metadata_xml": records["person"]},
    )
    await db.commit()

    org_candidates, person_candidates = await mine_publication_entities(db, inst.id)
    assert set(org_candidates) == {"o-eemcs", "o-ext"}  # id-less refs skipped
    assert set(person_candidates) == {"p-ut", "p-ext"}
    org_stats = await rebuild_pure_orgs(db, inst.id, mined=org_candidates)
    assert org_stats == {"orgs": 0, "parents": 0, "mined_orgs": 2, "parse_failures": 0}
    person_stats = await rebuild_pure_persons(db, inst.id, mined=person_candidates)
    assert person_stats == {"persons": 1, "mined_persons": 1, "parse_failures": 0}

    orgs = {r.uuid: r.name for r in (await db.execute(select(PureOrg))).scalars()}
    assert orgs == {"o-eemcs": "EEMCS", "o-ext": "External Institute"}
    persons = {r.uuid: r for r in (await db.execute(select(PurePerson))).scalars()}
    assert set(persons) == {"p-ut", "p-ext"}
    assert persons["p-ut"].orcid == "0000-0002-1825-0097"  # set-derived wins the collision
    assert set(persons["p-ut"].payload) == {"cerif"}
    mined = persons["p-ext"]
    assert mined.name == "Jane Smith" and mined.orcid is None
    assert mined.payload["origin"] == "publication"
    assert set(mined.payload["cerif"]) == {
        "id",
        "family_names",
        "first_names",
        "orcid",
        "scopus_author_id",
        "researcher_id",
        "affiliations",
    }

    org_candidates2, person_candidates2 = await mine_publication_entities(db, inst.id)
    assert (await rebuild_pure_persons(db, inst.id, mined=person_candidates2)) == person_stats
    assert (await rebuild_pure_orgs(db, inst.id, mined=org_candidates2)) == org_stats


# ── Pure re-harvest vs OpenAlex canon OA colour (folded from
#    test_harvest2_store_oa_canon.py) ─────────────────────────────────────


def _pure_payload(uuid: str, doi: str, rights: str) -> dict:
    """Minimal Pure payload; the Eprints rights literal maps
    closedAccess -> closed and openAccess -> green."""
    return {
        "oai_identifier": f"oai:ris.utwente.nl:publications:{uuid}",
        "dc": {
            "title": ["A work"],
            "rights": [f"info:eu-repo/semantics/{rights}"],
            "type": ["article"],
        },
        "doi_normalized": doi,
        "cerif": {},
    }


@requires_db
async def test_pure_reharvest_keeps_canon_oa_color(db, institution_factory):
    """The OpenAlex canon sync is the authoritative oa_status writer for
    DOI-matched works: a Pure re-harvest of a re-seen record must not
    downgrade the canon colour."""
    from journal_browser.harvest.pure.store import upsert_work

    ut = await institution_factory(code="ut")
    run = await _run(db, "pure", "work", ut)
    await upsert_work(
        db,
        _pure_payload("u1", "10.1000/abc", "closedAccess"),
        institution_id=ut.id,
        year=2024,
        run_id=run.id,
    )
    await db.commit()
    stored = dict(
        (
            await db.execute(
                select(Work.pure_uuid, Work.oa_status).where(Work.institution_id == ut.id)
            )
        ).all()
    )
    assert stored == {"u1": "closed"}

    # The canon sync upgrades the colour and OpenAlex carries it.
    await db.execute(
        update(Work)
        .where(Work.institution_id == ut.id, Work.pure_uuid == "u1")
        .values(oa_status="gold")
    )
    db.add(
        OpenalexWork(
            institution_id=ut.id, w_id="W1", doi_normalized="10.1000/abc", oa_status="gold"
        )
    )
    await db.commit()

    # A Pure re-harvest of the same record must not downgrade it.
    await upsert_work(
        db,
        _pure_payload("u1", "10.1000/abc", "closedAccess"),
        institution_id=ut.id,
        year=2024,
        run_id=run.id,
    )
    await db.commit()
    stored = dict(
        (
            await db.execute(
                select(Work.pure_uuid, Work.oa_status).where(Work.institution_id == ut.id)
            )
        ).all()
    )
    assert stored == {"u1": "gold"}


@requires_db
async def test_pure_fills_color_without_openalex_row(db, institution_factory):
    """Without an OpenAlex row for the DOI, Pure rights remain
    authoritative: an upgraded rights value lands on the re-seen record."""
    from journal_browser.harvest.pure.store import upsert_work

    ut = await institution_factory(code="ut")
    run = await _run(db, "pure", "work", ut)
    await upsert_work(
        db,
        _pure_payload("u2", "10.1000/def", "closedAccess"),
        institution_id=ut.id,
        year=2024,
        run_id=run.id,
    )
    await db.commit()
    stored = dict(
        (
            await db.execute(
                select(Work.pure_uuid, Work.oa_status).where(Work.institution_id == ut.id)
            )
        ).all()
    )
    assert stored == {"u2": "closed"}

    await upsert_work(
        db,
        _pure_payload("u2", "10.1000/def", "openAccess"),
        institution_id=ut.id,
        year=2024,
        run_id=run.id,
    )
    await db.commit()
    stored = dict(
        (
            await db.execute(
                select(Work.pure_uuid, Work.oa_status).where(Work.institution_id == ut.id)
            )
        ).all()
    )
    assert stored == {"u2": "green"}


@requires_db
async def test_pure_canon_rule_is_per_doi(db, institution_factory):
    """The keep-canon rule must correlate on the row's own DOI, not apply
    institution-wide: work A (OpenAlex colour) keeps it while work B (no
    OpenAlex row) takes the Pure rights upgrade in the same institution."""
    from journal_browser.harvest.pure.store import upsert_work

    ut = await institution_factory(code="ut")
    run = await _run(db, "pure", "work", ut)
    await upsert_work(
        db,
        _pure_payload("a1", "10.1000/aaa", "closedAccess"),
        institution_id=ut.id,
        year=2024,
        run_id=run.id,
    )
    await upsert_work(
        db,
        _pure_payload("b1", "10.1000/bbb", "closedAccess"),
        institution_id=ut.id,
        year=2024,
        run_id=run.id,
    )
    await db.commit()

    # Only work A is DOI-matched in OpenAlex; the canon sync upgraded it.
    await db.execute(
        update(Work)
        .where(Work.institution_id == ut.id, Work.pure_uuid == "a1")
        .values(oa_status="gold")
    )
    db.add(
        OpenalexWork(
            institution_id=ut.id, w_id="W1", doi_normalized="10.1000/aaa", oa_status="gold"
        )
    )
    await db.commit()

    # One re-harvest sees both records: A's Pure rights are still closed
    # (must keep the canon gold), B's rights upgrade to green (no canon
    # row, so Pure is authoritative — the institution-wide bug kept it
    # closed because A matched).
    await upsert_work(
        db,
        _pure_payload("a1", "10.1000/aaa", "closedAccess"),
        institution_id=ut.id,
        year=2024,
        run_id=run.id,
    )
    await upsert_work(
        db,
        _pure_payload("b1", "10.1000/bbb", "openAccess"),
        institution_id=ut.id,
        year=2024,
        run_id=run.id,
    )
    await db.commit()
    stored = dict(
        (
            await db.execute(
                select(Work.pure_uuid, Work.oa_status).where(Work.institution_id == ut.id)
            )
        ).all()
    )
    assert stored == {"a1": "gold", "b1": "green"}


# ── works.funders_checked_at sweep gate (folded from
#    test_correct_funders_checked_at.py) ──────────────────────────────────


def _award_payload(doi: str, awarded: bool):
    """Minimal OpenAlex work object: id + awards, plus the model_dump the
    ingest session stores."""
    awards = [{"funder_id": "https://openalex.org/F-1"}] if awarded else []
    return SimpleNamespace(
        id=f"https://openalex.org/W-{doi}",
        awards=awards,
        model_dump=lambda mode="json": {"id": f"W-{doi}", "awards": awards},
    )


@requires_db
async def test_work_funders_sweep_gate(db, institution_factory, monkeypatch):
    """works.funders_checked_at gates the work-funders sweep: a failed
    fetch stamps nothing (the next run retries), zero-award works are
    stamped so they leave the sweep, and past the TTL works return to it."""
    ut = await institution_factory(code="ut", data_window_start=2020)
    run = await _run(db, "pure", "works", ut)
    _mk_work(db, ut, "w-awarded", run, doi="10.0.0/awarded", title="w-awarded", year=2023)
    _mk_work(db, ut, "w-bare", run, doi="10.0.0/bare", title="w-bare", year=2023)
    await db.commit()

    async def _failing_fetch(_client, _dois, stats=None):
        if stats is not None:
            stats["fetch_errors"] = 2
        raise RuntimeError("openalex down")

    monkeypatch.setattr("journal_browser.harvest.work_funders.fetch_works_by_doi", _failing_fetch)
    with pytest.raises(RuntimeError, match="openalex down"):
        await harvest_work_funders(db, ttl_days=30)
    stamps = (await db.execute(select(Work.funders_checked_at))).scalars().all()
    assert all(s is None for s in stamps)

    async def _fake_fetch(_client, dois, stats=None):
        return (
            {doi: _award_payload(doi, doi == "10.0.0/awarded") for doi in dois},
            set(),
            None,
        )

    monkeypatch.setattr("journal_browser.harvest.work_funders.fetch_works_by_doi", _fake_fetch)
    stats = await harvest_work_funders(db, ttl_days=30)
    assert stats["works_attempted"] == 2
    rows = (await db.execute(select(Work.pure_uuid, Work.funders_checked_at))).all()
    # Zero-award works are stamped too: they leave the sweep.
    assert all(r.funders_checked_at is not None for r in rows)
    wf = (await db.execute(select(WorkFunder))).scalars().all()
    assert [(w.pure_uuid, w.funder_openalex_id) for w in wf] == [("w-awarded", "F-1")]

    # Fresh stamps skip the sweep entirely.
    stats2 = await harvest_work_funders(db, ttl_days=30)
    assert stats2["works_attempted"] == 0
    assert stats2["skipped_fresh"] == stats2["works_with_doi"] == 2

    # Beyond the TTL the works become eligible again.
    await db.execute(update(Work).values(funders_checked_at=datetime.now(UTC) - timedelta(days=31)))
    stats3 = await harvest_work_funders(db, ttl_days=30)
    assert stats3["works_attempted"] == 2


# ── OpenAlex budget reserve gate ──────────────────────────────────────────


@requires_db
async def test_openalex_reserve_gate_stops_stage(db, institution_factory, monkeypatch):
    """Below the reserve the stage stops cleanly: stats note, no client, no
    run started. The remaining-budget helper is mocked, not HTTP."""
    ut = await institution_factory(code="ut", data_window_start=2020)
    await db.commit()

    async def _low_remaining() -> float:
        return 0.10  # below the 0.25 default reserve

    monkeypatch.setattr("journal_browser.harvest.common.openalex_credits_remaining", _low_remaining)

    class _NoClient:
        def __init__(self, *a, **k):
            raise AssertionError("client constructed despite exhausted budget")

    monkeypatch.setattr("journal_browser.harvest.institution_stats.AlethecaClient", _NoClient)
    assert await openalex_budget_ok("gate") is False

    stats = await harvest_institution_stats(db, ut)
    assert stats["openalex_reserve_stop"] == 1
    assert "reserve" in stats["skipped"]

    # A healthy budget keeps the gate open.
    async def _healthy_remaining() -> float:
        return 5.0

    monkeypatch.setattr(
        "journal_browser.harvest.common.openalex_credits_remaining", _healthy_remaining
    )
    assert await openalex_budget_ok("gate") is True


@requires_db
async def test_enrich_openalex_commits_per_chunk(db, institution_factory, monkeypatch):
    """An interrupted enrich run keeps every completed chunk: works whose
    fetch chunk committed stay enriched after a later chunk fails."""
    ut = await institution_factory(code="ut", data_window_start=2020)
    run = await _run(db, "pure", "works", ut)
    for i in range(5):
        _mk_work(db, ut, f"w-{i}", run, doi=f"10.0.0/{i}", title=f"w {i}")
    await db.commit()

    monkeypatch.setattr("journal_browser.harvest.enrich.FETCH_CHUNK", 2)

    calls = {"n": 0}

    async def _get(url: str):
        calls["n"] += 1
        if calls["n"] > 4:  # third chunk: every lookup fails
            raise ValueError("openalex down")
        doi = url.rsplit("/", 1)[-1]
        return SimpleNamespace(
            id=f"https://openalex.org/W-{doi}",
            open_access=SimpleNamespace(oa_status="gold"),
            primary_location=SimpleNamespace(source=SimpleNamespace(issn_l=None, issn=[])),
            locations=[],
            model_dump=lambda mode="json": {"id": f"https://openalex.org/W-{doi}"},
        )

    class _FakeClient:
        def __init__(self, **_kw):
            self.works = SimpleNamespace(get=_get)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(aletheca, "AlethecaClient", _FakeClient)

    with pytest.raises(RuntimeError, match=r"openalex down"):
        await enrich_openalex(db, ut.id)

    enriched = dict((await db.execute(select(Work.pure_uuid, Work.oa_status))).all())
    # Chunks 1 and 2 (w-0..w-3) persisted per chunk; the failed chunk lost
    # only itself. Without per-chunk commits nothing would have persisted:
    # the run never reached its final commit.
    assert enriched["w-4"] is None
    assert {k: v for k, v in enriched.items() if v} == {
        "w-0": "gold",
        "w-1": "gold",
        "w-2": "gold",
        "w-3": "gold",
    }
    confirmed = (
        (await db.execute(select(WorkIdentity.source_pk).where(WorkIdentity.status == "confirmed")))
        .scalars()
        .all()
    )
    assert len(confirmed) == 4


# ── Enrichment outcome: $0 singleton route resolves journals ──────────────

# Captured at import time, before any fixture patches the credits helper.
_REAL_CREDITS = harvest_common.openalex_credits_remaining


@requires_db
async def test_enrich_openalex_resolves_journal_via_free_singleton(
    db, institution_factory, monkeypatch
):
    """The OpenAlex rung fetches exactly one $0 singleton GET per DOI
    (never a priced filter page) and resolves works.journal_issn_l when
    the venue's issn_l matches a seeded journal. Keyless client: the
    forced-empty settings pass no api_key."""
    ut = await institution_factory(code="ut", data_window_start=2020)
    db.add(journal_factory("0044-229X"))
    run = await _run(db, "pure", "works", ut)
    _mk_work(db, ut, "w-j", run, doi="10.1234/wj", title="venue outcome", year=2022)
    await db.commit()

    fetched_urls: list[str] = []

    def _venue_work(id_or_url: str) -> SimpleNamespace:
        source = SimpleNamespace(issn_l="0044-229X", issn=["0044-229X"])
        primary = SimpleNamespace(source=source)
        return SimpleNamespace(
            id=f"https://openalex.org/W-{id_or_url}",
            open_access=SimpleNamespace(oa_status="gold"),
            primary_location=primary,
            locations=[primary],
            model_dump=lambda mode="json": {"id": f"https://openalex.org/W-{id_or_url}"},
        )

    class _FakeWorks:
        async def get(self, id_or_url: str):
            fetched_urls.append(id_or_url)
            return _venue_work(id_or_url)

    client_kwargs: dict = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            client_kwargs.update(kwargs)
            self.works = _FakeWorks()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(aletheca, "AlethecaClient", _FakeClient)
    stats = await enrich_openalex(db, ut.id)
    await db.commit()

    assert stats["matched"] == 1 and stats["journal_resolved"] == 1
    work = (
        await db.execute(select(Work).where(Work.institution_id == ut.id, Work.pure_uuid == "w-j"))
    ).scalar_one()
    assert work.journal_issn_l == "0044-229X" and work.oa_status == "gold"
    # Free-route: one path-shaped singleton GET per DOI, no query string.
    assert fetched_urls == ["https://doi.org/10.1234/wj"]
    assert client_kwargs.get("api_key", "") == ""


async def test_openalex_suite_isolation_survives_key_in_settings(monkeypatch, tmp_path):
    """The conftest isolation is not env-deep only: even with a key in the
    settings overlay the suite makes no budget HTTP (gate stays open), and
    the keyless credits helper short-circuits to None offline."""
    yaml_file = tmp_path / "settings.yaml"
    yaml_file.write_text("openalex_api_key: sk-suite-test\n")
    monkeypatch.setenv("JB_SETTINGS_YAML", str(yaml_file))

    def _no_http(self, *args, **kwargs):
        raise AssertionError("live OpenAlex HTTP inside the not-live suite")

    monkeypatch.setattr(httpx.AsyncClient, "get", _no_http)

    reset_settings_cache()
    try:
        # The overlay wins over the forced-empty env: the key IS visible,
        # and the autouse stub still keeps the gate open with no network.
        assert get_settings().openalex_api_key == "sk-suite-test"
        stats: dict = {}
        assert await harvest_common.openalex_budget_ok("gate-test", stats) is True
        assert "openalex_reserve_stop" not in stats
    finally:
        reset_settings_cache()

    # The real helper without a key short-circuits: None, zero HTTP.
    with monkeypatch.context() as m:
        m.setattr(harvest_common, "openalex_credits_remaining", _REAL_CREDITS)
        m.delenv("JB_SETTINGS_YAML")
        reset_settings_cache()
        try:
            assert get_settings().openalex_api_key == ""
            assert await harvest_common.openalex_credits_remaining() is None
        finally:
            reset_settings_cache()
