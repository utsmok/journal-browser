"""ut-metadata authors ingest: identities, org-derived attributes, work edges.

Source side (all names verified live 2026-10-26):
    core_author_link            person roster (Pure uuid keyed)
    source_records persons      latest CERIF payload per person (version
                                order by id; no created_at)
    org / org_tree              org display names + closure (depth 0 = self)
    work_authors                author_a_id is an OpenAlex author id in
                                LOWERCASE form; core_work_link maps canonical
                                work ids to Pure uuids
    person / person_org / source_identity (persons)  canonical-person path

Faculty rule (mirrors the source repo's reconcile/org_tree.py): walking org
names self -> root, the first name in the faculty set wins, canonicalized to
the full faculty name. Author-native path first; authors without a faculty
there fall back to the canonical-person path (person_org)."""

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from ..config import work_type_excluded
from ..models import Author, AuthorWork, Institution, Journal

logger = logging.getLogger(__name__)

#: Canonical faculty names; org display names matching one of these (exactly,
#: so "Faculty Council of EEMCS" & co. never match) decide the faculty.
FACULTIES = (
    "Faculty of Science and Technology",
    "Faculty of Engineering Technology",
    "Faculty of Behavioural, Management and Social Sciences",
    "Faculty of Geo-Information Science and Earth Observation",
    "Faculty of Electrical Engineering, Mathematics and Computer Science",
)

#: Short codes map onto the canonical full name.
_FACULTY_ALIASES = {
    "TNW": FACULTIES[0],
    "ET": FACULTIES[1],
    "BMS": FACULTIES[2],
    "ITC": FACULTIES[3],
    "EEMCS": FACULTIES[4],
}
_FACULTY_SET = frozenset(FACULTIES) | frozenset(_FACULTY_ALIASES)

UNIVERSITY_ROOT_NAME = "University of Twente"


def canonical_faculty(name: str) -> str:
    """Full faculty name for any member of the faculty name set."""
    return _FACULTY_ALIASES.get(name, name)


@dataclass
class SourceData:
    """One full pull of the author-relevant ut-metadata tables."""

    # core_author_link rows.
    authors: list[dict[str, Any]] = field(default_factory=list)
    # latest pure person payload per person uuid (split off source_pk).
    persons: dict[str, dict[str, Any]] = field(default_factory=dict)
    # org id -> (pure_uuid, display_name).
    orgs: dict[int, tuple[str, str]] = field(default_factory=dict)
    # org id -> bare ROR id (None when the org has none).
    org_rors: dict[int, str | None] = field(default_factory=dict)
    # org_tree closure: org_id -> [(depth, ancestor_id)].
    tree: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    # work_authors edges resolved onto canonical Pure work uuids.
    edges: list[tuple[str, str]] = field(default_factory=list)
    # orcid -> person id (canonical-person path, orcid branch).
    person_orcids: dict[str, int] = field(default_factory=dict)
    # lower(openalex author id) -> canonical person id.
    person_by_openalex: dict[str, int] = field(default_factory=dict)
    # person_org: person id -> [org ids].
    person_orgs: dict[int, list[int]] = field(default_factory=dict)


async def fetch_source(engine: AsyncEngine) -> SourceData:
    """Pull every author-relevant table in five round trips."""
    data = SourceData()
    async with engine.connect() as conn:
        data.authors = [
            dict(row)
            for row in (
                await conn.execute(
                    text(
                        "SELECT pure_uuid, orcid, pure_name AS name, "
                        "openalex_author_id, openaire_person_id, crossref_orcid, "
                        "openalex_alt_ids FROM core_author_link"
                    )
                )
            ).mappings()
        ]
        rows = await conn.execute(
            text(
                "SELECT DISTINCT ON (split_part(source_pk, '/', 2)) "
                "split_part(source_pk, '/', 2) AS uuid, payload "
                "FROM source_records WHERE source = 'pure' AND entity_type = 'persons' "
                "ORDER BY 1, id DESC"
            )
        )
        data.persons = {row["uuid"]: row["payload"] for row in rows.mappings()}
        for org_id, pure_uuid, name, ror in await conn.execute(
            text("SELECT id, pure_uuid, display_name, ror FROM org")
        ):
            data.orgs[org_id] = (pure_uuid, name)
            data.org_rors[org_id] = ror
        for org_id, ancestor_id, depth in await conn.execute(
            text("SELECT org_id, ancestor_id, depth FROM org_tree")
        ):
            data.tree.setdefault(org_id, []).append((depth, ancestor_id))
        data.edges = [
            (a, w)
            for a, w in await conn.execute(
                text(
                    "SELECT wa.author_a_id, w.pure_uuid FROM work_authors wa "
                    "JOIN core_work_link w ON w.id = wa.work_id"
                )
            )
        ]
        for person_id, orcid in await conn.execute(
            text("SELECT id, orcid FROM person WHERE orcid IS NOT NULL")
        ):
            data.person_orcids[orcid] = person_id
        for source_pk, canonical_id in await conn.execute(
            text(
                "SELECT lower(source_pk), canonical_id FROM source_identity "
                "WHERE entity_type = 'persons' AND source = 'openalex'"
            )
        ):
            data.person_by_openalex[source_pk] = canonical_id
        for person_id, org_id in await conn.execute(
            text("SELECT person_id, org_id FROM person_org ORDER BY person_id, org_id")
        ):
            data.person_orgs.setdefault(person_id, []).append(org_id)
    return data


