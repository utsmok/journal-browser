"""/api/v1/journals: search + detail bundle with per-field attribution."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import (
    ApcEvidence,
    Deal,
    DealInstitution,
    DealJournal,
    Institution,
    InstitutionWorksStats,
    Journal,
    JournalApcAggregate,
    Publisher,
    ScimagojrMetric,
)
from ..schemas import (
    ApcAggregateOut,
    ApcEvidenceOut,
    Attribution,
    DealOut,
    JournalDetailResponse,
    JournalListItem,
    JournalSearchResponse,
    ScimagojrOut,
    StatsYear,
)
from ..services import search as search_service

router = APIRouter(prefix="/journals", tags=["journals"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

HOME_INST = select(Institution.id).where(Institution.is_home.is_(True)).scalar_subquery()

#: DealOut fields that map 1:1 onto Deal columns.
DEAL_FIELDS = [
    "id",
    "esac_id",
    "status",
    "start_year",
    "end_year",
    "duration_text",
    "corresponding_authors_only",
    "summary",
    "conditions_text",
    "workflow_text",
    "article_types_text",
    "cap_text",
    "cap_numbers",
    "contract_url",
    "openaccess_nl_url",
    "jct_data_url",
    "per_year_oa_counts",
    "needs_curation",
    "needs_curation_reason",
]

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
        source="openalex", caveat_codes=["openalex-oa-status", "openalex-coverage"]
    ),
    "stats": Attribution(
        source="openalex",
        caveat_codes=["window-2020", "institution-affiliation", "openalex-coverage"],
    ),
    "deals": Attribution(
        source="jct + openaccess.nl",
        url="https://journalcheckertool.org/transformative-agreements/",
        caveat_codes=["jct-coverage", "openaccess-nl-prose", "issn-mapping"],
    ),
    "apc_evidence": Attribution(
        source="openapc",
        url="https://github.com/OpenAPC/openapc-de",
        caveat_codes=["openapc-coverage", "openapc-fallback"],
    ),
    "scimagojr": Attribution(
        source="scimagojr",
        url="https://www.scimagojr.com",
        caveat_codes=["scimagojr-lag"],
    ),
}


def _to_list_item(data: dict) -> JournalListItem:
    data = dict(data)
    data["twoyr_mean_citedness"] = (
        float(data.pop("twoyr")) if data.get("twoyr") is not None else None
    )
    data.pop("rank", None)
    return JournalListItem(**data)


@router.get("", response_model=JournalSearchResponse)
async def search_journals(
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=200)] = None,
    deal: Annotated[str, Query(pattern="^(any|covered|not_covered)$")] = "any",
    oa: bool | None = None,
    doaj: bool | None = None,
    quartile: Annotated[str | None, Query(pattern="^Q[1-4]$")] = None,
    topic: Annotated[str | None, Query(max_length=100)] = None,
    scope: Annotated[str, Query(pattern="^(quality|all)$")] = "quality",
    sort: Annotated[
        str, Query(pattern="^(relevance|title|institution_works|2yr_mean_citedness)$")
    ] = "relevance",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JournalSearchResponse:
    result = await search_service.search_journals(
        session,
        q=q,
        deal=deal,
        oa=oa,
        doaj=doaj,
        quartile=quartile,
        topic=topic,
        sort=sort,
        cursor=cursor,
        limit=limit,
        scope=scope,
    )
    return JournalSearchResponse(
        items=[_to_list_item(item) for item in result["items"]],
        total=result["total"],
        next_cursor=result["next_cursor"],
        facets=result["facets"],
    )


@router.get("/{issn_l}", response_model=JournalDetailResponse)
async def journal_detail(issn_l: str, session: SessionDep) -> JournalDetailResponse:
    journal = await session.scalar(select(Journal).where(Journal.issn_l == issn_l.upper()))
    if journal is None:
        raise HTTPException(status_code=404, detail="journal not found")

    deal_rows = (
        await session.execute(
            select(Deal, Publisher.name)
            .join(DealInstitution, DealInstitution.deal_id == Deal.id)
            .join(DealJournal, DealJournal.deal_id == Deal.id)
            .outerjoin(Publisher, Publisher.id == Deal.publisher_id)
            .where(
                Deal.status == "current",
                DealJournal.issn_l == journal.issn_l,
                DealInstitution.institution_id == HOME_INST,
            )
        )
    ).all()
    deals = [d for d, _name in deal_rows]
    publisher_names = {d.id: name for d, name in deal_rows}
    stats = list(
        (
            await session.execute(
                select(InstitutionWorksStats)
                .where(
                    InstitutionWorksStats.issn_l == journal.issn_l,
                    InstitutionWorksStats.institution_id == HOME_INST,
                )
                .order_by(InstitutionWorksStats.year)
            )
        )
        .scalars()
        .all()
    )
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
    return JournalDetailResponse(
        journal=JournalListItem(
            issn_l=journal.issn_l,
            title=journal.title,
            publisher_name=journal.publisher_name,
            is_oa=journal.is_oa,
            is_in_doaj=journal.is_in_doaj,
            deal_covered=bool(deals),
            twente_works=sum(s.works_count for s in stats),
            quartile=sjr_rows[-1].best_quartile if sjr_rows else None,
            twoyr_mean_citedness=summary_stats.get("2yr_mean_citedness"),
        ),
        issns=journal.issns or [],
        alternate_titles=journal.alternate_titles or [],
        topics=journal.topics or [],
        apc_prices=journal.apc_prices or [],
        summary_stats=summary_stats or None,
        counts_by_year=journal.counts_by_year or [],
        homepage_url=journal.homepage_url,
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
        attribution=ATTRIBUTION,
    )
