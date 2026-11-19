"""Funder list/detail support: UT-work attribution from work_funders.

The work_funders tables may not exist yet; every read checks to_regclass
first and degrades to zeros ("harvest pending") instead of 500ing. Raw
SQL for the count paths: the gates are one shared fragment, and the
canon-link reads predate the WorkFunder ORM model."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import EXCLUDED_WORK_TYPES, get_settings
from ..models import FunderLink, Institution, OpenaireFunder, OpenaireFunderStream, OpenalexFunder


@dataclass(slots=True)
class FunderCanon:
    """Canon links for the jisc funders, resolved from funder_links.

    aliases: jisc id -> extra searchable names (OpenAlex display name,
    OpenAIRE short name); bare_ids: jisc id -> bare OpenAlex ids cited by
    works (one ROR can map to several funding-stream twins, so counts must
    union the set); openaire: jisc id -> OpenAIRE identity block."""

    aliases: dict[int, list[str]]
    bare_ids: dict[int, set[str]]
    urls: dict[int, list[str]]
    openaire: dict[int, dict[str, Any]]


async def canon_links(session: AsyncSession) -> FunderCanon:
    """One join over funder_links (migration 0050) -> all canon data.

    funder_links may not exist yet (fresh DB before 0050): degrade to
    empty so the funders endpoints still serve names and policies.
    EXTRA_ALIASES covers official names the linked rows never carry: the
    NWO row (jisc 459) stores only the Dutch name, while its English
    name ("Dutch Research Council") and acronym never appear in any
    linked source, so searching them misses the Netherlands' main
    funder."""
    extra_aliases: dict[int, list[str]] = {
        459: ["Dutch Research Council", "NWO"],
    }
    exists = bool(
        await session.scalar(text("select to_regclass('public.funder_links') is not null"))
    )
    if not exists:
        return FunderCanon(aliases={}, bare_ids={}, urls={}, openaire={})
    rows = (
        await session.execute(
            select(
                FunderLink.funder_id,
                FunderLink.source,
                FunderLink.source_id,
                FunderLink.via,
                OpenalexFunder.display_name,
                OpenaireFunder.short_name,
                OpenaireFunder.name.label("oa_name"),
                OpenaireFunder.jurisdiction,
                OpenaireFunder.website_url,
            )
            .select_from(FunderLink)
            .outerjoin(
                OpenalexFunder,
                (FunderLink.source == "openalex")
                & (OpenalexFunder.openalex_id == FunderLink.source_id),
            )
            .outerjoin(
                OpenaireFunder,
                (FunderLink.source == "openaire")
                & (OpenaireFunder.openaire_id == FunderLink.source_id),
            )
            .order_by(FunderLink.funder_id, FunderLink.via)
        )
    ).all()
    canon = FunderCanon(aliases={}, bare_ids={}, urls={}, openaire={})
    # Streams ride along keyed by openaire id; attached to the funder
    # blocks below (top funding-level-0 facets with project counts).
    stream_rows = (
        await session.execute(
            select(OpenaireFunderStream).order_by(
                OpenaireFunderStream.funder_openaire_id, OpenaireFunderStream.n_projects.desc()
            )
        )
    ).scalars()
    streams_by_id: dict[str, list[dict[str, Any]]] = {}
    for st in stream_rows:
        streams_by_id.setdefault(st.funder_openaire_id, []).append(
            {"level0_id": st.level0_id, "name": st.name, "n_projects": st.n_projects}
        )
    seen_alias: set[tuple[int, str]] = set()
    for (
        fid,
        source,
        sid,
        _via,
        display_name,
        short_name,
        oa_name,
        jurisdiction,
        website_url,
    ) in rows:
        if source == "openalex":
            canon.bare_ids.setdefault(fid, set()).add(str(sid).rsplit("/", 1)[-1])
            canon.urls.setdefault(fid, []).append(sid)
            if display_name and (fid, display_name) not in seen_alias:
                seen_alias.add((fid, display_name))
                canon.aliases.setdefault(fid, []).append(display_name)
        else:
            canon.openaire.setdefault(
                fid,
                {
                    "openaire_id": sid,
                    "name": oa_name,
                    "short_name": short_name,
                    "jurisdiction": jurisdiction,
                    "website_url": website_url,
                    "streams": streams_by_id.get(sid, []),
                },
            )
            if short_name and (fid, short_name) not in seen_alias:
                seen_alias.add((fid, short_name))
                canon.aliases.setdefault(fid, []).append(short_name)
    for fid, names in extra_aliases.items():
        for name in names:
            if name not in canon.aliases.setdefault(fid, []):
                canon.aliases[fid].append(name)
    return canon


async def _work_funders_ready(session: AsyncSession) -> bool:
    return bool(await session.scalar(text("select to_regclass('public.work_funders') is not null")))


#: SQL twin of works_query.work_type_not_excluded for the raw work_funders
#: queries: the normalized work type must not be one of the
#: never-journal-output types, or the count leaves the works population
#: every sibling count shares.
_TYPE_NORM_SQL = (
    "lower(replace(replace(coalesce(w.work_type, ''), 'info:eu-repo/semantics/', ''), '-', ''))"
)

#: Shared works gates for every funder work count: not retired,
#: journal-output types, and inside the institution's data window (an
#: explicit clamped year range replaces the bounds). Everything rides the
#: works join so unscoped and scoped callers describe one population.
_WORKS_JOIN_SQL = (
    " join works w on w.institution_id = wf.institution_id and w.pure_uuid = wf.pure_uuid"
    " and w.retired_at is null"
    " and w.year >= :wlo and w.year <= :whi"
    f" and {_TYPE_NORM_SQL} <> all(cast(:excluded_types as text[]))"
)


def _window_bounds(institution: Institution, year_range: tuple[int, int] | None) -> tuple[int, int]:
    if year_range is not None:
        return year_range
    return (
        institution.data_window_start,
        institution.data_window_end if institution.data_window_end is not None else 9999,
    )


def _gate_params(institution_id: int, wlo: int, whi: int) -> dict[str, Any]:
    return {
        "i": institution_id,
        "wlo": wlo,
        "whi": whi,
        "excluded_types": sorted(EXCLUDED_WORK_TYPES),
    }


async def ut_work_counts(
    session: AsyncSession, institution: Institution, year_range: tuple[int, int] | None = None
) -> dict[str, int]:
    """Gated UT works per bare funder id. Every count joins works with the
    shared gates (not retired, journal-output types, data window), so the
    funder numbers describe the same population as every sibling works
    count; year_range None keeps the institution's default window. Keys
    are bare OpenAlex ids (no https://openalex.org/ prefix); work_funders
    stores whatever the grants payload carried, so normalize both sides.
    The counts stay per id for the display-twin pick only — the served
    n_ut_works comes from ut_funder_work_counts, which dedupes works
    across a funder's twin-id set."""
    if not await _work_funders_ready(session):
        return {}
    rows = await session.execute(
        text(
            "select wf.funder_openalex_id, count(distinct wf.pure_uuid) as n"
            " from work_funders wf" + _WORKS_JOIN_SQL + " where wf.institution_id = :i group by 1"
        ),
        _gate_params(institution.id, *_window_bounds(institution, year_range)),
    )
    return {str(fid).rsplit("/", 1)[-1]: int(n) for fid, n in rows}


async def ut_funder_work_counts(
    session: AsyncSession,
    institution: Institution,
    bare_ids_by_funder: dict[int, set[str]],
    year_range: tuple[int, int] | None = None,
) -> dict[int, int]:
    """Distinct gated UT works per canon funder across its twin-id set:
    one work crediting two funding-stream twins of the same funder counts
    once (the per-id sum would double it — NWO's twin ids differed by 75
    works). Funders with no matching works stay out of the result;
    callers default to 0."""
    if not await _work_funders_ready(session):
        return {}
    pairs = [(fid, bare) for fid, ids in bare_ids_by_funder.items() for bare in sorted(ids)]
    if not pairs:
        return {}
    params = _gate_params(institution.id, *_window_bounds(institution, year_range))
    params["fids"] = [fid for fid, _ in pairs]
    params["bares"] = [bare for _, bare in pairs]
    rows = await session.execute(
        text(
            "select m.fid, count(distinct wf.pure_uuid) as n"
            " from work_funders wf"
            + _WORKS_JOIN_SQL
            + " join unnest(cast(:fids as int[]), cast(:bares as text[])) as m(fid, bare)"
            " on wf.funder_openalex_id = m.bare where wf.institution_id = :i group by m.fid"
        ),
        params,
    )
    return {int(fid): int(n) for fid, n in rows}


async def top_journals(
    session: AsyncSession,
    institution: Institution,
    openalex_funder_id: str | None,
    limit: int = 5,
    year_range: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    """Journals with the most gated UT works crediting this funder (the
    same works gates as ut_work_counts); an explicit year_range replaces
    the default window."""
    if not await _work_funders_ready(session) or openalex_funder_id is None:
        return []
    # Admin ignore-list (e.g. arXiv): an ignored journal is treated as
    # nonexistent everywhere else, so it must not top a funder's list.
    ignored = [i.upper() for i in get_settings().ignored_issns]
    params = {
        **_gate_params(institution.id, *_window_bounds(institution, year_range)),
        "f": openalex_funder_id,
        "l": limit,
    }
    ignored_clause = (
        " and (j.issn_l is null or upper(j.issn_l) != any(:ignored))" if ignored else ""
    )
    if ignored:
        params["ignored"] = ignored
    sql = (
        "select j.title, j.issn_l, count(distinct wf.pure_uuid) as n"
        " from work_funders wf"
        + _WORKS_JOIN_SQL
        + " join journals j on j.issn_l = w.journal_issn_l"
        " where wf.institution_id = :i and wf.funder_openalex_id = :f"
        + ignored_clause
        + " group by j.title, j.issn_l order by n desc limit :l"
    )
    rows = await session.execute(text(sql), params)
    return [{"title": r[0], "issn_l": r[1], "n_works": int(r[2])} for r in rows]