def author_id_index(authors: list[dict[str, Any]]) -> dict[str, str]:
    """lower(OpenAlex author id) / lower(alt id) -> author pure_uuid.

    work_authors.author_a_id is stored lower-cased, so the whole index is
    lower-cased too."""
    index: dict[str, str] = {}
    for author in authors:
        uuid = author["pure_uuid"]
        ids = [author.get("openalex_author_id"), *(author.get("openalex_alt_ids") or [])]
        for value in ids:
            if value:
                index.setdefault(value.lower(), uuid)
    return index


def chain(data: SourceData, org_id: int) -> list[tuple[int, str]]:
    """One org's closure as (depth, ancestor display name), self -> root."""
    return sorted(
        (
            (depth, data.orgs[ancestor_id][1])
            for depth, ancestor_id in data.tree.get(org_id, [])
            if ancestor_id in data.orgs
        ),
        key=lambda item: (item[0], item[1]),
    )


def faculty_from_chains(chains: list[list[tuple[int, str]]]) -> str | None:
    """First faculty-set name across the chains, canonicalized; None if none."""
    for chain_rows in chains:
        for _depth, name in chain_rows:
            if name in _FACULTY_SET:
                return canonical_faculty(name)
    return None


def _affiliation_org_ids(payload: dict[str, Any], orgs: dict[int, tuple[str, str]]) -> list[int]:
    """Affiliation uuids that resolve to an org row, in payload order."""
    by_uuid = {pure_uuid: org_id for org_id, (pure_uuid, _name) in orgs.items()}
    ids: list[int] = []
    for affiliation in (payload.get("cerif") or {}).get("affiliations") or []:
        org_id = by_uuid.get(affiliation.get("affiliation_id"))
        if org_id is not None:
            ids.append(org_id)
    return ids


def derive_identity(
    payload: dict[str, Any], data: SourceData
) -> tuple[str | None, str | None, list[str]]:
    """(faculty, research_group, orgs) from one person's CERIF payload.

    research_group: the first affiliation org (payload order) that is
    neither a faculty nor the university root and whose closure reaches a
    faculty. orgs: distinct affiliation display names, most specific first
    (largest closure depth = furthest from the root)."""
    org_ids = _affiliation_org_ids(payload, data.orgs)
    chains = [chain(data, org_id) for org_id in org_ids]
    faculty = faculty_from_chains(chains)
    research_group = None
    for org_id, chain_rows in zip(org_ids, chains, strict=True):
        name = data.orgs[org_id][1]
        if name in _FACULTY_SET or name == UNIVERSITY_ROOT_NAME:
            continue
        if any(n in _FACULTY_SET for _d, n in chain_rows):
            research_group = name
            break
    org_names: list[str] = []
    seen: set[str] = set()
    depth_order = sorted(
        ((org_id, max((d for d, _n in chain(data, org_id)), default=0)) for org_id in org_ids),
        key=lambda item: (-item[1], data.orgs[item[0]][1]),
    )
    for org_id, _depth in depth_order:
        name = data.orgs[org_id][1]
        if name not in seen:
            seen.add(name)
            org_names.append(name)
    return faculty, research_group, org_names


