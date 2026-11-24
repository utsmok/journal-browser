"""Funder list/detail support: UT-work attribution from work_funders.

The work_funders tables may not exist yet; every read checks to_regclass
first and degrades to zeros ("harvest pending") instead of 500ing. Raw
SQL for the count paths: the gates are one shared fragment, and the
canon-link reads predate the WorkFunder ORM model."""

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import EXCLUDED_WORK_TYPES, get_settings
from ..identifiers import bare_openalex_id
from ..models import (
    FunderLink,
    Institution,
    JiscFunder,
    OpenaireFunder,
    OpenaireFunderStream,
    OpenalexFunder,
)
from ..queries import cache_epoch
from .cache import SNAPSHOT_CACHE, SNAPSHOT_TTL, cache_get, cache_put
from .works_query import YEAR_BUCKETS, empty_year_buckets


@dataclass(slots=True)
class FunderCanon:
    """Canon links for the jisc funders, resolved from funder_links.

    aliases: jisc id -> extra searchable names (OpenAlex display name,
    OpenAIRE short name); bare_ids: jisc id -> bare OpenAlex ids whose
    works count for the record (one ROR can map to several programme
    twins, see programme_ids); whole_ids: jisc id -> the ones that stand
    for the funder itself, set only where programme records share its
    ROR; openaire: jisc id -> OpenAIRE identity block."""

    aliases: dict[int, list[str]]
    bare_ids: dict[int, set[str]]
    whole_ids: dict[int, set[str]]
    openaire: dict[int, dict[str, Any]]


#: A parenthesised label that closes a Jisc funder name.
_LABEL_RE = re.compile(r"\(([^()]*)\)\s*$")


def _tokens(text: str | None) -> frozenset[str]:
    """Lower-cased tokens of a name. A run that mixes letters and digits
    also yields its letter part and its digit part ("H2020" -> h2020,
    2020), so the label "Horizon 2020" meets the OpenAlex spelling
    "H2020". Tokens of one character are dropped."""
    tokens: set[str] = set()
    for run in re.findall(r"[^\W_]+", (text or "").lower()):
        tokens.add(run)
        tokens.update(re.findall(r"\d+|[^\W\d_]+", run))
    return frozenset(token for token in tokens if len(token) > 1)


def programme_ids(
    records: Mapping[int, str | None], twins: Mapping[str, str | None]
) -> tuple[dict[int, set[str]], dict[int, set[str]]]:
    """Bare OpenAlex ids that describe each Jisc record, for records that
    share one ROR, and the ones that stand for the funder as a whole.
    `records` maps jisc id -> name, `twins` maps bare OpenAlex id ->
    display name.

    Jisc keeps one record per funding programme for some funders, all
    with the same ROR ("European Research Council", "European Research
    Council (FP7)", "... (Horizon 2020)"), and OpenAlex keeps one funder
    per programme ("FP7 Ideas: European Research Council"). Linked by ROR
    alone, every record gets every twin, and the parent shows the same
    works as each of its programmes.

    A record whose name ends in a parenthesised label is a programme
    record, and a twin whose name contains a token of that label belongs
    to it. The label counts only when some twin names it.

    The records that stand for the funder as a whole are those without
    a label. Where there is none, they are the records whose label no
    twin names: Jisc keeps one record per assessment exercise for some
    funders ("Research England (UKRI)", "(REF 2021)") and they are one
    funder. A labelled record next to an unlabelled one keeps only what
    its own Funder Registry id links to when no twin names its
    programme ("European Research Council (Horizon Europe)": OpenAlex
    has no ERC funder for it).

    Whole records get every twin, so the parent stays the sum of its
    programmes. The second result is empty until some twin is claimed;
    then it holds, per whole record, the twins no programme claimed.
    That is the funder itself, the one to link to."""
    labels: dict[int, frozenset[str]] = {}
    for fid, name in records.items():
        match = _LABEL_RE.search(name or "")
        if match and (label := _tokens(match.group(1))):
            labels[fid] = label
    names: dict[str, list[int]] = {}
    for bare, twin in twins.items():
        twin_tokens = _tokens(twin)
        names[bare] = [fid for fid, label in labels.items() if label & twin_tokens]
    split_off = {fid for owners in names.values() for fid in owners}
    unlabelled = [fid for fid in records if fid not in labels]
    whole = unlabelled or [fid for fid in records if fid not in split_off]
    out: dict[int, set[str]] = {fid: set() for fid in records}
    for bare, owners in names.items():
        for fid in [*whole, *owners] or list(records):
            out[fid].add(bare)
    unclaimed = {bare for bare, owners in names.items() if not owners}
    as_whole = {fid: out[fid] & unclaimed for fid in whole} if split_off else {}
    return out, as_whole


