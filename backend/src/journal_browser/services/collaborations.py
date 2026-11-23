"""Collaboration partners: counts, facets and detail for /collaborations.

work_partners holds one link per work and partner ROR id. The derive job
(harvest.work_partners) rebuilds it from the stored OpenAlex and OpenAIRE
work payloads. partner_institutions holds the ROR records.

Every number here counts works, never links: a work with three partners
counts once in the totals and once under each of its partners.

Every query is assembled from three condition builders, so a new filter
or facet is one condition plus one entry in FACETS:

- _work_conditions selects the institution's works by publication year,
  the author's org unit, and the funders and projects credited on the
  work;
- _link_conditions selects links by the payload that supplied them;
- _partner_conditions selects partners by name, type and country.

Each facet leaves its own dimension open and keeps every other filter.
The totals and facets of one filter set are cached until the next harvest
bump.
"""

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from weakref import WeakKeyDictionary

from fastapi.responses import StreamingResponse
from sqlalchemy import Text, and_, case, distinct, func, literal, or_, select, union_all
from sqlalchemy import cast as sql_cast
from sqlalchemy.dialects.postgresql import JSONB, aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ..harvest.common import cache_epoch
from ..harvest.funder_aliases import bare_openalex_id
from ..harvest.funders import normalize_ror
from ..models import (
    Author,
    AuthorWork,
    FunderAlias,
    Institution,
    OpenaireWorkFacts,
    OpenalexFunder,
    PartnerInstitution,
    Work,
    WorkFunder,
    WorkPartner,
    WorkPureAuthor,
)
from ..schemas import (
    CollaborationDetailResponse,
    CollaborationFacets,
    CollaborationFunder,
    CollaborationLink,
    CollaborationMapPoint,
    CollaborationMapResponse,
    CollaborationPartner,
    CollaborationProject,
    CollaborationRelation,
    CollaborationSearchResponse,
    CollaborationWork,
    CollaborationWorksResponse,
    CollaborationYearCount,
    FacetCount,
)
from .cache import FACET_CACHE, SNAPSHOT_TTL, cache_get, cache_put
from .exports import _csv_response, _csv_safe, _safe_filename
from .works_query import (
    unit_key,
    unit_work_conditions,
    work_type_normalized,
    work_type_not_excluded,
    work_window,
)

FACET_CAP = 50
ITEM_LIST_CAP = 5
DETAIL_LIST_CAP = 25
RECENT_WORKS = 25
AUTHOR_CAP = 50
#: sessions _together uses at once, on top of the request's own session
QUERY_CONCURRENCY = 4

_Payload = Literal["openalex", "openaire"]

_PARTNER_CSV = (
    "ror",
    "name",
    "org_type",
    "country_code",
    "city",
    "works",
    "corresponding_works",
    "authorships",
    "share",
    "sources",
    "funders",
    "projects",
)
_WORK_CSV = (
    "pure_uuid",
    "title",
    "year",
    "doi",
    "work_type",
    "corresponding",
    "source",
    "authors",
)


@dataclass(frozen=True, slots=True)
class CollaborationFilters:
    """Every list, map, detail, works and export filter in one object.
    Multi-select fields are OR'ed within their dimension and AND'ed across
    dimensions; None means the dimension is not filtered.
    """

    q: str | None = None
    org_types: Sequence[str] | None = None
    countries: Sequence[str] | None = None
    level: str = "faculty"
    faculty: Sequence[str] | None = None
    funders: Sequence[str] | None = None
    projects: Sequence[str] | None = None
    sources: Sequence[str] | None = None
    year_range: tuple[int, int] | None = None


def _payload(value: Any) -> _Payload:
    """A work_partners.source or credit-key prefix as its Literal type;
    the check constraint limits the column to these two payloads."""
    return "openaire" if value == "openaire" or str(value).startswith("openaire:") else "openalex"


def _sources(values: Sequence[str] | None) -> list[_Payload]:
    return [_payload(value) for value in sorted(values or [])]


# --- condition builders ---------------------------------------------------


