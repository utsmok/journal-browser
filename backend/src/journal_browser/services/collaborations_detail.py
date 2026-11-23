"""Cross-surface collaboration summaries (org-unit & author pages) and
partner-detail enrichment helpers."""

from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..harvest.funders import normalize_ror
from ..models import (
    Author,
    AuthorWork,
    Institution,
    Journal,
    JournalFlags,
    PartnerInstitution,
    Work,
    WorkPartner,
)
from ..schemas import (
    CollaborationAuthorCount,
    CollaborationJournalCount,
    CollaborationMergedChild,
    CollaborationUnitCount,
    CollaborationYearCount,
    FacetCount,
    PartnerSummary,
)
from .search import _oa_type
from .works_query import (
    YEAR_BUCKETS,
    author_works_join,
    unit_author_join,
    unit_key,
    unit_work_join,
    work_type_normalized,
    work_type_not_excluded,
    work_year_window,
)

OA_OPEN_STATUSES = ("gold", "diamond", "hybrid", "green", "bronze")
STANDARD_MAX_PARTNERS = 20
DETAIL_UNIT_CAP = 15
DETAIL_AUTHOR_CAP = 20
DETAIL_JOURNAL_CAP = 15
DETAIL_TOPIC_CAP = 10
SUMMARY_PARTNER_CAP = 8


def primary_topic_expr() -> Any:
    """OpenAlex primary topic display_name from Journal.topics JSONB."""
    return Journal.topics.op("->")(0).op("->>")("display_name")