async def canon_links(session: AsyncSession) -> FunderCanon:
    """One join over funder_links (migration 0050) -> all canon data.

    funder_links may not exist yet (fresh DB before 0050): degrade to
    empty so the funders endpoints still serve names and policies. Link
    rows written before migration 0005 carry the OpenAlex id with its
    https://openalex.org/ prefix; both sides of the join are stripped.
    EXTRA_ALIASES covers official names the linked rows never carry: the
    NWO row (jisc 459) stores only the Dutch name, while its English
    name ("Dutch Research Council") and acronym never appear in any
    linked source, so searching them misses the Netherlands' main
    funder."""
    extra_aliases: dict[int, list[str]] = {
        459: ["Dutch Research Council", "NWO"],
    }
    cache_key = ("funder_canon_links", await cache_epoch(session))
    hit = cache_get(SNAPSHOT_CACHE, cache_key, SNAPSHOT_TTL)
    if hit is not None:
        return hit
    exists = bool(
        await session.scalar(text("select to_regclass('public.funder_links') is not null"))
    )
    if not exists:
        return FunderCanon(aliases={}, bare_ids={}, whole_ids={}, openaire={})
    rows = (
        await session.execute(
            select(
                FunderLink.funder_id,
                FunderLink.source,
                FunderLink.source_id,
                FunderLink.via,
                JiscFunder.name.label("jisc_name"),
                JiscFunder.ror.label("jisc_ror"),
                OpenalexFunder.display_name,
                OpenaireFunder.short_name,
                OpenaireFunder.name.label("oa_name"),
                OpenaireFunder.jurisdiction,
                OpenaireFunder.website_url,
            )
            .select_from(FunderLink)
            .join(JiscFunder, JiscFunder.id == FunderLink.funder_id)
            .outerjoin(
                OpenalexFunder,
                (FunderLink.source == "openalex")
                & (
                    bare_openalex_id(OpenalexFunder.openalex_id)
                    == bare_openalex_id(FunderLink.source_id)
                ),
            )
            .outerjoin(
                OpenaireFunder,
                (FunderLink.source == "openaire")
                & (OpenaireFunder.openaire_id == FunderLink.source_id),
            )
            .order_by(FunderLink.funder_id, FunderLink.via)
        )
    ).all()
    canon = FunderCanon(aliases={}, bare_ids={}, whole_ids={}, openaire={})
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
    # OpenAlex twins: fundref links are exact per record; ror links wait
    # for the programme split, grouped by the ROR they came through. A
    # record without a ROR has nobody to share twins with, so its links
    # stay exact too.
    names: dict[int, str | None] = {}
    ror_twins: dict[str, dict[str, str | None]] = defaultdict(dict)
    ror_by_fid: dict[int, str] = {}
    ids: dict[int, set[str]] = defaultdict(set)
    twin_names: dict[str, str] = {}
    seen_alias: set[tuple[int, str]] = set()
    for (
        fid,
        source,
        sid,
        via,
        jisc_name,
        jisc_ror,
        display_name,
        short_name,
        oa_name,
        jurisdiction,
        website_url,
    ) in rows:
        if source == "openalex":
            bare = str(sid).rsplit("/", 1)[-1]
            names[fid] = jisc_name
            if via == "ror" and jisc_ror is not None:
                ror_by_fid[fid] = jisc_ror
                ror_twins[jisc_ror][bare] = display_name
            else:
                ids[fid].add(bare)
            if display_name:
                twin_names[bare] = display_name
            continue
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
    fids_by_ror: dict[str, set[int]] = defaultdict(set)
    for fid, ror in ror_by_fid.items():
        fids_by_ror[ror].add(fid)
    for ror, fids in fids_by_ror.items():
        split, as_whole = programme_ids({fid: names[fid] for fid in fids}, ror_twins[ror])
        for fid, bares in split.items():
            ids[fid].update(bares)
        canon.whole_ids.update(as_whole)
    for fid, bares in ids.items():
        canon.bare_ids[fid] = bares
        for bare in sorted(bares):
            name = twin_names.get(bare)
            if name and name not in canon.aliases.setdefault(fid, []):
                canon.aliases[fid].append(name)
    for fid, extra in extra_aliases.items():
        for name in extra:
            if name not in canon.aliases.setdefault(fid, []):
                canon.aliases[fid].append(name)
    cache_put(SNAPSHOT_CACHE, cache_key, canon)
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
    cache_key = ("funder_work_counts", institution.id, await cache_epoch(session), year_range)
    hit = cache_get(SNAPSHOT_CACHE, cache_key, 3600)
    if hit is not None:
        return hit
    rows = await session.execute(
        text(
            "select wf.funder_openalex_id, count(distinct wf.pure_uuid) as n"
            " from work_funders wf" + _WORKS_JOIN_SQL + " where wf.institution_id = :i group by 1"
        ),
        _gate_params(institution.id, *_window_bounds(institution, year_range)),
    )
    out = {str(fid).rsplit("/", 1)[-1]: int(n) for fid, n in rows}
    cache_put(SNAPSHOT_CACHE, cache_key, out)
    return out


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
    cache_key = (
        "funder_union_counts",
        institution.id,
        await cache_epoch(session),
        year_range,
        hash(tuple(pairs)),
    )
    hit = cache_get(SNAPSHOT_CACHE, cache_key, 3600)
    if hit is not None:
        return hit
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
    out = {int(fid): int(n) for fid, n in rows}
    cache_put(SNAPSHOT_CACHE, cache_key, out)
    return out


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