def _awards(institution: Institution) -> Any:
    """One row per OpenAlex funder credit on the institution's works:
    funder_key openalex:<bare id>, project_key openalex:<bare id>/<award>."""
    funder_id = bare_openalex_id(WorkFunder.funder_openalex_id)
    award = func.nullif(func.btrim(WorkFunder.award), "")
    return (
        select(
            WorkFunder.pure_uuid.label("work"),
            func.concat("openalex:", funder_id).label("funder_key"),
            func.coalesce(OpenalexFunder.display_name, WorkFunder.funder_name, funder_id).label(
                "funder_name"
            ),
            case((award.is_not(None), func.concat("openalex:", funder_id, "/", award))).label(
                "project_key"
            ),
            award.label("code"),
            sql_cast(literal(None), Text).label("acronym"),
            literal("openalex", Text).label("payload"),
        )
        .outerjoin(OpenalexFunder, OpenalexFunder.openalex_id == funder_id)
        .where(WorkFunder.institution_id == institution.id)
        .subquery()
    )


def _projects(institution: Institution) -> Any:
    """One row per OpenAIRE project credit on the institution's works.
    funder_key is openalex:<bare id> when funder_aliases resolves the
    project's funder name to an OpenAlex funder, else openaire:<funder
    name>; project_key is openaire:<project id>."""
    elements = (
        select(
            OpenaireWorkFacts.pure_uuid.label("work"),
            sql_cast(func.jsonb_array_elements(OpenaireWorkFacts.projects), JSONB).label("project"),
        )
        .where(OpenaireWorkFacts.institution_id == institution.id)
        .subquery()
    )
    project = elements.c.project

    def value(key: str) -> Any:
        return func.nullif(func.btrim(project[key].astext), "")

    funder, pid = value("funder"), value("id")
    resolved = FunderAlias.funder_openalex_id
    return (
        select(
            elements.c.work,
            case(
                (resolved.is_not(None), func.concat("openalex:", resolved)),
                (funder.is_not(None), func.concat("openaire:", funder)),
            ).label("funder_key"),
            func.coalesce(OpenalexFunder.display_name, funder).label("funder_name"),
            case((pid.is_not(None), func.concat("openaire:", pid))).label("project_key"),
            value("code").label("code"),
            value("acronym").label("acronym"),
            literal("openaire", Text).label("payload"),
        )
        .select_from(elements)
        .outerjoin(FunderAlias, FunderAlias.funder_name == funder)
        .outerjoin(OpenalexFunder, OpenalexFunder.openalex_id == resolved)
        .subquery()
    )


def _credit_sources(institution: Institution) -> list[tuple[_Payload, Any]]:
    return [("openalex", _awards(institution)), ("openaire", _projects(institution))]


def _credits(institution: Institution, dimension: str) -> Any:
    """Both payloads' credits of one dimension (funder or project) in one
    subquery: work, key, name, code, acronym, payload."""
    key = f"{dimension}_key"
    return union_all(
        *(
            select(
                source.c.work,
                source.c[key].label("key"),
                source.c.funder_name.label("name"),
                source.c.code,
                source.c.acronym,
                source.c.payload,
            )
            for _, source in _credit_sources(institution)
        )
    ).subquery()


def _credit_name(credits: Any) -> Any:
    """The funder's name as OpenAlex gives it when OpenAlex credits it,
    else the name the OpenAIRE payload gives."""
    return func.coalesce(
        func.max(case((credits.c.payload == "openalex", credits.c.name))),
        func.max(credits.c.name),
    )


def _credit_sources_list(credits: Any) -> Any:
    """The payloads that credit one key in the grouped rows."""
    return func.array_agg(distinct(credits.c.payload))


def _work_conditions(
    institution: Institution, filters: CollaborationFilters, *, drop: str | None = None
) -> list[Any]:
    """Conditions on Work: the institution's non-retired works of the
    counted types (the set the other work pages show), the work-level
    filters, minus the dimension `drop` (the facet that is being
    counted)."""
    conds: list[Any] = [
        Work.institution_id == institution.id,
        Work.retired_at.is_(None),
        work_type_not_excluded(Work.work_type),
    ]
    if drop != "years":
        if filters.year_range is None:
            conds.extend(work_window(institution))
        else:
            lo, hi = filters.year_range
            conds.extend((Work.year >= lo, Work.year <= hi))
    if drop != "orgunit" and filters.faculty:
        conds.append(
            select(AuthorWork.work_pure_uuid)
            .join(Author, Author.pure_uuid == AuthorWork.author_pure_uuid)
            .where(*unit_work_conditions(institution, filters.level, filters.faculty))
            .exists()
        )
    for dimension, column in (("funder", "funder_key"), ("project", "project_key")):
        keys = getattr(filters, f"{dimension}s")
        if drop != dimension and keys:
            conds.append(
                or_(
                    *(
                        Work.pure_uuid.in_(select(source.c.work).where(source.c[column].in_(keys)))
                        for _, source in _credit_sources(institution)
                    )
                )
            )
    return conds


