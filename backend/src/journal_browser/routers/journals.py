"""/api/v1/journals: search + detail bundle with per-field attribution."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BeforeValidator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..deps import InstitutionDep
from ..models import (
    ApcEvidence,
    Deal,
    DealInstitution,
    DealJournal,
    InstitutionWorksStats,
    JiscFunder,
    Journal,
    JournalApcAggregate,
    JournalFlags,
    Publisher,
    ScimagojrMetric,
)
from ..schemas import (
    ApcAggregateOut,
    ApcEvidenceOut,
    Attribution,
    DealOut,
    FunderFitOut,
    GreenOaPolicy,
    GreenOaRoute,
    InstitutionMetrics,
    JournalDetailResponse,
    JournalListItem,
    JournalSearchResponse,
    OpenaireInfo,
    OpenalexInfo,
    OpenalexOnly,
    ScimagojrOut,
    SimilarJournalItem,
    SimilarJournalsBundle,
    StatsYear,
    UTAuthorship,
    WorksPage,
)
from ..services import authorship, detail_enrichment, exports, repo_links
from ..services import search as search_service
from ..services.deal_coverage import deal_institution_join, dj_scope
from ..services.funder_fit import JournalFacts, compute_funder_fit
from ..services.works_query import clamped_year_range
from ..vocab import GreenOa, OaType
from .deals import DEAL_FIELDS

router = APIRouter(prefix="/journals", tags=["journals"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _split_csv(v: str | list | None) -> list[str] | None:
    # FastAPI hands list-typed params the assembled list of query values;
    # the frontend sends one comma-joined key, repeated keys also work.
    if v is None:
        return None
    if isinstance(v, list):
        v = ",".join(v)
    parts = [s for s in v.split(",") if s]
    return parts or None


#: Comma-separated oa_type multi-select, validated against OaType (422).
OaTypeFilter = Annotated[list[OaType] | None, BeforeValidator(_split_csv), Query(max_length=60)]


def _is_ignored(issn_l: str) -> bool:
    """Admin ignore-list: an ignored journal is treated as nonexistent."""
    return issn_l.upper() in set(get_settings().ignored_issns)


async def _funder_policy(session: AsyncSession, funder_id: int | None) -> dict | None:
    """Selected funder's verbatim publications_policy; 404 on a bad id,
    None when no funder is selected."""
    if funder_id is None:
        return None
    row = await session.get(JiscFunder, funder_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"funder {funder_id} not found")
    return row.publications_policy


#: Per-field source attribution (structural; caveat codes resolve against
#: the limitations registry served at /api/v1/meta/limitations).
ATTRIBUTION = {
    "title": Attribution(source="openalex", url="https://openalex.org"),
    "publisher": Attribution(source="openalex"),
    "metrics": Attribution(
        source="openalex",
        url="https://help.openalex.org/hc/en-us/articles/26611033839895",
        caveat_codes=["openalex-metrics"],
    ),
    "oa_status": Attribution(
        source="doaj (canon) + openalex",
        url="https://doaj.org",
        caveat_codes=["doaj-canon", "openalex-oa-status", "openalex-coverage"],
    ),
    "stats": Attribution(
        source="pure (primary) + openalex (cross-check)",
        # per-institution research portal; substituted at response time
        url="",
        caveat_codes=["stats-window", "pure-canon-primary", "institution-affiliation"],
    ),
    "deals": Attribution(
        source="owner-curated register (openaccess.nl + JCT)",
        url="https://journalcheckertool.org/transformative-agreements/",
        caveat_codes=["jct-coverage", "openaccess-nl-prose", "issn-mapping"],
    ),
    "apc_evidence": Attribution(
        source="openapc (observed) + doaj (declared)",
        url="https://github.com/OpenAPC/openapc-de",
        caveat_codes=["openapc-coverage", "openapc-fallback", "doaj-apc-declared"],
    ),
    "openalex": Attribution(source="openalex", url="https://openalex.org"),
    "openaire": Attribution(source="openaire", url="https://openaire.eu"),
    "works": Attribution(
        # per-institution label; substituted at response time
        source="",
        url="https://openalex.org",
    ),
    "scimagojr": Attribution(
        source="scimagojr",
        url="https://www.scimagojr.com",
        caveat_codes=["scimagojr-lag"],
    ),
    "green_oa": Attribution(
        source="Jisc Open Policy Finder",
        url="https://openpolicyfinder.jisc.ac.uk",
        caveat_codes=["jisc-policy-currency", "jisc-cc-by-nc-nd"],
    ),
}


def _to_list_item(data: dict) -> JournalListItem:
    # Service output is already converted (twoyr renamed, rank popped);
    # only raw rows (detail endpoint) need the rename here.
    data = dict(data)
    if "twoyr" in data:
        data["twoyr_mean_citedness"] = (
            float(data.pop("twoyr")) if data.get("twoyr") is not None else None
        )
        data.pop("rank", None)
    return JournalListItem(**data)


@router.get("", response_model=JournalSearchResponse)
async def search_journals(
    session: SessionDep,
    institution: InstitutionDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    search_in: Annotated[str, Query(pattern="^(all|title|publisher|topic)$")] = "all",
    deal: Annotated[str, Query(pattern="^(any|covered|not_covered)$")] = "any",
    oa: bool | None = None,
    doaj: bool | None = None,
    quartile: Annotated[str | None, Query(pattern="^Q[1-4]$")] = None,
    topic: Annotated[str | None, Query(max_length=100)] = None,
    publisher: Annotated[str | None, Query(max_length=200)] = None,
    has_apc: bool | None = None,
    has_works: bool | None = None,
    oa_type: OaTypeFilter = None,
    green_oa: GreenOa | None = None,
    pub_type: Annotated[str | None, Query(max_length=40)] = None,
    language: Annotated[
        str | None,
        Query(
            max_length=60,
            description="Comma-separated ISO 639-1 codes; unknown values match nothing",
        ),
    ] = None,
    sort: Annotated[
        str,
        Query(
            pattern="^(relevance|title|publisher|institution_works|quartile|topic|apc|2yr_mean_citedness)$"
        ),
    ] = "relevance",
    dir: Annotated[str | None, Query(pattern="^(asc|desc)$")] = None,
    cursor: Annotated[str | None, Query(max_length=512, pattern=r"^[A-Za-z0-9_-]*={0,2}$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    include_facets: bool = True,
    funder: Annotated[int | None, Query(description="Jisc OPF funder id")] = None,
    funder_fit: Annotated[
        str | None, Query(pattern="^(compliant|check|no)$", description="Funder-fit tier filter")
    ] = None,
    year_from: Annotated[
        int | None,
        Query(
            ge=1900,
            le=2100,
            description="Publication-year range start (clamped to the "
            "institution's data window; default: the full window)",
        ),
    ] = None,
    year_to: Annotated[
        int | None,
        Query(
            ge=1900,
            le=2100,
            description="Publication-year range end (clamped to the "
            "institution's data window; default: the full window)",
        ),
    ] = None,
) -> JournalSearchResponse:
    # oa_type is a comma-separated multi-select, OR'd together server-side;
    # values validate against OaType at the boundary (422).
    funder_policy = await _funder_policy(session, funder)
    year_range = clamped_year_range(institution, year_from, year_to)
    result = await search_service.search_journals(
        session,
        institution_id=institution.id,
        q=q,
        search_in=search_in,
        deal=deal,
        oa=oa,
        doaj=doaj,
        quartile=quartile,
        topic=topic,
        publisher=publisher,
        has_apc=has_apc,
        has_works=has_works,
        oa_types=list(oa_type) if oa_type else None,
        green_oa=green_oa,
        pub_type=pub_type,
        languages=_split_csv(language),
        sort=sort,
        dir=dir,
        cursor=cursor,
        limit=limit,
        include_facets=include_facets,
        funder_struct=funder_policy,
        funder_fit=funder_fit if funder_policy is not None else None,
        year_from=year_range[0] if year_range else None,
        year_to=year_range[1] if year_range else None,
    )
    return JournalSearchResponse(
        items=[_to_list_item(item) for item in result["items"]],
        total=result["total"],
        next_cursor=result["next_cursor"],
        fuzzy=result["fuzzy"],
        facets=result["facets"],
    )


@router.get("/semantic-search", response_model=JournalSearchResponse)
async def semantic_search_journals(
    session: SessionDep,
    institution: InstitutionDep,
    q: Annotated[str, Query(min_length=2, max_length=512)],
    limit: Annotated[int, Query(ge=1, le=100)] = 40,
    cursor: Annotated[str | None, Query(max_length=512, pattern=r"^[A-Za-z0-9_-]*={0,2}$")] = None,
) -> JournalSearchResponse:
    """Free-text "journals like this description" search over embeddings."""
    result = await search_service.semantic_search(session, q, institution.id, limit, cursor)
    return JournalSearchResponse(
        items=[_to_list_item(item) for item in result["items"]],
        total=result["total"],
        next_cursor=result["next_cursor"],
    )


@router.get("/{issn_l}/similar", response_model=SimilarJournalsBundle)
async def similar_journals(
    issn_l: str, session: SessionDep, institution: InstitutionDep
) -> SimilarJournalsBundle:
    if _is_ignored(issn_l):
        raise HTTPException(status_code=404, detail="journal not found")
    similar = await search_service.similar_journals(session, issn_l, institution.id)
    if similar is None:
        raise HTTPException(status_code=404, detail="journal not found")
    return SimilarJournalsBundle(
        **{key: [SimilarJournalItem(**item) for item in items] for key, items in similar.items()}
    )


@router.get("/{issn_l}/works", response_model=WorksPage)
async def journal_works(
    issn_l: str,
    session: SessionDep,
    institution: InstitutionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
    year_from: Annotated[
        int | None,
        Query(
            ge=1900,
            le=2100,
            description="Publication-year range start (clamped to the "
            "institution's data window; default: the full window)",
        ),
    ] = None,
    year_to: Annotated[
        int | None,
        Query(
            ge=1900,
            le=2100,
            description="Publication-year range end (clamped to the "
            "institution's data window; default: the full window)",
        ),
    ] = None,
) -> WorksPage:
    known = await session.scalar(select(Journal.issn_l).where(Journal.issn_l == issn_l.upper()))
    if known is None or _is_ignored(known):
        raise HTTPException(status_code=404, detail="journal not found")
    return WorksPage(
        **await detail_enrichment.list_works(
            session,
            known,
            institution,
            page,
            page_size,
            year_range=clamped_year_range(institution, year_from, year_to),
        )
    )


@router.get("/{issn_l}/openalex-only.csv")
async def journal_openalex_only_csv(
    issn_l: str,
    session: SessionDep,
    institution: InstitutionDep,
    year_from: Annotated[
        int | None,
        Query(
            ge=1900,
            le=2100,
            description="Publication-year range start (clamped to the "
            "institution's data window; default: the full window)",
        ),
    ] = None,
    year_to: Annotated[
        int | None,
        Query(
            ge=1900,
            le=2100,
            description="Publication-year range end (clamped to the "
            "institution's data window; default: the full window)",
        ),
    ] = None,
) -> StreamingResponse:
    """Uncapped CSV of the journal's CRIS-gap (OpenAlex-only) list."""
    return await exports.journal_openalex_only_csv(
        session,
        institution,
        issn_l,
        year_range=clamped_year_range(institution, year_from, year_to),
    )