async def works_by_year(
    session: AsyncSession,
    institution: Institution,
    bare_ids: set[str],
    year_range: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    """Per-year OA status breakdown for distinct gated UT works crediting this funder."""
    if not await _work_funders_ready(session) or not bare_ids:
        return []
    params = {
        **_gate_params(institution.id, *_window_bounds(institution, year_range)),
        "bares": sorted(bare_ids),
    }
    sql = (
        "select w.year, w.oa_status, count(distinct wf.pure_uuid) as n"
        " from work_funders wf" + _WORKS_JOIN_SQL + " where wf.institution_id = :i"
        " and wf.funder_openalex_id = any(cast(:bares as text[]))"
        " group by w.year, w.oa_status"
    )
    rows = await session.execute(text(sql), params)
    by_year: dict[int, dict[str, int]] = {}
    for yr, oa_status, n in rows:
        if yr is None:
            continue
        year_int = int(yr)
        count = int(n or 0)
        bucket = by_year.setdefault(year_int, {"total": 0, **empty_year_buckets()})
        bucket["total"] += count
        if oa_status in YEAR_BUCKETS:
            bucket[oa_status] += count
    return [
        {
            "year": yr,
            "works_count": by_year[yr]["total"],
            "works_count_source": "pure_canon",
            **{f"oa_{status}": by_year[yr][status] for status in YEAR_BUCKETS},
        }
        for yr in sorted(by_year, reverse=True)
    ]