def _link_conditions(filters: CollaborationFilters, *, drop: str | None = None) -> list[Any]:
    if filters.sources and drop != "source":
        return [WorkPartner.source.in_(list(filters.sources))]
    return []


def _partner_conditions(filters: CollaborationFilters, *, drop: str | None = None) -> list[Any]:
    """Conditions on PartnerInstitution. The name search is never dropped:
    it narrows the partner set for every facet."""
    conds: list[Any] = []
    needle = (filters.q or "").strip().lower()
    if needle:
        conds.append(
            or_(
                func.lower(PartnerInstitution.name).contains(needle, autoescape=True),
                PartnerInstitution.ror == needle,
            )
        )
    if filters.org_types and drop != "org_type":
        conds.append(
            func.lower(PartnerInstitution.org_type).in_([v.lower() for v in filters.org_types])
        )
    if filters.countries and drop != "country":
        conds.append(
            func.upper(PartnerInstitution.country_code).in_([v.upper() for v in filters.countries])
        )
    return conds


# --- link sets --------------------------------------------------------------


def _links(
    institution: Institution,
    filters: CollaborationFilters,
    *,
    work: str | None = None,
    link: str | None = None,
) -> Any:
    """Subquery with one row per link (work, partner, source,
    corresponding) whose work passes the work-level filters and whose
    source passes the link filter. `work` and `link` leave their dimension
    open."""
    return (
        select(
            WorkPartner.work_pure_uuid.label("work"),
            WorkPartner.partner_ror.label("ror"),
            WorkPartner.source.label("source"),
            WorkPartner.corresponding.label("corresponding"),
            WorkPartner.authorships.label("authorships"),
        )
        .join(
            Work,
            and_(
                Work.institution_id == WorkPartner.institution_id,
                Work.pure_uuid == WorkPartner.work_pure_uuid,
            ),
        )
        .where(
            *_work_conditions(institution, filters, drop=work),
            *_link_conditions(filters, drop=link),
        )
        .subquery()
    )


def _selected(
    institution: Institution,
    filters: CollaborationFilters,
    *,
    work: str | None = None,
    link: str | None = None,
    partner: str | None = None,
) -> Any:
    """_links reduced to the links whose partner also passes the partner
    filters: the links behind every number on the page."""
    links = _links(institution, filters, work=work, link=link)
    return (
        select(
            links.c.work, links.c.ror, links.c.source, links.c.corresponding, links.c.authorships
        )
        .join(PartnerInstitution, PartnerInstitution.ror == links.c.ror)
        .where(*_partner_conditions(filters, drop=partner))
        .subquery()
    )


def _per_partner(selected: Any) -> Any:
    """One row per partner in `selected` with its ROR record and its work
    counts; the caller orders and pages the returned select. work_partners
    holds one link per work and partner, so each row is one joint work."""
    return (
        select(
            selected.c.ror.label("ror"),
            func.coalesce(PartnerInstitution.name, selected.c.ror).label("name"),
            PartnerInstitution.org_type,
            PartnerInstitution.country_code,
            PartnerInstitution.city,
            PartnerInstitution.lat,
            PartnerInstitution.lng,
            PartnerInstitution.parent_ror,
            PartnerInstitution.parent_name,
            PartnerInstitution.payload.is_not(None).label("in_ror"),
            func.count().label("works"),
            func.count().filter(selected.c.corresponding).label("corresponding_works"),
            func.sum(selected.c.authorships).label("authorships"),
            func.array_agg(func.distinct(selected.c.source)).label("sources"),
        )
        .outerjoin(PartnerInstitution, PartnerInstitution.ror == selected.c.ror)
        .group_by(selected.c.ror, PartnerInstitution.ror)
    )


_SORTS = {
    "works": ("works", "name"),
    "name": ("name", "works"),
    "corresponding_works": ("corresponding_works", "works"),
}


def _ordered(stmt: Any, sort: str, direction: str | None) -> Any:
    """Order by the sort column, its tie-breakers, then the ROR id. The
    first key sorts descending unless the sort is by name; `direction`
    overrides both."""
    primary, tie = _SORTS[sort]
    descending = (primary != "name") if direction is None else direction == "desc"
    columns = stmt.selected_columns
    first = columns[primary].desc() if descending else columns[primary].asc()
    second = columns[tie].asc() if tie == "name" else columns[tie].desc()
    return stmt.order_by(first, second, columns["name"].asc(), columns["ror"])


