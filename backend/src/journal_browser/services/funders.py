"""Funder list/detail support: UT-work attribution from work_funders.

The work_funders table (migration 0049) may not exist yet; every read
checks to_regclass first and degrades to zeros ("harvest pending") instead
of 500ing. Raw SQL on purpose: no ORM model until the migration lands."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import FunderLink, OpenaireFunder, OpenaireFunderStream, OpenalexFunder


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
    empty so the funders endpoints still serve names and policies."""
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
    return canon


async def _work_funders_ready(session: AsyncSession) -> bool:
    return bool(await session.scalar(text("select to_regclass('public.work_funders') is not null")))


async def ut_work_counts(
    session: AsyncSession, institution_id: int, year_range: tuple[int, int] | None = None
) -> dict[str, int]:
    """UT works per funder_openalex_id for this institution. Keys are bare
    OpenAlex ids (no https://openalex.org/ prefix); work_funders stores
    whatever the grants payload carried, so normalize both sides. An
    explicit year_range joins works and keeps only works published inside
    the clamped window; None stays today's unscoped count."""
    if not await _work_funders_ready(session):
        return {}
    if year_range is None:
        rows = await session.execute(
            text(
                "select funder_openalex_id, count(distinct pure_uuid) as n"
                " from work_funders where institution_id = :i group by 1"
            ),
            {"i": institution_id},
        )
    else:
        lo, hi = year_range
        rows = await session.execute(
            text(
                "select wf.funder_openalex_id, count(distinct wf.pure_uuid) as n"
                " from work_funders wf"
                " join works w on w.institution_id = wf.institution_id"
                "  and w.pure_uuid = wf.pure_uuid"
                " where wf.institution_id = :i and w.year >= :lo and w.year <= :hi"
                " group by 1"
            ),
            {"i": institution_id, "lo": lo, "hi": hi},
        )
    counts: dict[str, int] = {}
    for funder_id, n in rows:
        bare = str(funder_id).rsplit("/", 1)[-1]
        counts[bare] = counts.get(bare, 0) + int(n)
    return counts


async def top_journals(
    session: AsyncSession,
    institution_id: int,
    openalex_funder_id: str | None,
    limit: int = 5,
    year_range: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    """Journals with the most works crediting this funder; an explicit
    year_range keeps only works published inside the clamped window."""
    if not await _work_funders_ready(session) or openalex_funder_id is None:
        return []
    sql = (
        "select j.title, j.issn_l, count(distinct wf.pure_uuid) as n"
        " from work_funders wf"
        " join works w on w.institution_id = wf.institution_id and w.pure_uuid = wf.pure_uuid"
        " join journals j on j.issn_l = w.journal_issn_l"
        " where wf.institution_id = :i and wf.funder_openalex_id = :f"
    )
    params: dict[str, Any] = {"i": institution_id, "f": openalex_funder_id, "l": limit}
    if year_range is not None:
        sql += " and w.year >= :lo and w.year <= :hi"
        params["lo"], params["hi"] = year_range
    sql += " group by j.title, j.issn_l order by n desc limit :l"
    rows = await session.execute(text(sql), params)
    return [{"title": r[0], "issn_l": r[1], "n_works": int(r[2])} for r in rows]