def canonical_person_ids(author: dict[str, Any], data: SourceData) -> list[int]:
    """Canonical person ids for an author: orcid branch, then the OpenAlex
    source_identity branch (lower-cased comparison on both sides)."""
    found: list[int] = []
    orcid = author.get("orcid")
    if orcid and (person_id := data.person_orcids.get(orcid)):
        found.append(person_id)
    openalex_id = author.get("openalex_author_id")
    person_id = data.person_by_openalex.get(openalex_id.lower()) if openalex_id else None
    if person_id is not None and person_id not in found:
        found.append(person_id)
    return found


def augment_faculty(author: dict[str, Any], data: SourceData) -> str | None:
    """Faculty via the canonical-person path (only reached when the
    author-native CERIF path resolved nothing)."""
    person_ids = canonical_person_ids(author, data)
    chains = [
        chain(data, org_id)
        for person_id in person_ids
        for org_id in data.person_orgs.get(person_id, [])
    ]
    return faculty_from_chains(chains)


def _ror_id(ror: str | None) -> str | None:
    """Bare ROR id: source org.ror stores '006hf6230', institutions.ror the
    'https://ror.org/006hf6230' URL form."""
    return ror.rstrip("/").rsplit("/", 1)[-1] if ror else None


def is_confirmed(payload: dict[str, Any], data: SourceData, ror: str | None) -> bool:
    """Confirmed affiliated iff a CERIF payload exists and some affiliation
    org's closure (self at depth 0) reaches the institution's ROR org."""
    target = _ror_id(ror)
    if target is None or not payload:
        return False
    for org_id in _affiliation_org_ids(payload, data.orgs):
        for _depth, ancestor_id in data.tree.get(org_id, []):
            if _ror_id(data.org_rors.get(ancestor_id)) == target:
                return True
    return False


def topic_mass(
    venues: dict[str, int], topics_by_issn: dict[str, list[Any]]
) -> dict[str, float]:
    """Works-weighted topic mass across venues.

    Each venue's works are spread over its OpenAlex topic list in
    proportion to the topics' per-source `count` (a venue split
    40/30/20/10 contributes its works exactly that way), and labels carry
    the topics' subfield — coarser than topic names, whose hyper-specific
    fragments made "most common topic" nearly meaningless. Venues without
    counts (rows stored before the field was persisted) contribute to
    their primary topic only; entries without a subfield fall back to the
    topic name."""
    mass: dict[str, float] = {}
    for issn, n in venues.items():
        entries = [
            t
            for t in topics_by_issn.get(issn) or []
            if isinstance(t, dict) and t.get("display_name")
        ]
        if not entries:
            continue
        counts = [int(t.get("count") or 0) for t in entries]
        total = sum(counts)
        if total <= 0:
            name = entries[0].get("subfield") or entries[0]["display_name"]
            mass[name] = mass.get(name, 0.0) + n
            continue
        for t, c in zip(entries, counts, strict=False):
            name = t.get("subfield") or t["display_name"]
            mass[name] = mass.get(name, 0.0) + n * c / total
    return mass


def primary_topic_from_venues(
    venues: dict[str, int], topics_by_issn: dict[str, list[Any]]
) -> str | None:
    """Top topic by venue mass (see topic_mass), ties alphabetical; None
    without journals or topics."""
    mass = topic_mass(venues, topics_by_issn)
    return min(mass, key=lambda name: (-mass[name], name)) if mass else None


def build_edge_map(
    edges: list[tuple[str, str]],
    index: dict[str, str],
    local_work_uuids: set[str],
) -> dict[str, set[str]]:
    """author pure_uuid -> set of local work uuids, via the lower-cased
    author-id index. Edges to works the institution does not hold drop out."""
    mapping: dict[str, set[str]] = {}
    for author_a_id, work_uuid in edges:
        author_uuid = index.get(author_a_id.lower())
        if author_uuid is not None and work_uuid in local_work_uuids:
            mapping.setdefault(author_uuid, set()).add(work_uuid)
    return mapping