def _joint_works(institution: Institution, filters: CollaborationFilters, ror: str) -> Any:
    """Subquery with one row per work linked to `ror` under the filters,
    with the link's payload and corresponding flag."""
    selected = _selected(institution, filters)
    return (
        select(selected.c.work.label("work"), selected.c.source, selected.c.corresponding)
        .where(selected.c.ror == ror)
        .subquery()
    )


def _author_names() -> Any:
    """Comma-joined display names of the institution's authors on a work,
    by position, from the Pure roster."""
    name = func.btrim(func.concat_ws(" ", WorkPureAuthor.first_names, WorkPureAuthor.family_names))
    return (
        select(func.string_agg(name, aggregate_order_by(literal(", "), WorkPureAuthor.position)))
        .where(
            WorkPureAuthor.institution_id == Work.institution_id,
            WorkPureAuthor.work_pure_uuid == Work.pure_uuid,
        )
        .correlate(Work)
        .scalar_subquery()
    )


def _works_stmt(institution: Institution, joint: Any) -> Any:
    """The works of a _joint_works subquery with their display fields,
    newest first."""
    return (
        select(
            joint.c.work.label("pure_uuid"),
            joint.c.source,
            joint.c.corresponding,
            Work.title,
            Work.year,
            Work.doi_normalized,
            work_type_normalized(Work.work_type).label("work_type"),
            _author_names().label("authors"),
        )
        .select_from(joint)
        .join(Work, and_(Work.institution_id == institution.id, Work.pure_uuid == joint.c.work))
        .order_by(Work.year.desc(), Work.title, joint.c.work)
    )


# --- totals and facets -------------------------------------------------------


def _facet_counts(rows: Sequence[Any], limit: int = FACET_CAP) -> list[FacetCount]:
    """FacetCount list sorted by count, then value."""
    return [
        FacetCount(value=str(v), count=int(n))
        for v, n in sorted(rows, key=lambda r: (-int(r[1]), str(r[0])))
    ][:limit]


async def _partner_attribute_counts(
    session: AsyncSession, selected: Any, column: Any
) -> list[FacetCount]:
    """Works per value of a partner attribute over the links in
    `selected`."""
    stmt = (
        select(column.label("value"), func.count(func.distinct(selected.c.work)))
        .select_from(selected)
        .join(PartnerInstitution, PartnerInstitution.ror == selected.c.ror)
        .where(column.is_not(None))
        .group_by(column)
    )
    return _facet_counts((await session.execute(stmt)).all())


async def _facet_org_type(
    session: AsyncSession, institution: Institution, filters: CollaborationFilters
) -> list[FacetCount]:
    return await _partner_attribute_counts(
        session,
        _selected(institution, filters, partner="org_type"),
        func.coalesce(func.lower(PartnerInstitution.org_type), "unknown"),
    )


async def _facet_country(
    session: AsyncSession, institution: Institution, filters: CollaborationFilters
) -> list[FacetCount]:
    return await _partner_attribute_counts(
        session,
        _selected(institution, filters, partner="country"),
        func.upper(PartnerInstitution.country_code),
    )


async def _facet_source(
    session: AsyncSession, institution: Institution, filters: CollaborationFilters
) -> list[FacetCount]:
    selected = _selected(institution, filters, link="source")
    rows = await session.execute(
        select(selected.c.source, func.count(func.distinct(selected.c.work))).group_by(
            selected.c.source
        )
    )
    return _facet_counts(rows.all())


async def _facet_orgunit(
    session: AsyncSession, institution: Institution, filters: CollaborationFilters
) -> list[FacetCount]:
    """Works per org unit (at the request's level) among the selected
    partners' works."""
    selected = _selected(institution, filters, work="orgunit")
    key = unit_key(filters.level)
    stmt = (
        select(key.label("value"), func.count(func.distinct(Work.pure_uuid)))
        .where(
            *_work_conditions(institution, filters, drop="orgunit"),
            *unit_work_conditions(institution, filters.level),
            Work.pure_uuid.in_(select(selected.c.work)),
            key.is_not(None),
            func.btrim(key) != "",
        )
        .group_by(key)
    )
    return _facet_counts((await session.execute(stmt)).all())