async def detail_breakdowns(
    session: AsyncSession,
    institution: Institution,
    ror: str,
    joint: Any,
    *,
    rollup: bool,
    work_conds: list[Any],
    link_conds: list[Any],
    together: Any,
) -> dict[str, Any]:
    """Run all partner-detail breakdown queries concurrently via `together`."""
    on = and_(Work.institution_id == institution.id, Work.pure_uuid == joint.c.work)
    work_type = work_type_normalized(Work.work_type).label("type")

    async def q_by_type(own: AsyncSession):
        return (
            await own.execute(
                select(work_type, func.count().label("count"))
                .select_from(joint)
                .join(Work, on)
                .group_by(work_type)
                .order_by(func.count().desc(), work_type)
            )
        ).all()

    async def q_per_year(own: AsyncSession):
        return (
            await own.execute(
                select(
                    Work.year,
                    func.count().label("works"),
                    *(
                        func.count().filter(func.lower(Work.oa_status) == st).label(f"oa_{st}")
                        for st in YEAR_BUCKETS
                    ),
                )
                .select_from(joint)
                .join(Work, on)
                .group_by(Work.year)
                .order_by(Work.year)
            )
        ).all()

    async def q_units(own: AsyncSession, level: str, cap: int):
        key = unit_key(level)
        return (
            await own.execute(
                select(key.label("name"), func.count(func.distinct(Work.pure_uuid)).label("works"))
                .select_from(joint)
                .join(Work, on)
                .join(
                    AuthorWork,
                    and_(
                        AuthorWork.institution_id == institution.id,
                        AuthorWork.work_pure_uuid == Work.pure_uuid,
                    ),
                )
                .join(
                    Author,
                    and_(
                        Author.institution_id == institution.id,
                        Author.pure_uuid == AuthorWork.author_pure_uuid,
                    ),
                )
                .where(key.is_not(None), func.btrim(key) != "")
                .group_by(key)
                .order_by(func.count(func.distinct(Work.pure_uuid)).desc(), key)
                .limit(cap)
            )
        ).all()

    async def q_authors(own: AsyncSession):
        return (
            await own.execute(
                select(
                    Author.pure_uuid,
                    Author.name,
                    Author.faculty,
                    Author.research_group,
                    func.count(func.distinct(Work.pure_uuid)).label("works"),
                )
                .select_from(joint)
                .join(Work, on)
                .join(
                    AuthorWork,
                    and_(
                        AuthorWork.institution_id == institution.id,
                        AuthorWork.work_pure_uuid == Work.pure_uuid,
                    ),
                )
                .join(
                    Author,
                    and_(
                        Author.institution_id == institution.id,
                        Author.pure_uuid == AuthorWork.author_pure_uuid,
                    ),
                )
                .group_by(Author.pure_uuid, Author.name, Author.faculty, Author.research_group)
                .order_by(func.count(func.distinct(Work.pure_uuid)).desc(), Author.name)
                .limit(DETAIL_AUTHOR_CAP)
            )
        ).all()

    async def q_journals(own: AsyncSession):
        oa_expr = _oa_type(
            func.coalesce(JournalFlags.deal_covered, False),
            func.coalesce(JournalFlags.openaire_diamond, False),
        )
        rows = (
            await own.execute(
                select(
                    Journal.issn_l,
                    Journal.title,
                    func.coalesce(JournalFlags.deal_covered, False).label("deal_covered"),
                    oa_expr.label("oa_type"),
                    Journal.latest_quartile.label("quartile"),
                    func.count(func.distinct(Work.pure_uuid)).label("works"),
                    func.count(func.distinct(Work.pure_uuid))
                    .filter(Work.oa_status == "closed")
                    .label("closed_works"),
                )
                .select_from(joint)
                .join(Work, on)
                .join(Journal, Journal.issn_l == Work.journal_issn_l)
                .outerjoin(
                    JournalFlags,
                    and_(
                        JournalFlags.institution_id == institution.id,
                        JournalFlags.issn_l == Journal.issn_l,
                    ),
                )
                .group_by(
                    Journal.issn_l,
                    JournalFlags.deal_covered,
                    JournalFlags.openaire_diamond,
                )
                .order_by(func.count(func.distinct(Work.pure_uuid)).desc(), Journal.title)
                .limit(DETAIL_JOURNAL_CAP)
            )
        ).all()
        deal_closed = int(
            (
                await own.scalar(
                    select(func.count(func.distinct(Work.pure_uuid)))
                    .select_from(joint)
                    .join(Work, on)
                    .join(
                        JournalFlags,
                        and_(
                            JournalFlags.institution_id == institution.id,
                            JournalFlags.issn_l == Work.journal_issn_l,
                            JournalFlags.deal_covered.is_(True),
                        ),
                    )
                    .where(Work.oa_status == "closed")
                )
            )
            or 0
        )
        return rows, deal_closed

    async def q_topics(own: AsyncSession):
        topic = primary_topic_expr()
        return (
            await own.execute(
                select(topic, func.count(func.distinct(Work.pure_uuid)).label("n"))
                .select_from(joint)
                .join(Work, on)
                .join(Journal, Journal.issn_l == Work.journal_issn_l)
                .where(topic.is_not(None), topic != "")
                .group_by(topic)
                .order_by(func.count(func.distinct(Work.pure_uuid)).desc(), topic)
                .limit(DETAIL_TOPIC_CAP)
            )
        ).all()

    async def q_merged_children(own: AsyncSession):
        if not rollup:
            return []
        return (
            await own.execute(
                select(
                    PartnerInstitution.ror,
                    func.coalesce(PartnerInstitution.name, PartnerInstitution.ror).label("name"),
                    PartnerInstitution.status,
                    func.count(func.distinct(WorkPartner.work_pure_uuid)).label("works"),
                )
                .join(WorkPartner, WorkPartner.partner_ror == PartnerInstitution.ror)
                .join(
                    Work,
                    and_(
                        Work.institution_id == WorkPartner.institution_id,
                        Work.pure_uuid == WorkPartner.work_pure_uuid,
                    ),
                )
                .where(PartnerInstitution.rollup_ror == ror, *work_conds, *link_conds)
                .group_by(
                    PartnerInstitution.ror, PartnerInstitution.name, PartnerInstitution.status
                )
                .order_by(func.count(func.distinct(WorkPartner.work_pure_uuid)).desc())
            )
        ).all()

    (
        by_type,
        per_year,
        faculties,
        groups,
        authors,
        journals_and_closed,
        topics,
        children,
    ) = await together(
        session,
        [
            q_by_type,
            q_per_year,
            lambda own: q_units(own, "faculty", DETAIL_UNIT_CAP),
            lambda own: q_units(own, "group", DETAIL_UNIT_CAP),
            q_authors,
            q_journals,
            q_topics,
            q_merged_children,
        ],
    )
    journal_rows, deal_closed_works = journals_and_closed
    return {
        "deal_closed_works": deal_closed_works,
        "works_by_type": [FacetCount(value=t, count=int(n)) for t, n in by_type if t is not None],
        "per_year": [
            CollaborationYearCount(
                year=int(r.year),
                works=int(r.works),
                **{f"oa_{st}": int(getattr(r, f"oa_{st}")) for st in YEAR_BUCKETS},
            )
            for r in per_year
        ],
        "ut_faculties": [
            CollaborationUnitCount(name=r.name, level="faculty", works=int(r.works))
            for r in faculties
        ],
        "ut_groups": [
            CollaborationUnitCount(name=r.name, level="group", works=int(r.works)) for r in groups
        ],
        "ut_authors": [
            CollaborationAuthorCount(
                pure_uuid=r.pure_uuid,
                name=r.name,
                faculty=r.faculty,
                research_group=r.research_group,
                works=int(r.works),
            )
            for r in authors
        ],
        "top_journals": [
            CollaborationJournalCount(
                issn_l=r.issn_l,
                title=r.title or r.issn_l,
                works=int(r.works),
                closed_works=int(r.closed_works),
                oa_type=r.oa_type,
                quartile=r.quartile,
                deal_covered=bool(r.deal_covered),
            )
            for r in journal_rows
        ],
        "top_topics": [FacetCount(value=t, count=int(n)) for t, n in topics if t],
        "merged_children": [
            CollaborationMergedChild(ror=r.ror, name=r.name, status=r.status, works=int(r.works))
            for r in children
        ],
    }