@router.get("/{issn_l}", response_model=JournalDetailResponse)
async def journal_detail(
    issn_l: str,
    session: SessionDep,
    institution: InstitutionDep,
    funder: Annotated[int | None, Query(description="Jisc OPF funder id")] = None,
    year_from: Annotated[
        int | None,
        Query(
            ge=1900,
            le=2100,
            description="Publication-year range start (clamped to the "
            "institution's data window; default: the full window)",
        ),
    ] = None,
    year_to: Annotated[
        int | None,
        Query(
            ge=1900,
            le=2100,
            description="Publication-year range end (clamped to the "
            "institution's data window; default: the full window)",
        ),
    ] = None,
) -> JournalDetailResponse:
    journal = await session.scalar(select(Journal).where(Journal.issn_l == issn_l.upper()))
    if journal is None or _is_ignored(journal.issn_l):
        raise HTTPException(status_code=404, detail="journal not found")
    # Works-derived detail sections (UT authorship, OpenAIRE matches, the
    # canonical institution metrics, the CRIS gap) narrow to the range; the
    # venue registry aggregates (OpenAlex venue metrics, SJR, deals, APC
    # evidence) stay window/attribute-based.
    year_range = clamped_year_range(institution, year_from, year_to)

    # Publisher registry links (Open Access NL deals profile), keyed by the
    # same canonical grouping the publisher directory uses.
    canonical_pub = journal.publisher_canonical or journal.publisher_name
    oa_nl_slug = (
        await session.scalar(
            select(Publisher.openaccess_nl_slug).where(Publisher.name == canonical_pub)
        )
        if canonical_pub
        else None
    )

    # Effective coverage: a shared deal_journals row applies unless the
    # institution's relation opts into a scoped override list.
    deal_rows = (
        await session.execute(
            select(Deal, Publisher.name)
            .select_from(Deal)
            # Relation first: the DealJournal ON clause reads
            # journal_override from it.
            .join(DealInstitution, deal_institution_join(institution.id))
            .join(
                DealJournal,
                (DealJournal.deal_id == Deal.id)
                & dj_scope(institution.id)
                & DealJournal.excluded.is_not(True)
                & (DealJournal.issn_l == journal.issn_l),
            )
            .outerjoin(Publisher, Publisher.id == Deal.publisher_id)
            .where(Deal.status == "current")
        )
    ).all()
    deals = [d for d, _name in deal_rows]
    publisher_names = {d.id: name for d, name in deal_rows}
    # Reads the denormalized flag (harvest.denorm) shared with the search list.
    deal_cap_reached = (
        await session.execute(
            select(JournalFlags.deal_cap_reached).where(
                JournalFlags.institution_id == institution.id,
                JournalFlags.issn_l == journal.issn_l,
            )
        )
    ).scalar() or False
    # Phase 10: pure_canon is the primary works count; the OpenAlex
    # institution-filter rows keep the OA split and stay visible as the
    # labeled cross-check (decision 13-style honesty about sources).
    stats_rows = list(
        (
            await session.execute(
                select(InstitutionWorksStats)
                .where(
                    InstitutionWorksStats.issn_l == journal.issn_l,
                    InstitutionWorksStats.institution_id == institution.id,
                    # Institution data window (denorm.py convention).
                    InstitutionWorksStats.year >= institution.data_window_start,
                    InstitutionWorksStats.year
                    <= (
                        institution.data_window_end
                        if institution.data_window_end is not None
                        else 9999
                    ),
                )
                .order_by(InstitutionWorksStats.year)
            )
        )
        .scalars()
        .all()
    )
    by_source = {
        source: {s.year: s for s in stats_rows if s.source == source}
        for source in ("pure_canon", "openalex_institution_filter")
    }
    stats_totals = {
        source: sum(s.works_count for s in years.values()) for source, years in by_source.items()
    }
    stats: list[InstitutionWorksStats] = []
    works_source_by_year: dict[int, str] = {}
    for year in sorted({s.year for s in stats_rows}):
        oa_row = by_source["openalex_institution_filter"].get(year)
        primary = by_source["pure_canon"].get(year)
        # Works count: Pure-canonical when present. OA split: always the
        # OpenAlex rows (pure_canon carries none by design).
        if oa_row is not None:
            row = oa_row
            if primary is not None:
                # In-memory only; never persisted (no commit of these rows).
                row.works_count = primary.works_count
                works_source_by_year[year] = "pure_canon"
        elif primary is not None:
            row = primary
            works_source_by_year[year] = "pure_canon"
        else:
            row = None
        if row is not None:
            stats.append(row)
    sjr_rows = list(
        (
            await session.execute(
                select(ScimagojrMetric)
                .where(ScimagojrMetric.issn_l == journal.issn_l)
                .order_by(ScimagojrMetric.year)
            )
        )
        .scalars()
        .all()
    )
    aggregates = list(
        (
            await session.execute(
                select(JournalApcAggregate)
                .where(JournalApcAggregate.issn_l == journal.issn_l)
                .order_by(JournalApcAggregate.period.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    evidence = list(
        (
            await session.execute(
                select(ApcEvidence)
                .where(ApcEvidence.issn_l == journal.issn_l)
                .order_by(ApcEvidence.period.desc())
                .limit(25)
            )
        )
        .scalars()
        .all()
    )

    summary_stats = journal.summary_stats or {}
    openalex_info = await detail_enrichment.openalex_info(session, journal.issn_l)
    # Jisc Open Policy Finder green-OA bundle; null when never swept
    # (jisc_policy NULL, DOAJ tri-state convention).
    policy = journal.jisc_policy
    routes = {
        version: GreenOaRoute(**route)
        for version, route in ((policy.get("routes") or {}) if policy else {}).items()
    }
    green_oa = (
        GreenOaPolicy(
            in_opf=journal.jisc_in_opf is True,
            oa_prohibited=policy.get("open_access_prohibited"),
            routes=routes,
            internal_moniker=policy.get("internal_moniker"),
            urls=policy.get("urls") or [],
            repository_links=await repo_links.repository_links(
                session, {name for route in routes.values() for name in route.repositories}
            ),
            policy_uri=policy.get("policy_uri"),
            harvested_at=journal.jisc_harvested_at,
        )
        if policy is not None
        else None
    )
    # The oa_type feeds both the list item and the optional funder fit.
    oa_type_val = search_service.oa_type_value(
        journal.is_in_doaj,
        journal.is_oa,
        bool(aggregates)
        or journal.latest_apc_euro is not None
        or bool(journal.apc_prices)
        or journal.doaj_has_apc is True,
        bool(deals),
        journal.oa_status_observed,
        doaj_in_doaj=journal.doaj_in_doaj,
        doaj_has_apc=journal.doaj_has_apc,
    )
    funder_policy = await _funder_policy(session, funder)
    funder_fit = None
    if funder_policy is not None:
        fit = compute_funder_fit(
            funder_policy,
            JournalFacts(
                oa_type=oa_type_val.value if hasattr(oa_type_val, "value") else oa_type_val,
                prohibited=journal.jisc_oa_prohibited,
                sa_submitted=journal.jisc_allows_sa_submitted,
                sa_accepted=journal.jisc_allows_sa_accepted,
                sa_published=journal.jisc_allows_sa_published,
                deal_covered=bool(deals),
                publisher_name=journal.publisher_name,
            ),
        )
        funder_fit = FunderFitOut(status=fit.status, reasons=fit.reasons)
    return JournalDetailResponse(
        journal=JournalListItem(
            issn_l=journal.issn_l,
            title=journal.title,
            publisher_name=journal.publisher_name,
            publisher_canonical=journal.publisher_canonical,
            is_oa=journal.is_oa,
            is_in_doaj=journal.is_in_doaj,
            in_scimago=journal.in_scimago,
            last_active_year=journal.last_active_year,
            deal_covered=bool(deals),
            deal_cap_reached=deal_cap_reached,
            works=sum(s.works_count for s in stats),
            quartile=sjr_rows[-1].best_quartile if sjr_rows else None,
            twoyr_mean_citedness=summary_stats.get("two_yr_mean_citedness"),
            oa_type=oa_type_val,
        ),
        stats_totals=stats_totals,
        issns=journal.issns or [],
        alternate_titles=journal.alternate_titles or [],
        topics=journal.topics or [],
        apc_prices=journal.apc_prices or [],
        summary_stats=summary_stats or None,
        counts_by_year=journal.counts_by_year or [],
        # DOAJ is the canon homepage source; OpenAlex fills the gap.
        homepage_url=journal.doaj_homepage_url or journal.homepage_url,
        doaj_homepage_url=journal.doaj_homepage_url,
        openaccess_nl_slug=oa_nl_slug,
        type=journal.type,
        harvested_at=journal.harvested_at,
        deals=[
            DealOut(
                **{c: getattr(d, c) for c in DEAL_FIELDS if hasattr(d, c)},
                publisher_name=publisher_names.get(d.id),
            )
            for d in deals
        ],
        stats=[
            StatsYear(
                year=s.year,
                works_count=s.works_count,
                works_count_source=works_source_by_year.get(s.year, "openalex_institution_filter"),
                oa_gold=s.oa_gold,
                oa_hybrid=s.oa_hybrid,
                oa_green=s.oa_green,
                oa_bronze=s.oa_bronze,
                oa_diamond=s.oa_diamond,
                oa_closed=s.oa_closed,
            )
            for s in stats
        ],
        scimagojr=[
            ScimagojrOut(year=r.year, sjr=r.sjr, best_quartile=r.best_quartile, h_index=r.h_index)
            for r in sjr_rows
        ],
        apc_aggregates=[
            ApcAggregateOut(
                period=a.period,
                article_count=a.article_count,
                euro_min=a.euro_min,
                euro_max=a.euro_max,
                euro_mean=a.euro_mean,
            )
            for a in aggregates
        ],
        apc_evidence=[ApcEvidenceOut.model_validate(e) for e in evidence],
        openalex=OpenalexInfo(**openalex_info) if openalex_info else None,
        openaire=OpenaireInfo(
            matched_works=await detail_enrichment.openaire_matched(
                session, journal.issn_l, institution.id, year_range
            )
        ),
        green_oa=green_oa,
        funder_fit=funder_fit,
        institution_metrics=InstitutionMetrics(
            **await detail_enrichment.institution_metrics(
                session, journal.issn_l, institution, year_range
            )
        ),
        ut_authorship=UTAuthorship(
            **await authorship.venue_authorship(
                session, institution, issn_l=journal.issn_l, year_range=year_range
            )
        ),
        openalex_only=OpenalexOnly(
            **await authorship.venue_openalex_only(
                session, institution, issn_l=journal.issn_l, year_range=year_range
            )
        ),
        attribution={
            **ATTRIBUTION,
            "stats": ATTRIBUTION["stats"].model_copy(
                update={"url": get_settings().research_portal_url}
            ),
            "works": ATTRIBUTION["works"].model_copy(
                update={
                    "source": (f"openalex works of {get_settings().institution_name} publications")
                }
            ),
        },
    )