async def _credit_facet(
    session: AsyncSession, institution: Institution, filters: CollaborationFilters, dimension: str
) -> list[Any]:
    """Funders or projects credited on the selected partners' works. A
    funder both payloads credit is one entry with both sources and each
    work counted once; a project stays one entry per payload."""
    selected = _selected(institution, filters, work=dimension)
    works = (
        select(Work.pure_uuid.label("work"))
        .where(
            *_work_conditions(institution, filters, drop=dimension),
            Work.pure_uuid.in_(select(selected.c.work)),
        )
        .subquery()
    )
    credits = _credits(institution, dimension)
    stmt = (
        select(
            credits.c.key.label("key"),
            _credit_name(credits).label("name"),
            func.max(credits.c.code).label("code"),
            func.max(credits.c.acronym).label("acronym"),
            func.count(func.distinct(credits.c.work)).label("count"),
            _credit_sources_list(credits).label("sources"),
        )
        .where(credits.c.work.in_(select(works.c.work)), credits.c.key.is_not(None))
        .group_by(credits.c.key)
    )
    rows = (await session.execute(stmt)).all()
    ordered = sorted(rows, key=lambda r: (-int(r.count), r.name or "", r.key))[:FACET_CAP]
    if dimension == "funder":
        return [
            CollaborationFunder(
                key=r.key, name=r.name or r.key, sources=sorted(r.sources), works=int(r.count)
            )
            for r in ordered
        ]
    return [
        CollaborationProject(
            key=r.key,
            code=r.code,
            acronym=r.acronym,
            funder=r.name,
            source=r.sources[0],
            works=int(r.count),
        )
        for r in ordered
    ]


FACETS: dict[str, Callable[[AsyncSession, Institution, CollaborationFilters], Awaitable[Any]]] = {
    "org_type": _facet_org_type,
    "country": _facet_country,
    "orgunit": _facet_orgunit,
    "funder": lambda s, i, f: _credit_facet(s, i, f, "funder"),
    "project": lambda s, i, f: _credit_facet(s, i, f, "project"),
    "source": _facet_source,
}


_query_slots: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = WeakKeyDictionary()


def _slots() -> asyncio.Semaphore:
    """The sessions every request on the running loop may use through
    _together at once. One budget for all requests, so a burst of uncached
    requests queues on it instead of taking every connection of the pool."""
    loop = asyncio.get_running_loop()
    slots = _query_slots.get(loop)
    if slots is None:
        slots = _query_slots.setdefault(loop, asyncio.Semaphore(QUERY_CONCURRENCY))
    return slots


async def _together(session: AsyncSession, queries: Sequence[Any]) -> list[Any]:
    """Run query callables and return their results in order. Each query
    runs on a new session from `session`'s engine, so the queries overlap
    instead of adding up; they wait for one of the shared slots. A session
    bound to a connection (not an engine) runs them one after the other."""
    if not isinstance(session.bind, AsyncEngine):
        return [await query(session) for query in queries]
    slots = _slots()

    async def one(query: Any) -> Any:
        async with (
            slots,
            async_sessionmaker(session.bind, expire_on_commit=False)() as own,
        ):
            return await query(own)

    return list(await asyncio.gather(*(one(query) for query in queries)))


async def _summary(
    session: AsyncSession, institution: Institution, filters: CollaborationFilters
) -> dict[str, Any]:
    """Totals and facets of one filter set, cached per harvest epoch. The
    facets are always computed: the next request with the same filters
    usually asks for them."""
    key = (
        institution.id,
        filters.q,
        *(tuple(v) if v else () for v in (filters.org_types, filters.countries, filters.faculty)),
        filters.level,
        *(tuple(v) if v else () for v in (filters.funders, filters.projects, filters.sources)),
        filters.year_range,
        await cache_epoch(session),
    )
    hit = cache_get(FACET_CACHE, key, SNAPSHOT_TTL)
    if hit is not None:
        return hit
    selected = _selected(institution, filters)
    total_works, with_partner, total_partners = (
        await session.execute(
            select(
                select(func.count())
                .select_from(Work)
                .where(*_work_conditions(institution, filters))
                .scalar_subquery(),
                select(func.count(func.distinct(selected.c.work))).scalar_subquery(),
                select(func.count(func.distinct(selected.c.ror))).scalar_subquery(),
            )
        )
    ).one()
    by_source: dict[_Payload, int] = {"openalex": 0, "openaire": 0}
    for source, count in await session.execute(
        select(selected.c.source, func.count(func.distinct(selected.c.work))).group_by(
            selected.c.source
        )
    ):
        by_source[_payload(source)] = int(count)
    year_from, year_to = (
        await session.execute(
            select(func.min(Work.year), func.max(Work.year)).where(
                *_work_conditions(institution, filters)
            )
        )
    ).one()

    def facet(
        name: str, fill: Callable[[AsyncSession, Institution, CollaborationFilters], Awaitable[Any]]
    ) -> Callable[[AsyncSession], Awaitable[Any]]:
        async def run(own: AsyncSession) -> Any:
            return name, await fill(own, institution, filters)

        return run

    summary: dict[str, Any] = {
        "total_works": int(total_works),
        "works_with_partner": int(with_partner),
        "total_partners": int(total_partners),
        "works_by_source": by_source,
        "year_from": year_from,
        "year_to": year_to,
        "facets": dict(
            await _together(session, [facet(name, fill) for name, fill in FACETS.items()])
        ),
    }
    cache_put(FACET_CACHE, key, summary)
    return summary