async def _top_partners_for_work_subquery(
    session: AsyncSession,
    institution: Institution,
    work_uuids_subq: Any,
    *,
    limit: int = SUMMARY_PARTNER_CAP,
) -> list[dict[str, Any]]:
    """Top rolled-up standard-size partners for a subquery of Work.pure_uuid."""
    home_ror = normalize_ror(institution.ror)
    raw_pi = aliased(PartnerInstitution)
    eff_ror = func.coalesce(raw_pi.rollup_ror, WorkPartner.partner_ror).label("ror")
    conds = [
        WorkPartner.institution_id == institution.id,
        WorkPartner.work_pure_uuid.in_(select(work_uuids_subq.c.work_uuid)),
        WorkPartner.partner_count <= STANDARD_MAX_PARTNERS,
    ]
    if home_ror:
        conds.append(func.coalesce(raw_pi.rollup_ror, WorkPartner.partner_ror) != home_ror)
    dedup = (
        select(WorkPartner.work_pure_uuid.label("work"), eff_ror)
        .outerjoin(raw_pi, raw_pi.ror == WorkPartner.partner_ror)
        .where(*conds)
        .group_by(WorkPartner.work_pure_uuid, eff_ror)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                dedup.c.ror,
                func.coalesce(PartnerInstitution.name, dedup.c.ror).label("name"),
                PartnerInstitution.org_type,
                PartnerInstitution.country_code,
                PartnerInstitution.city,
                func.count().label("works"),
                func.count().filter(Work.oa_status.in_(OA_OPEN_STATUSES)).label("oa_works"),
            )
            .select_from(dedup)
            .join(
                Work,
                and_(Work.institution_id == institution.id, Work.pure_uuid == dedup.c.work),
            )
            .outerjoin(PartnerInstitution, PartnerInstitution.ror == dedup.c.ror)
            .group_by(
                dedup.c.ror,
                PartnerInstitution.name,
                PartnerInstitution.org_type,
                PartnerInstitution.country_code,
                PartnerInstitution.city,
            )
            .order_by(func.count().desc(), func.coalesce(PartnerInstitution.name, dedup.c.ror))
            .limit(limit)
        )
    ).all()
    return [
        PartnerSummary(
            ror=r.ror,
            name=r.name,
            org_type=r.org_type,
            country_code=r.country_code,
            city=r.city,
            works=int(r.works),
            oa_share=round(int(r.oa_works) / int(r.works), 4) if int(r.works) else None,
        ).model_dump()
        for r in rows
    ]


async def top_partners_for_orgunit(
    session: AsyncSession,
    institution: Institution,
    level: str,
    name: str,
    year_range: tuple[int, int] | None = None,
    *,
    limit: int = SUMMARY_PARTNER_CAP,
) -> list[dict[str, Any]]:
    key = unit_key(level)
    membership = [
        Author.institution_id == institution.id,
        *([Author.confirmed.is_(True)] if institution.require_confirmed_affiliation else []),
        key == name,
    ]
    unit_works = (
        select(Work.pure_uuid.label("work_uuid"))
        .distinct()
        .select_from(Author)
        .join(AuthorWork, unit_author_join(institution.id))
        .join(Work, unit_work_join(institution.id))
        .where(
            *membership,
            Work.retired_at.is_(None),
            *work_year_window(institution, year_range),
            work_type_not_excluded(Work.work_type),
        )
        .subquery()
    )
    return await _top_partners_for_work_subquery(session, institution, unit_works, limit=limit)


async def top_partners_for_author(
    session: AsyncSession,
    institution: Institution,
    author_pure_uuid: str,
    year_range: tuple[int, int] | None = None,
    *,
    limit: int = SUMMARY_PARTNER_CAP,
) -> list[dict[str, Any]]:
    author_works = (
        select(Work.pure_uuid.label("work_uuid"))
        .distinct()
        .select_from(Work)
        .join(AuthorWork, author_works_join(institution.id, author_pure_uuid))
        .where(
            Work.institution_id == institution.id,
            Work.retired_at.is_(None),
            *work_year_window(institution, year_range),
            work_type_not_excluded(Work.work_type),
        )
        .subquery()
    )
    return await _top_partners_for_work_subquery(session, institution, author_works, limit=limit)