async def ingest_authors(
    session: AsyncSession, institution_id: int, engine: AsyncEngine, inst_ror: str | None
) -> dict:
    """Full pull + full-replace upsert for one institution.

    authors upserts in place (identity fields + derived attributes);
    author_works is deleted and rebuilt, so works retired since the last
    run drop out of every count. n_works counts the stored edges.
    last_pub_year / primary_topic derive from those same edges, bounded to
    the institution's publication-year window; confirmed
    checks the person payload's affiliations against the institution ROR.
    Edges to preprint/book works (config.EXCLUDED_WORK_TYPES) are not
    stored, so no author count, list, or topic sees them."""
    data = await fetch_source(engine)
    # The institution row carries the publication-year window; edges to
    # works outside it drop out of every derived count below.
    institution = await session.get(Institution, institution_id)
    year_start = institution.data_window_start
    year_end = institution.data_window_end if institution.data_window_end is not None else 9999
    local_works = {
        row["pure_uuid"]: (row["year"], row["journal_issn_l"])
        for row in (
            await session.execute(
                text(
                    "SELECT pure_uuid, year, journal_issn_l, work_type FROM works "
                    "WHERE institution_id = :iid AND retired_at IS NULL "
                    "AND year BETWEEN :ws AND :we"
                ),
                {"iid": institution_id, "ws": year_start, "we": year_end},
            )
        ).mappings()
        if not work_type_excluded(row["work_type"])
    }
    index = author_id_index(data.authors)
    edge_map = build_edge_map(data.edges, index, set(local_works))

    # One pass over the new edge set: last publication year and per-venue
    # work counts (primary_topic weighting input).
    last_years: dict[str, int | None] = {}
    venues_by_author: dict[str, dict[str, int]] = {}
    for author_uuid, work_uuids in edge_map.items():
        venues: dict[str, int] = {}
        last_year: int | None = None
        for w in work_uuids:
            year, issn = local_works[w]
            if year is not None and (last_year is None or year > last_year):
                last_year = year
            if issn:
                venues[issn] = venues.get(issn, 0) + 1
        last_years[author_uuid] = last_year
        venues_by_author[author_uuid] = venues
    issns = {issn for venues in venues_by_author.values() for issn in venues}
    topics_by_issn: dict[str, list[Any]] = {}
    if issns:
        rows = await session.execute(
            select(Journal.issn_l, Journal.topics).where(Journal.issn_l.in_(issns))
        )
        topics_by_issn = {issn: topics or [] for issn, topics in rows.all()}

    author_rows = []
    stats = {"with_faculty": 0, "with_research_group": 0, "confirmed": 0}
    for author in data.authors:
        payload = data.persons.get(author["pure_uuid"], {})
        faculty, research_group, org_names = derive_identity(payload, data)
        if faculty is None:
            faculty = augment_faculty(author, data)
        if faculty is not None:
            stats["with_faculty"] += 1
        if research_group is not None:
            stats["with_research_group"] += 1
        uuid = author["pure_uuid"]
        confirmed = is_confirmed(payload, data, inst_ror)
        if confirmed:
            stats["confirmed"] += 1
        author_rows.append(
            {
                "institution_id": institution_id,
                "pure_uuid": uuid,
                "name": author["name"] or "",
                "orcid": author["orcid"],
                "openalex_author_id": author["openalex_author_id"],
                "openaire_person_id": author["openaire_person_id"],
                "crossref_orcid": author["crossref_orcid"],
                "faculty": faculty,
                "research_group": research_group,
                "orgs": org_names,
                "n_works": len(edge_map.get(uuid, ())),
                "confirmed": confirmed,
                "last_pub_year": last_years.get(uuid),
                "primary_topic": primary_topic_from_venues(
                    venues_by_author.get(uuid, {}), topics_by_issn
                ),
            }
        )
    if author_rows:
        # Full-replace: authors that left the source roster must not linger
        # with stale n_works, so clear the institution's rows and reinsert.
        await session.execute(delete(Author).where(Author.institution_id == institution_id))
        # asyncpg caps one statement at 32767 bound params; 14 per author row.
        for start in range(0, len(author_rows), 2000):
            await session.execute(insert(Author), author_rows[start : start + 2000])
    await session.execute(delete(AuthorWork).where(AuthorWork.institution_id == institution_id))
    edge_rows = [
        {
            "institution_id": institution_id,
            "author_pure_uuid": author_uuid,
            "work_pure_uuid": work_uuid,
        }
        for author_uuid, works in edge_map.items()
        for work_uuid in works
    ]
    for start in range(0, len(edge_rows), 10000):
        await session.execute(insert(AuthorWork), edge_rows[start : start + 10000])
    return {
        "authors": len(author_rows),
        "edges": len(edge_rows),
        **stats,
    }