# --- rows to response models ----------------------------------------------


@dataclass(slots=True)
class _Credits:
    """A partner's top funders and projects."""

    funders: list[CollaborationFunder]
    projects: list[CollaborationProject]


async def _credit_lists(
    session: AsyncSession,
    institution: Institution,
    selected: Any,
    rors: Sequence[str],
    cap: int,
) -> dict[str, _Credits]:
    """Top funders and projects per partner, by joint works, over the
    links in `selected` for the partners in `rors`. A funder both payloads
    credit is one entry; each work counts once."""
    out: dict[str, _Credits] = {ror: _Credits([], []) for ror in rors}
    if not rors:
        return out
    rows: dict[tuple[str, str], list[Any]] = defaultdict(list)

    def dimension_rows(dimension: str) -> Callable[[AsyncSession], Awaitable[Sequence[Any]]]:
        credits = _credits(institution, dimension)
        stmt = (
            select(
                selected.c.ror.label("ror"),
                credits.c.key.label("key"),
                _credit_name(credits).label("name"),
                func.max(credits.c.code).label("code"),
                func.max(credits.c.acronym).label("acronym"),
                func.count(func.distinct(selected.c.work)).label("count"),
                _credit_sources_list(credits).label("sources"),
            )
            .select_from(selected)
            .join(credits, credits.c.work == selected.c.work)
            .where(selected.c.ror.in_(list(rors)), credits.c.key.is_not(None))
            .group_by(selected.c.ror, credits.c.key)
        )

        async def run(own: AsyncSession) -> Sequence[Any]:
            return (await own.execute(stmt)).all()

        return run

    for dimension, found in zip(
        ("funder", "project"),
        await _together(session, [dimension_rows("funder"), dimension_rows("project")]),
        strict=True,
    ):
        for row in found:
            rows[(row.ror, dimension)].append(row)
    for (ror, dimension), entries in rows.items():
        entries.sort(key=lambda r: (-int(r.count), r.name or "", r.key))
        top = entries[:cap]
        if dimension == "funder":
            out[ror].funders = [
                CollaborationFunder(
                    key=e.key,
                    name=e.name or e.key,
                    sources=sorted(e.sources),
                    works=int(e.count),
                )
                for e in top
            ]
        else:
            out[ror].projects = [
                CollaborationProject(
                    key=e.key,
                    code=e.code,
                    acronym=e.acronym,
                    funder=e.name,
                    source=e.sources[0],
                    works=int(e.count),
                )
                for e in top
            ]
    return out


def _partner(row: Any, total_works: int, credits: _Credits) -> CollaborationPartner:
    works = int(row.works)
    return CollaborationPartner(
        ror=row.ror,
        name=row.name,
        org_type=row.org_type,
        country_code=row.country_code,
        city=row.city,
        lat=None if row.lat is None else float(row.lat),
        lng=None if row.lng is None else float(row.lng),
        parent_ror=row.parent_ror,
        parent_name=row.parent_name,
        in_ror=bool(row.in_ror),
        works=works,
        share=round(works / total_works, 4) if total_works else None,
        corresponding_works=int(row.corresponding_works),
        authorships=int(row.authorships or 0),
        sources=_sources(row.sources),
        funders=credits.funders,
        projects=credits.projects,
    )


def _work(row: Any) -> CollaborationWork:
    return CollaborationWork(
        pure_uuid=row.pure_uuid,
        title=row.title or "",
        year=int(row.year),
        doi=row.doi_normalized,
        work_type=row.work_type,
        corresponding=bool(row.corresponding),
        source=_payload(row.source),
        authors=[a for a in (row.authors or "").split(", ") if a][:AUTHOR_CAP],
    )


