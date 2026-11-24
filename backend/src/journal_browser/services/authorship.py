"""UT authorship aggregates and CRIS-gap (OpenAlex-only) queries shared
by the journal, publisher, org-unit, and author detail views.

Two views over the same two stores:

- UT authorship: who at this institution authors a venue's canonical
  works. The population is the works-table set the search card counts
  (windowed, retired dropped, never-journal-output types excluded),
  joined through work_pure_authors → authors for faculty and research
  group attribution — the reverse view of the author and org-unit pages.
- OpenAlex-only ("not registered in Pure"): openalex_works store rows
  attributed to the venue (issn) or to the unit's member authors whose
  DOI matches no Pure work, gated like the author page's openalex-only
  merge: publication-year window, never-journal-output types dropped,
  NULL types kept (the store's vocabulary is sparser than Pure's).

Store-backed queries return available=False when the local
openalex_works projection has never run for the institution (the same
degradation the author page applies); the frontend hides the card
instead of showing a misleading zero.
"""

import warnings
from collections.abc import Iterable
from typing import Any, Literal

from sqlalchemy import (
    and_,
    bindparam,
    cast,
    column,
    exists,
    false,
    func,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy import exc as sa_exc
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Text

from ..config import AUTHOR_SWEEP_PREFIX
from ..identifiers import norm_title, normalize_doi
from ..models import (
    Author,
    Institution,
    Journal,
    OpenalexWork,
    OpenalexWorkAuthor,
    Work,
    WorkPureAuthor,
)
from ..queries import work_type_not_excluded
from .works_query import work_year_window, year_end

TOP_AUTHORS = 10
#: Entries served per OpenalexOnly payload (after grouping); total and
#: entries_total stay exact beyond the cap.
GAP_ITEM_CAP = 50
#: Canonical OpenAlex work url prefix (openalex.org/W...).
OPENALEX_URL = "https://openalex.org"


#: SQL predicate per parts filter value (the shared contract's part_kind):
#: standalone rows have no parents; chapter rows name a volume parent
#: (the book); other link types (component, data-series, part) stay
#: "part". Values validate at the API boundary (422 on unknown).
PART_KIND_PREDICATES: dict[str, Any] = {
    "standalone": OpenalexWork.is_part.is_(False),
    "chapter": and_(
        OpenalexWork.is_part.is_(True),
        OpenalexWork.parent_works.contains([{"rel": "volume"}]),
    ),
    "part": and_(
        OpenalexWork.is_part.is_(True),
        ~OpenalexWork.parent_works.contains([{"rel": "volume"}]),
    ),
}

#: Books listed per chapter_rollup; sample chapter titles per book.
CHAPTER_ROLLUP_BOOKS = 10
CHAPTER_ROLLUP_SAMPLE = 3


def parts_predicate(parts: list[str] | None) -> Any | None:
    """OR'd predicate for the pipe-joined parts filter; None = no filter.
    Unknown kinds KeyError: the boundary validates, services must not
    silently narrow."""
    if not parts:
        return None
    return or_(*(PART_KIND_PREDICATES[kind] for kind in sorted(set(parts))))


def primary_parent(parents: list[Any] | None) -> dict[str, Any] | None:
    """A part's primary parent: the first rel=volume parent (the book a
    chapter belongs to), else the first listed parent; None = standalone
    (no parents). Parts join exactly one group — their primary parent's —
    so multi-parent parts never split a main work's missing set."""
    rows = [p for p in parents or [] if isinstance(p, dict)]
    for p in rows:
        if p.get("rel") == "volume":
            return p
    return rows[0] if rows else None


async def local_store_ready(session: AsyncSession, institution: Institution) -> bool:
    """True when the openalex_works projection has run for this
    institution at least once (store-backed cards may answer)."""
    return (
        await session.scalar(
            select(1).where(OpenalexWork.institution_id == institution.id).limit(1)
        )
    ) is not None


def _unavailable() -> dict[str, Any]:
    return {"total": 0, "entries_total": 0, "items": [], "available": False, "parts_counts": {}}


def not_repository() -> Any:
    """True unless the store row's OpenAlex primary location is a
    repository source. A repository copy (Zenodo, TNO repository) is not
    evidence a work is missing from Pure — and the institution's own
    research information system is repository-typed in OpenAlex, so
    without this gate the gap cards list works Pure already holds. NULL
    stays (OpenAlex's source vocabulary is sparser than the raw feed)."""
    return func.coalesce(OpenalexWork.source_type, "") != "repository"


def store_gates(institution: Institution, year_range: tuple[int, int] | None = None) -> list[Any]:
    """Window + type + source gates for store rows, mirroring the author
    page's openalex-only merge: NULL years drop (outside any window), NULL
    types and source kinds stay (OpenAlex's vocabulary is sparser than
    Pure's). An explicit clamped year range replaces the window bounds."""
    start, end = (
        year_range if year_range else (institution.data_window_start, year_end(institution))
    )
    return [
        OpenalexWork.year.between(start, end),
        func.coalesce(work_type_not_excluded(OpenalexWork.work_type), True),
        not_repository(),
    ]


def not_in_pure() -> Any:
    """Anti-join: no Pure work holds this DOI. DOI-less store rows cannot
    match and therefore count — same rule the author page applies."""
    return ~exists(
        select(1).where(
            Work.institution_id == OpenalexWork.institution_id,
            Work.doi_normalized == OpenalexWork.doi_normalized,
        )
    )


def parent_doi(doi: str | None) -> str | None:
    """DOI with its trailing ``_<segment>`` stripped: book-chapter DOIs
    share their parent book's DOI stem (10.1007/978-3-032-03219-5_4 ->
    10.1007/978-3-032-03219-5). One segment only; None when the DOI has
    no strippable suffix."""
    if not doi:
        return None
    head, sep, _tail = doi.rpartition("_")
    if not sep or not head or head.endswith("/"):
        return None
    return head


def pure_work_url(institution: Institution, pure_uuid: str | None) -> str | None:
    """Pure public record page for a work; None without a portal URL or
    an identified record."""
    if not pure_uuid or not institution.research_portal_url:
        return None
    return f"{institution.research_portal_url}/en/publications/{pure_uuid}"


async def tag_pure_matches(
    session: AsyncSession,
    institution: Institution,
    items: list[dict[str, Any]],
    author_uuids: list[set[str]],
    *,
    check_own_doi: bool,
) -> None:
    """Tag gap items whose publication is in fact held by Pure under a
    record the page does not show, so the UI can explain why a row is
    not truly missing. Mutates each item in place with:

    - ``pure_match``: 'doi_in_pure' (the DOI belongs to a Pure work the
      page does not list — a book, or a record not linked to the author),
      'parent_book_in_pure' (a chapter DOI whose parent book DOI is a
      Pure record), or 'same_title_in_pure' (a Pure record of the same
      normalized title sharing an author);
    - ``pure_match_url``: the identified Pure record's portal page.

    Precedence is doi > parent > title; untagged rows are the likely
    misses. One batched DOI/parent-DOI lookup and one batched title
    lookup per page — never per-row queries. Titles fold with the same
    function Pure ingestion uses (identifiers.norm_title), so both sides
    normalize identically.

    ``check_own_doi`` enables the doi_in_pure tag; venue/group cards
    already anti-join their rows against every Pure DOI of the
    institution, so there an exact-DOI hit cannot exist and the flag
    stays off. ``author_uuids`` is parallel to ``items``: the roster
    author uuids a same-title Pure record must share (the author themself
    on the author page, any matched roster member on the cards)."""
    dois = sorted({d for it in items if (d := normalize_doi(it.get("doi")))})
    parents = sorted({p for d in dois if (p := parent_doi(d))})
    doi_uuid: dict[str, str] = {}
    wanted = sorted({*dois, *parents})
    if wanted:
        rows = (
            await session.execute(
                select(Work.doi_normalized, Work.pure_uuid).where(
                    Work.institution_id == institution.id,
                    Work.doi_normalized.in_(wanted),
                )
            )
        ).all()
        doi_uuid = {r.doi_normalized: r.pure_uuid for r in rows}
    # norm title -> the Pure records carrying it and their roster authors
    title_rows: dict[str, set[tuple[str, str]]] = {}
    titles = sorted({t for it in items if (t := norm_title(it.get("title") or ""))})
    persons = sorted({u for ids in author_uuids for u in ids})
    if titles and persons:
        rows = (
            await session.execute(
                select(Work.norm_title, Work.pure_uuid, WorkPureAuthor.person_uuid)
                .join(
                    WorkPureAuthor,
                    (WorkPureAuthor.institution_id == Work.institution_id)
                    & (WorkPureAuthor.work_pure_uuid == Work.pure_uuid),
                )
                .where(
                    Work.institution_id == institution.id,
                    Work.norm_title.in_(titles),
                    WorkPureAuthor.person_uuid.in_(persons),
                )
                .distinct()
            )
        ).all()
        for r in rows:
            title_rows.setdefault(r.norm_title, set()).add((r.pure_uuid, r.person_uuid))
    for it, ids in zip(items, author_uuids, strict=False):
        doi = normalize_doi(it.get("doi"))
        match = None
        match_uuid = None
        if check_own_doi and doi and doi in doi_uuid:
            match, match_uuid = "doi_in_pure", doi_uuid[doi]
        if match is None and doi and (parent := parent_doi(doi)) in doi_uuid:
            match, match_uuid = "parent_book_in_pure", doi_uuid[parent]
        shared = title_rows.get(norm_title(it.get("title") or "")) if match is None else None
        hits = sorted(uuid for uuid, person in shared or () if person in ids)
        if hits:
            match, match_uuid = "same_title_in_pure", hits[0]
        it["pure_match"] = match
        it["pure_match_url"] = pure_work_url(institution, match_uuid)


#: The literal values tag_pure_matches writes into items' pure_match.
PureMatch = Literal["doi_in_pure", "parent_book_in_pure", "same_title_in_pure"]


async def _parent_registry(
    session: AsyncSession, institution: Institution, parent_ids: set[str]
) -> dict[str, Any]:
    """openalex_work_parents rows for the given parent W-ids, keyed by
    parent_w_id, with pure_registered derived live from the works table
    (EXISTS on the parent's normalized DOI; a no-DOI parent can never
    match, so it counts as not registered). No row = backfill pending =
    the caller serves null registry fields."""
    if not parent_ids:
        return {}
    # The model ships with the parts backfill job (that changeset owns
    # the migration); imported here so serving code loads on trees the
    # migration has not reached yet.
    from ..models import OpenalexWorkParent

    registered = exists(
        select(1).where(
            Work.institution_id == institution.id,
            Work.doi_normalized == OpenalexWorkParent.doi_normalized,
        )
    )
    rows = (
        await session.execute(
            select(
                OpenalexWorkParent.parent_w_id,
                OpenalexWorkParent.doi_normalized,
                OpenalexWorkParent.title,
                OpenalexWorkParent.work_type,
                registered.label("pure_registered"),
            ).where(
                OpenalexWorkParent.institution_id == institution.id,
                OpenalexWorkParent.parent_w_id.in_(sorted(parent_ids)),
            )
        )
    ).all()
    return {r.parent_w_id: r for r in rows}


async def group_gap_entries(
    session: AsyncSession, institution: Institution, items: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """Group gap work rows under their main work (the shared contract's
    entry shape): a part joins exactly one group — its primary parent —
    and a group holds only the missing rows fed in (registered parts
    never reach a gap payload). Standalone rows (no parent works) pass
    through as single entries; a group's parts keep the incoming order
    (most recent first).

    Returns (entries, entries_total); entries_total counts entries before
    any cap. Entries order most recent first — a standalone's own year, a
    group's newest part year (the entry's rendered recency) — ties by
    name (standalone title, group parent name). Parent registry fields
    come from _parent_registry; the group's name prefers the registry
    title (None coalesces to the parts' parent_works name)."""
    groups: dict[str, dict[str, Any]] = {}
    entries: list[dict[str, Any]] = []
    for it in items:
        primary = primary_parent(it.get("parent_works"))
        if primary is None:
            entries.append(
                {
                    "kind": "single",
                    **it,
                    "_year": it.get("year"),
                    "_name": (it.get("title") or "").lower(),
                }
            )
            continue
        # Parents without an id still group (by name): the registry
        # lookup needs the id, so their registry fields stay null.
        key = str(primary.get("id") or f"name:{(primary.get('name') or '').lower()}")
        group = groups.setdefault(key, {"primary": primary, "parts": [], "year": None})
        parts: list[dict[str, Any]] = group["parts"]
        parts.append(it)
        year = it.get("year")
        if year is not None and (group["year"] is None or year > group["year"]):
            group["year"] = year
    # One registry probe per distinct parent id; parents without an id
    # group by name but never hit the registry.
    parent_ids = {str(g["primary"]["id"]) for g in groups.values() if g["primary"].get("id")}
    registry = await _parent_registry(session, institution, parent_ids)
    for group in groups.values():
        primary = group["primary"]
        w_id = primary.get("id")
        reg = registry.get(str(w_id)) if w_id else None
        entries.append(
            {
                "kind": "group",
                "parent": {
                    "w_id": w_id,
                    "name": (reg.title if reg is not None else None) or primary.get("name"),
                    "work_type": reg.work_type if reg is not None else None,
                    "doi": reg.doi_normalized if reg is not None else None,
                    "pure_registered": bool(reg.pure_registered) if reg is not None else None,
                },
                "parts": group["parts"],
                "parts_total": len(group["parts"]),
                "_year": group["year"],
                "_name": str(primary.get("name") or "").lower(),
            }
        )
    entries.sort(key=lambda e: (e["_year"] is None, -(e["_year"] or 0), e["_name"]))
    for e in entries:
        del e["_year"], e["_name"]
    return entries, len(entries)


def attributed_to_any(aids: list[str]) -> Any:
    """True when the store row names any of the given bare OpenAlex
    author ids, case-insensitively.

    One EXISTS probe over the openalex_work_authors edge table (author-
    first PK): the unit's ids ride in as one text[] bind param compared
    with = ANY, so the bind count stays at one however large the id set
    grows (asyncpg rejects statements above 32,767 bound arguments, and
    faculty-sized id sets cleared that limit with the IN-list form).
    Measured on UT (Engineering Technology, ~1,100 ids): the gap count
    runs in ~0.45 s, against ~5 s for an unnest-subquery form and ~11 s
    for the pre-edge-table OR'd jsonb probes. Earlier forms degenerated
    on faculty-sized units (~1,200 ids for EEMCS): ~2,400 OR'd jsonb
    containment probes seq-scanned (~11 s), and the one-array-overlap
    replacement was worse — the overlap matched most of the store so the
    planner skipped the GIN and evaluated && per row (~45 s)."""
    lowered = sorted({aid.lower() for aid in aids if aid})
    if not lowered:
        return false()
    return exists(
        select(OpenalexWorkAuthor.author_id).where(
            OpenalexWorkAuthor.institution_id == OpenalexWork.institution_id,
            OpenalexWorkAuthor.w_id == OpenalexWork.w_id,
            # op("="), not ==: the generic eq commutes function calls,
            # which puts any() on the operator's left — a syntax error.
            OpenalexWorkAuthor.author_id.op("=")(
                func.any(bindparam("gap_aids", value=lowered, type_=ARRAY(Text)))
            ),
        )
    )


async def ut_roster_by_aids(
    session: AsyncSession, institution: Institution, aids: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """Roster authors whose openalex_ids intersect the given bare A-ids,
    keyed by lowercase id, one map entry per (author, id) pair.

    Values carry pure_uuid for dedupe (merged A-ids point at one author);
    ut_authors_for_authorships projects them to the served shape. Ids
    compare case-insensitively — the store's authorships carry OpenAlex's
    canonical uppercase form, openalex_ids stores lowercase ids."""
    wanted = sorted({aid.lower() for aid in aids if aid})
    if not wanted:
        return {}
    ids = func.jsonb_array_elements_text(Author.openalex_ids).table_valued(column("value", JSONB))
    rows = (
        await session.execute(
            select(
                Author.pure_uuid,
                Author.name,
                Author.orcid,
                Author.faculty,
                Author.research_group,
                Author.institute,
                Author.openalex_ids,
            ).where(
                Author.institution_id == institution.id,
                exists(
                    select(1)
                    .select_from(ids)
                    .where(
                        # op("="), not ==: the generic eq commutes function
                        # calls, which puts any() on the operator's left.
                        func.lower(ids.c.value).op("=")(
                            func.any(bindparam("roster_aids", value=wanted, type_=ARRAY(Text)))
                        )
                    )
                ),
            )
        )
    ).all()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        entry = {
            "pure_uuid": r.pure_uuid,
            "name": r.name,
            "orcid": r.orcid,
            "faculty": r.faculty,
            "research_group": r.research_group,
            "institute": r.institute,
        }
        for aid in r.openalex_ids or []:
            out.setdefault(str(aid).lower(), entry)
    return out


def ut_authors_for_authorships(
    authorships: list[Any] | None, roster: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Roster attribution for one work's compact authorships, authorship
    order kept, one row per roster author even when merged A-ids repeat
    and blanks skipped."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in authorships or []:
        hit = roster.get(str((entry or {}).get("a") or "").lower())
        if hit is None or hit["pure_uuid"] in seen:
            continue
        seen.add(hit["pure_uuid"])
        out.append({k: hit[k] for k in ("name", "orcid", "faculty", "research_group", "institute")})
    return out


def work_authors_of(authorships: list[Any] | None) -> list[dict[str, Any]]:
    """Authors of one work from the compact authorships array, order
    kept, blank ids skipped."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in authorships or []:
        if not isinstance(entry, dict):
            continue
        aid = str(entry.get("a") or "").strip()
        if not aid or aid in seen:
            continue
        seen.add(aid)
        out.append({"openalex_id": aid, "name": entry.get("n"), "orcid": entry.get("o")})
    return out


async def journal_publisher_map(session: AsyncSession, issns: Iterable[str]) -> dict[str, str]:
    """issn_l -> display publisher (canonical when known, else the raw
    publisher_name) for the venue join."""
    wanted = sorted({issn for issn in issns if issn})
    if not wanted:
        return {}
    rows = (
        await session.execute(
            select(
                Journal.issn_l,
                func.coalesce(
                    func.nullif(Journal.publisher_canonical, ""), Journal.publisher_name
                ).label("publisher"),
            ).where(Journal.issn_l.in_(wanted))
        )
    ).all()
    return {r.issn_l: r.publisher for r in rows}


def _gap_entry_stubs(rows: list[Any]) -> tuple[list[dict[str, Any]], int]:
    """Pass-1 grouping using only lightweight columns (no authorships JSONB,
    no DB lookups): preserves exact entry ordering and entries_total before
    GAP_ITEM_CAP slicing."""
    groups: dict[str, dict[str, Any]] = {}
    entries: list[dict[str, Any]] = []
    for r in rows:
        primary = primary_parent(r.parent_works)
        if primary is None:
            entries.append(
                {
                    "kind": "single",
                    "w_id": r.w_id,
                    "_year": r.year,
                    "_name": (r.title or "").lower(),
                }
            )
            continue
        key = str(primary.get("id") or f"name:{(primary.get('name') or '').lower()}")
        group = groups.setdefault(key, {"primary": primary, "w_ids": [], "year": None})
        group["w_ids"].append(r.w_id)
        year = r.year
        if year is not None and (group["year"] is None or year > group["year"]):
            group["year"] = year
    for group in groups.values():
        primary = group["primary"]
        entries.append(
            {
                "kind": "group",
                "w_ids": group["w_ids"],
                "_year": group["year"],
                "_name": str(primary.get("name") or "").lower(),
            }
        )
    entries.sort(key=lambda e: (e["_year"] is None, -(e["_year"] or 0), e["_name"]))
    return entries[:GAP_ITEM_CAP], len(entries)


async def _store_gap_counts(
    session: AsyncSession,
    institution: Institution,
    predicate: list[Any],
    *,
    parts: list[str] | None = None,
) -> tuple[bool, int, dict[str, int]]:
    """Return (available, total, parts_counts) without hydrating any gap rows."""
    if not await local_store_ready(session, institution):
        return False, 0, {}
    base_where = [OpenalexWork.institution_id == institution.id, *predicate]
    parts_sql = parts_predicate(parts)
    count_cols = [
        func.count().label("all"),
        func.count().filter(PART_KIND_PREDICATES["standalone"]).label("standalone"),
        func.count().filter(PART_KIND_PREDICATES["chapter"]).label("chapter"),
        func.count().filter(PART_KIND_PREDICATES["part"]).label("part"),
        *([func.count().filter(parts_sql).label("filtered")] if parts_sql is not None else []),
    ]
    counts_row = (await session.execute(select(*count_cols).where(*base_where))).one()
    parts_counts = {
        "all": int(counts_row.all or 0),
        "standalone": int(counts_row.standalone or 0),
        "chapter": int(counts_row.chapter or 0),
        "part": int(counts_row.part or 0),
    }
    total = int(counts_row.filtered or 0) if parts_sql is not None else parts_counts["all"]
    return True, total, parts_counts


async def _store_gap_payload(
    session: AsyncSession,
    institution: Institution,
    predicate: list[Any],
    parts: list[str] | None = None,
) -> dict[str, Any]:
    """Shared shape: exact work total + per-part counts + capped grouped
    entries over one store predicate (gates + attribution + anti-join).

    Two-pass execution avoids pulling thousands of authorships JSONB blobs
    or running Pure-match/roster enrichment beyond GAP_ITEM_CAP:
    1. Count all / standalone / chapter / part totals in one SQL pass, and
       fetch lightweight columns (w_id, title, year, parent_works, is_part)
       only to determine exact grouping order and `entries_total`.
    2. Hydrate full row details, UT author roster, publisher map, Pure-match
       tags, and parent registry ONLY for the `w_id`s inside top `entries[:GAP_ITEM_CAP]`."""
    ready, total, parts_counts = await _store_gap_counts(
        session, institution, predicate, parts=parts
    )
    if not ready:
        return _unavailable()
    if total == 0:
        return {
            "total": 0,
            "entries_total": 0,
            "items": [],
            "available": True,
            "parts_counts": parts_counts,
        }
    parts_sql = parts_predicate(parts)
    where = [
        OpenalexWork.institution_id == institution.id,
        *predicate,
        *([parts_sql] if parts_sql is not None else []),
    ]
    stub_rows = (
        await session.execute(
            select(
                OpenalexWork.w_id,
                OpenalexWork.title,
                OpenalexWork.year,
                OpenalexWork.parent_works,
            )
            .where(*where)
            .order_by(OpenalexWork.year.desc().nulls_last(), func.lower(OpenalexWork.title))
        )
    ).all()
    top_stubs, entries_total = _gap_entry_stubs(stub_rows)
    served_wids = sorted(
        {
            wid
            for stub in top_stubs
            for wid in ([stub["w_id"]] if stub["kind"] == "single" else stub["w_ids"])
        }
    )
    rows = (
        await session.execute(
            select(
                OpenalexWork.w_id,
                OpenalexWork.title,
                OpenalexWork.year,
                OpenalexWork.doi_normalized,
                OpenalexWork.oa_status,
                OpenalexWork.work_type,
                OpenalexWork.venue_issn_l,
                OpenalexWork.venue_name,
                OpenalexWork.authorships,
                OpenalexWork.parent_works,
                OpenalexWork.is_part,
            )
            .where(
                OpenalexWork.institution_id == institution.id, OpenalexWork.w_id.in_(served_wids)
            )
            .order_by(OpenalexWork.year.desc().nulls_last(), func.lower(OpenalexWork.title))
        )
    ).all()
    publishers = await journal_publisher_map(session, [r.venue_issn_l for r in rows])
    roster = await ut_roster_by_aids(
        session,
        institution,
        {
            aid.lower()
            for r in rows
            for entry in r.authorships or []
            if (aid := str((entry or {}).get("a") or ""))
        },
    )
    items = [
        {
            "title": r.title,
            "year": r.year,
            "doi": r.doi_normalized,
            "oa_status": r.oa_status,
            "work_type": r.work_type,
            "venue": r.venue_name,
            "openalex_id": r.w_id,
            "openalex_url": f"{OPENALEX_URL}/{r.w_id}",
            "authors": work_authors_of(r.authorships),
            "ut_authors": ut_authors_for_authorships(r.authorships, roster),
            "journal_issn_l": r.venue_issn_l,
            "journal_title": r.venue_name,
            "publisher_name": publishers.get(r.venue_issn_l),
            "parent_works": r.parent_works or [],
            "is_part": bool(r.is_part),
        }
        for r in rows
    ]
    await tag_pure_matches(
        session,
        institution,
        items,
        [
            {
                m["pure_uuid"]
                for entry in r.authorships or []
                if (m := roster.get(str((entry or {}).get("a") or "").lower()))
            }
            for r in rows
        ],
        check_own_doi=False,
    )
    entries, _ = await group_gap_entries(session, institution, items)
    return {
        "total": total,
        "entries_total": entries_total,
        "items": entries[:GAP_ITEM_CAP],
        "available": True,
        "parts_counts": parts_counts,
    }


def venue_gap_predicate(
    institution: Institution, venue_issns: list[str], year_range: tuple[int, int] | None = None
) -> list[Any]:
    """One venue-attributed gap predicate: the venue(s)' issn set, the
    institution-filter corpus cutoff (source != author-sweep), the store
    gates and the Pure DOI anti-join — the exact population
    venue_openalex_only serves, shared with the chapter rollup."""
    return [
        OpenalexWork.venue_issn_l.in_(sorted(set(venue_issns))),
        OpenalexWork.source != AUTHOR_SWEEP_PREFIX,
        *store_gates(institution, year_range),
        not_in_pure(),
    ]


def _flat_aids(aids: list[str]) -> list[str]:
    """Bare lowercase OpenAlex author ids from the possibly nested list
    (authors.openalex_ids stores lowercase ids; the store's authorships
    carry OpenAlex's canonical uppercase form)."""
    return sorted(
        {aid.lower() for row in aids for aid in (row if isinstance(row, list) else [row]) if aid}
    )


def aids_gap_predicate(
    institution: Institution, aids: list[str], year_range: tuple[int, int] | None = None
) -> list[Any]:
    """One attribution-keyed gap predicate: any of the given OpenAlex
    author ids, the store gates and the Pure DOI anti-join — the exact
    population author_ids_openalex_only serves, shared with the chapter
    rollup."""
    return [
        attributed_to_any(_flat_aids(aids)),
        *store_gates(institution, year_range),
        not_in_pure(),
    ]


async def chapter_rollup(
    session: AsyncSession,
    institution: Institution,
    predicate: list[Any],
    parts: list[str] | None = None,
) -> dict[str, Any]:
    """Chapter/book rollup over one gap predicate: the same population
    the page's openalex-only card serves, before its item cap.

    chapters_total counts chapter-kind works (is_part with a volume
    parent); books_total the distinct volume parents. books is the top
    CHAPTER_ROLLUP_BOOKS by chapter count (ties by name, id), each with
    up to CHAPTER_ROLLUP_SAMPLE sample chapter titles. One unnest pass
    aggregates every book's titles — bounded work for chapter-sized
    groups."""
    where = [OpenalexWork.institution_id == institution.id, *predicate]
    if (parts_sql := parts_predicate(parts)) is not None:
        where.append(parts_sql)
    where.append(PART_KIND_PREDICATES["chapter"])
    chapters_total = (
        await session.scalar(select(func.count()).select_from(OpenalexWork).where(*where))
    ) or 0
    parents = (
        func.jsonb_array_elements(OpenalexWork.parent_works)
        .table_valued("value", name="parent")
        .render_derived()
    )
    parent_id = func.coalesce(parents.c.value.op("->>")("id"), "")
    parent_name = func.coalesce(parents.c.value.op("->>")("name"), "")
    # The set-returning function in FROM is implicitly lateral in
    # Postgres; SQLAlchemy mistakes it for a cartesian product.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message=".*cartesian product.*", category=sa_exc.SAWarning
        )
        rows = (
            await session.execute(
                select(
                    parent_id.label("parent_id"),
                    parent_name.label("name"),
                    func.count(func.distinct(OpenalexWork.w_id)).label("chapters"),
                    func.jsonb_agg(func.distinct(OpenalexWork.title)).label("titles"),
                )
                .select_from(OpenalexWork, parents)
                .where(*where, parents.c.value.op("->>")("rel") == "volume")
                .group_by(parent_id, parent_name)
            )
        ).all()
    books = sorted(
        (
            {
                "parent_id": r.parent_id or None,
                "name": str(r.name),
                "chapters": int(r.chapters),
                "titles": sorted(t for t in (r.titles or ()) if t),
            }
            for r in rows
        ),
        key=lambda b: (-b["chapters"], str(b["name"]).lower(), b["parent_id"] or ""),
    )
    return {
        "chapters_total": int(chapters_total),
        "books_total": len(books),
        "books": [
            {
                "parent_id": b["parent_id"],
                "name": b["name"],
                "chapters": b["chapters"],
                "sample": b["titles"][:CHAPTER_ROLLUP_SAMPLE],
            }
            for b in books[:CHAPTER_ROLLUP_BOOKS]
        ],
    }


async def venue_openalex_only(
    session: AsyncSession,
    institution: Institution,
    *,
    issn_l: str | None = None,
    issns: list[str] | None = None,
    year_range: tuple[int, int] | None = None,
    parts: list[str] | None = None,
) -> dict[str, Any]:
    """Store works in the venue(s) the Pure population does not hold.

    One issn for the journal view, the publisher group's issn set for the
    publisher view. Attribution key is venue_issn_l — the same key the
    OpenAlex-side institution metrics use. parts (pipe-joined
    standalone|chapter|part) filters the served rows and totals; the
    survivors group under their main works.

    Restricted to the institution-filter corpus (source != author-sweep):
    those rows were harvested under OpenAlex's institutions.id filter, so
    OpenAlex itself attributes them to this institution. Author-sweep rows
    carry an author's full profile — works OpenAlex attributes elsewhere
    or to no institution — and counting those here would report the
    venue's global output as a CRIS gap."""
    venue_issns = [issn_l] if issn_l is not None else sorted(set(issns or []))
    if not venue_issns:
        return {"total": 0, "entries_total": 0, "items": [], "available": True, "parts_counts": {}}
    return await _store_gap_payload(
        session,
        institution,
        venue_gap_predicate(institution, venue_issns, year_range),
        parts=parts,
    )


async def author_ids_openalex_only(
    session: AsyncSession,
    institution: Institution,
    aids: list[str],
    year_range: tuple[int, int] | None = None,
    parts: list[str] | None = None,
) -> dict[str, Any]:
    """Store works attributed to any of the given OpenAlex author ids the
    Pure population does not hold (org-unit gap card).

    Attribution unnests the authorships array and compares bare A-ids
    case-insensitively: authors.openalex_ids stores lowercase ids while
    the store's authorships carry OpenAlex's canonical uppercase form, so
    a work counts once however many of the unit's authors it names.
    parts (pipe-joined standalone|chapter|part) filters rows and total;
    the survivors group under their main works."""
    if not _flat_aids(aids):
        return {
            "total": 0,
            "entries_total": 0,
            "items": [],
            "available": await local_store_ready(session, institution),
            "parts_counts": {},
        }
    return await _store_gap_payload(
        session,
        institution,
        aids_gap_predicate(institution, aids, year_range),
        parts=parts,
    )


async def venue_openalex_only_counts(
    session: AsyncSession,
    institution: Institution,
    *,
    issn_l: str | None = None,
    issns: list[str] | None = None,
    year_range: tuple[int, int] | None = None,
    parts: list[str] | None = None,
) -> dict[str, Any]:
    """Count-only counterpart to `venue_openalex_only` when entries are deferred."""
    venue_issns = [issn_l] if issn_l is not None else sorted(set(issns or []))
    if not venue_issns:
        return {"total": 0, "entries_total": 0, "items": [], "available": True, "parts_counts": {}}
    ready, total, parts_counts = await _store_gap_counts(
        session,
        institution,
        venue_gap_predicate(institution, venue_issns, year_range),
        parts=parts,
    )
    if not ready:
        return _unavailable()
    return {
        "total": total,
        "entries_total": 0,
        "items": [],
        "available": True,
        "parts_counts": parts_counts,
    }


async def author_ids_openalex_only_counts(
    session: AsyncSession,
    institution: Institution,
    aids: list[str],
    year_range: tuple[int, int] | None = None,
    parts: list[str] | None = None,
) -> dict[str, Any]:
    """Count-only counterpart to `author_ids_openalex_only` when entries are deferred."""
    if not _flat_aids(aids):
        return {
            "total": 0,
            "entries_total": 0,
            "items": [],
            "available": await local_store_ready(session, institution),
            "parts_counts": {},
        }
    ready, total, parts_counts = await _store_gap_counts(
        session,
        institution,
        aids_gap_predicate(institution, aids, year_range),
        parts=parts,
    )
    if not ready:
        return _unavailable()
    return {
        "total": total,
        "entries_total": 0,
        "items": [],
        "available": True,
        "parts_counts": parts_counts,
    }


async def venue_authorship(
    session: AsyncSession,
    institution: Institution,
    *,
    issn_l: str | None = None,
    issns: list[str] | None = None,
    year_range: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Who at this institution authors the venue's canonical works.

    Distinct works per faculty and per research group plus the top
    authors, all over one population: the works-table rows the search
    card counts, restricted to rows with at least one UT author edge.
    Rows whose faculty/research_group attribute is missing stay in
    n_ut_works but form no bucket. An explicit publication-year range
    replaces the data-window bounds (the works-derived numbers scope;
    None keeps the window, byte-identical)."""
    venue_issns = [issn_l] if issn_l is not None else sorted(set(issns or []))
    empty: dict[str, Any] = {
        "n_ut_works": 0,
        "faculties": [],
        "research_groups": [],
        "top_authors": [],
    }
    if not venue_issns:
        return empty
    population = [
        Work.institution_id == institution.id,
        Work.journal_issn_l.in_(venue_issns),
        Work.retired_at.is_(None),
        *work_year_window(institution, year_range),
        work_type_not_excluded(Work.work_type),
    ]
    pairs = (
        select(
            Work.pure_uuid.label("work_uuid"),
            Author.faculty.label("faculty"),
            Author.research_group.label("research_group"),
            Author.pure_uuid.label("author_uuid"),
            Author.name.label("name"),
        )
        .join(
            WorkPureAuthor,
            (WorkPureAuthor.institution_id == Work.institution_id)
            & (WorkPureAuthor.work_pure_uuid == Work.pure_uuid),
        )
        .join(
            Author,
            (Author.institution_id == WorkPureAuthor.institution_id)
            & (Author.pure_uuid == WorkPureAuthor.person_uuid),
        )
        .where(*population)
        .cte("pairs")
    )
    works = func.count(func.distinct(pairs.c.work_uuid)).label("works")
    # One statement over the materialized pairs CTE (Postgres materializes
    # a multiply-referenced CTE) instead of four statements that each
    # re-derived the works x work_pure_authors x authors join: the
    # publisher page rebuilt that population four times per request.
    # kind 0 = the distinct-works total, 1/2 = faculty/research-group
    # buckets, 3 = top authors; branch-internal ORDER BY/LIMITs match the
    # per-statement queries this replaced, and UNION ALL keeps them.
    rows = (
        await session.execute(
            union_all(
                select(
                    literal(0).label("kind"),
                    cast(literal(None), Text).label("name"),
                    cast(literal(None), Text).label("faculty"),
                    cast(literal(None), Text).label("research_group"),
                    cast(literal(None), Text).label("author_uuid"),
                    works,
                ).select_from(pairs),
                select(
                    literal(1).label("kind"),
                    pairs.c.faculty.label("name"),
                    cast(literal(None), Text).label("faculty"),
                    cast(literal(None), Text).label("research_group"),
                    cast(literal(None), Text).label("author_uuid"),
                    works,
                )
                .select_from(pairs)
                .where(pairs.c.faculty.is_not(None), pairs.c.faculty != "")
                .group_by(pairs.c.faculty)
                .order_by(works.desc(), pairs.c.faculty),
                select(
                    literal(2).label("kind"),
                    pairs.c.research_group.label("name"),
                    cast(literal(None), Text).label("faculty"),
                    cast(literal(None), Text).label("research_group"),
                    cast(literal(None), Text).label("author_uuid"),
                    works,
                )
                .select_from(pairs)
                .where(pairs.c.research_group.is_not(None), pairs.c.research_group != "")
                .group_by(pairs.c.research_group)
                .order_by(works.desc(), pairs.c.research_group),
                select(
                    literal(3).label("kind"),
                    pairs.c.name.label("name"),
                    pairs.c.faculty.label("faculty"),
                    pairs.c.research_group.label("research_group"),
                    pairs.c.author_uuid.label("author_uuid"),
                    works,
                )
                .select_from(pairs)
                .group_by(
                    pairs.c.author_uuid, pairs.c.name, pairs.c.faculty, pairs.c.research_group
                )
                .order_by(works.desc(), func.lower(pairs.c.name))
                .limit(TOP_AUTHORS),
            )
        )
    ).all()
    return {
        "n_ut_works": next((int(r.works) for r in rows if r.kind == 0), 0),
        "faculties": [{"name": r.name, "works": int(r.works)} for r in rows if r.kind == 1],
        "research_groups": [{"name": r.name, "works": int(r.works)} for r in rows if r.kind == 2],
        "top_authors": [
            {
                "pure_uuid": r.author_uuid,
                "name": r.name,
                "faculty": r.faculty,
                "research_group": r.research_group,
                "works": int(r.works),
            }
            for r in rows
            if r.kind == 3
        ],
    }