def _ror_details(record: PartnerInstitution | None) -> dict[str, Any]:
    """Status, OpenAlex id, labels, links and relationships from a ROR v2
    record; the display name comes first."""
    payload: dict[str, Any] = record.payload if record and isinstance(record.payload, dict) else {}
    names = sorted(
        payload.get("names") or [],
        key=lambda name: "ror_display" not in (name.get("types") or []),
    )
    labels: list[str] = []
    for name in names:
        value = str(name.get("value") or "").strip()
        if value and value not in labels:
            labels.append(value)
    links = [
        CollaborationLink(type=str(link.get("type") or ""), value=str(link.get("value") or ""))
        for link in payload.get("links") or []
        if link.get("type") and link.get("value")
    ]
    relationships = [
        CollaborationRelation(
            type=str(rel.get("type") or ""),
            ror=normalize_ror(rel.get("id")) or "",
            label=str(rel.get("label") or ""),
        )
        for rel in payload.get("relationships") or []
        if normalize_ror(rel.get("id"))
    ]
    return {
        "status": record.status if record else None,
        "openalex_id": record.openalex_id if record else None,
        "labels": labels[:12],
        "links": links[:20],
        "relationships": relationships[:20],
    }


def _file_stem(institution: Institution, *parts: str) -> str:
    return _safe_filename("-".join(p for p in (institution.code, *parts) if p))


async def _csv_lines(rows: Sequence[Sequence[Any]]) -> AsyncIterator[list[str]]:
    for row in rows:
        yield ["" if v is None else _csv_safe(str(v)) for v in row]


async def _linked(session: AsyncSession, institution: Institution, ror: str) -> bool:
    """True when the institution has any link to `ror`, filters aside."""
    return (
        await session.scalar(
            select(WorkPartner.work_pure_uuid)
            .where(
                WorkPartner.institution_id == institution.id,
                WorkPartner.partner_ror == ror,
            )
            .limit(1)
        )
    ) is not None


# --- public API ---------------------------------------------------------------


async def search_collaborations(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
    *,
    sort: str,
    direction: str | None,
    offset: int,
    limit: int,
    include_facets: bool,
) -> CollaborationSearchResponse:
    selected = _selected(institution, filters)
    # The summary's facets overlap; the page needs nothing from the summary.
    summary = await _summary(session, institution, filters)
    rows = (
        await session.execute(
            _ordered(_per_partner(selected), sort, direction).offset(offset).limit(limit)
        )
    ).all()
    credits = await _credit_lists(
        session, institution, selected, [r.ror for r in rows], ITEM_LIST_CAP
    )
    return CollaborationSearchResponse(
        items=[_partner(r, summary["total_works"], credits[r.ror]) for r in rows],
        total_partners=summary["total_partners"],
        total_works=summary["total_works"],
        works_with_partner=summary["works_with_partner"],
        works_by_source=summary["works_by_source"],
        year_from=summary["year_from"],
        year_to=summary["year_to"],
        facets=CollaborationFacets(**summary["facets"]) if include_facets else None,
    )


async def collaboration_map(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
) -> CollaborationMapResponse:
    per_partner = _per_partner(_selected(institution, filters)).subquery()
    rows = (
        await session.execute(
            select(
                per_partner.c.ror,
                per_partner.c.name,
                per_partner.c.country_code,
                per_partner.c.city,
                per_partner.c.org_type,
                per_partner.c.lat,
                per_partner.c.lng,
                per_partner.c.works,
                per_partner.c.corresponding_works,
            )
        )
    ).all()
    items = [
        CollaborationMapPoint(
            ror=r.ror,
            name=r.name,
            country_code=r.country_code,
            city=r.city,
            org_type=(r.org_type or "unknown").lower(),
            lat=float(r.lat),
            lng=float(r.lng),
            works=int(r.works),
            corresponding_works=int(r.corresponding_works),
        )
        for r in rows
        if r.lat is not None and r.lng is not None
    ]
    return CollaborationMapResponse(items=items, unmapped=len(rows) - len(items))


async def collaboration_detail(
    session: AsyncSession,
    institution: Institution,
    ror: str,
    filters: CollaborationFilters,
) -> CollaborationDetailResponse | None:
    if not await _linked(session, institution, ror):
        return None
    selected = _selected(institution, filters)
    row = (await session.execute(_per_partner(selected).where(selected.c.ror == ror))).one_or_none()
    summary = await _summary(session, institution, filters)
    total_works = summary["total_works"]
    if row is not None:
        base = _partner(
            row,
            total_works,
            (await _credit_lists(session, institution, selected, [ror], DETAIL_LIST_CAP))[ror],
        )
    else:
        # The filters leave this partner no joint work: report it with
        # zero counts from its ROR record.
        record = await session.get(PartnerInstitution, ror)
        base = CollaborationPartner(
            ror=ror,
            name=record.name if record and record.name else ror,
            org_type=record.org_type if record else None,
            country_code=record.country_code if record else None,
            city=record.city if record else None,
            lat=float(record.lat) if record and record.lat is not None else None,
            lng=float(record.lng) if record and record.lng is not None else None,
            parent_ror=record.parent_ror if record else None,
            parent_name=record.parent_name if record else None,
            in_ror=record is not None and record.payload is not None,
            works=0,
            corresponding_works=0,
            authorships=0,
            sources=[],
            funders=[],
            projects=[],
        )
    joint = _joint_works(institution, filters, ror)
    on = and_(Work.institution_id == institution.id, Work.pure_uuid == joint.c.work)
    work_type = work_type_normalized(Work.work_type).label("type")
    by_type = (
        await session.execute(
            select(work_type, func.count().label("count"))
            .select_from(joint)
            .join(Work, on)
            .group_by(work_type)
            .order_by(func.count().desc(), work_type)
        )
    ).all()
    per_year = (
        await session.execute(
            select(Work.year, func.count())
            .select_from(joint)
            .join(Work, on)
            .group_by(Work.year)
            .order_by(Work.year)
        )
    ).all()
    recent = (await session.execute(_works_stmt(institution, joint).limit(RECENT_WORKS))).all()
    record = await session.get(PartnerInstitution, ror)
    details = _ror_details(record)
    return CollaborationDetailResponse(
        **base.model_dump(),
        **details,
        total_works=total_works,
        works_by_type=[FacetCount(value=t, count=int(n)) for t, n in by_type if t is not None],
        per_year=[CollaborationYearCount(year=int(y), works=int(n)) for y, n in per_year],
        recent_works=[_work(r) for r in recent],
    )


async def partner_works(
    session: AsyncSession,
    institution: Institution,
    ror: str,
    filters: CollaborationFilters,
    *,
    offset: int,
    limit: int,
) -> CollaborationWorksResponse | None:
    if not await _linked(session, institution, ror):
        return None
    joint = _joint_works(institution, filters, ror)
    total = await session.scalar(select(func.count()).select_from(joint))
    rows = (
        await session.execute(_works_stmt(institution, joint).offset(offset).limit(limit))
    ).all()
    return CollaborationWorksResponse(items=[_work(r) for r in rows], total=int(total or 0))


async def collaborations_csv(
    session: AsyncSession,
    institution: Institution,
    filters: CollaborationFilters,
) -> StreamingResponse:
    selected = _selected(institution, filters)
    total_works = await session.scalar(
        select(func.count()).select_from(Work).where(*_work_conditions(institution, filters))
    )
    rows = (await session.execute(_ordered(_per_partner(selected), "works", None))).all()
    credits = await _credit_lists(
        session, institution, selected, [r.ror for r in rows], ITEM_LIST_CAP
    )
    table: list[list[Any]] = []
    for row in rows:
        works = int(row.works)
        table.append(
            [
                row.ror,
                row.name,
                row.org_type,
                row.country_code,
                row.city,
                works,
                row.corresponding_works,
                row.authorships,
                round(works / total_works, 4) if total_works else None,
                " ".join(sorted(row.sources or [])),
                "; ".join(f.name for f in credits[row.ror].funders),
                "; ".join(
                    p.acronym or p.code or p.funder or p.key for p in credits[row.ror].projects
                ),
            ]
        )
    return _csv_response(
        f"{_file_stem(institution, 'collaborations-partners')}.csv",
        _csv_lines(table),
        _PARTNER_CSV,
    )


async def partner_works_csv(
    session: AsyncSession,
    institution: Institution,
    ror: str,
    filters: CollaborationFilters,
) -> StreamingResponse | None:
    if not await _linked(session, institution, ror):
        return None
    joint = _joint_works(institution, filters, ror)
    rows = (await session.execute(_works_stmt(institution, joint))).all()
    table = [
        [
            r.pure_uuid,
            r.title,
            r.year,
            r.doi_normalized,
            r.work_type,
            "yes" if r.corresponding else "no",
            r.source,
            r.authors,
        ]
        for r in rows
    ]
    return _csv_response(
        f"{_file_stem(institution, 'collaborations', ror, 'works')}.csv",
        _csv_lines(table),
        _WORK_CSV,
    )
