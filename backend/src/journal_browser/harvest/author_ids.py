"""Author identity resolution: the ported cascade over JB's own stores.

Per local work, the org-tree-filtered pure author list (work_pure_authors
with work-entry name spellings) meets the matched OpenAlex work's
authorships (openalex_works, DOI-keyed). The ported cascade decides per
work; aggregation across a person's works ranks methods and counts
conflicting ids. The primary id follows the rung ladder
(confirmed/candidate/rejected — candidates never auto-promote; admin
decisions are sticky). Work-matched alternate ids ride along as
confirmed fragmentation twins only when the work-level evidence says
they are the same human: never co-occurring with the primary id on one
work, and no contradicting ORCID. Competing namesake ids stay
candidates for the review queue. The authors ingest reads this table
additively: confirmed rows feed authors.openalex_ids.

Runs with no DSN; the only API spend is the authors listing sweep
(filter affiliations.institution.ror, verified live 2026-10-30 — the
singular "affiliation." form is rejected by the API) and the
budget-capped per-author works enrichment (50 batched A-ids per keyed
call) covering authors whose OpenAlex profile lacks the institution.
"""

import logging
import time
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..ingest import IngestSession
from ..models import (
    AuthorIdentity,
    HarvestRun,
    OpenalexWork,
    PurePerson,
    SourceRecord,
    Work,
    WorkPureAuthor,
)
from .author_cascade import (
    METHOD_FUZZY,
    METHOD_INITIALS,
    METHOD_NAME,
    METHOD_ORCID,
    ExtEntry,
    PureAuthor,
    aggregate,
    match,
    openalex_entries,
)
from .author_names import bare_orcid, decompose_parts
from .openalex_journals import openalex_id_to_pk, resolve_institution_openalex_id
from .org_closure import load_org_tree

logger = logging.getLogger(__name__)

SOURCE = "openalex"
SOURCE_OPENAIRE = "openaire"
AUTHOR_ENTITY = "authors"
SWEEP_FILTER_PREFIX = "author-sweep"
BATCH_SIZE = 50  # OpenAlex pipe-OR ceiling (ut-metadata gap-fetch size)
PER_PAGE = 200

#: evidence quality per rung (review-list sort + display)
CONFIDENCE = {
    METHOD_ORCID: 1.0,
    "name-exact": 0.9,
    "name-initials": 0.8,
    "family-unique": 0.7,
    METHOD_FUZZY: 0.6,
}


def _derived_status(method: str | None, conflicts: int) -> str:
    """Status of a cascade-derived primary id.

    orcid-exact is fact-grade; the deterministic name rungs are confirmed
    when nothing conflicts; the fuzzy floor rung is the weakest evidence
    and always lands as candidate; fragmented primaries stay confirmed
    (the alternates carry the review need)."""
    if method == METHOD_ORCID:
        return "confirmed"
    if conflicts == 0 and method != METHOD_FUZZY:
        return "confirmed"
    return "candidate"


async def sweep_openalex_authors(
    client, session: AsyncSession, institution, limit: int | None = None
) -> dict[str, Any]:
    """Listing sweep: the institution's OpenAlex author profiles
    (affiliations.institution.ror filter) into source_records
    (entity_type authors). Corroboration source + recall complement for
    the work-anchored cascade."""
    ror = institution.ror.rsplit("/", 1)[-1].lower() if institution.ror else None
    if not ror:
        raise ValueError(f"institution {institution.code!r} has no ROR")
    inst_id = await resolve_institution_openalex_id(client, session, institution)
    filter_set = f"affiliations.institution.ror={ror}"
    ingest = IngestSession(session)
    config = {
        "filter": filter_set,
        "institution_openalex_id": inst_id,
        "page_size": PER_PAGE,
    }
    await ingest.start_run(SOURCE, AUTHOR_ENTITY, filter_set, config, institution_id=institution.id)

    async def commit_page(_page: int, _cursor: str | None) -> None:
        await ingest.commit()

    async for item in client.authors.iterate(
        page_size=PER_PAGE,
        filters={"affiliations.institution.ror": ror},
        on_page=commit_page,
    ):
        payload = (
            item
            if isinstance(item, dict)
            else (item.model_dump(mode="json") if hasattr(item, "model_dump") else None)
        )
        if not payload or not payload.get("id"):
            await ingest.record_parse_failure({"source_pk": None, "reason": "author parse failure"})
            continue
        await ingest.ingest_record(openalex_id_to_pk(payload.get("id")), payload)
        if limit is not None and ingest.records_seen >= limit:
            logger.info("Reached --limit %s", limit)
            break
    stats = await ingest.finish_run("completed", {})
    await session.commit()
    return stats


async def _listing_orcids(session: AsyncSession, institution_id: int) -> dict[str, str | None]:
    """Latest stored author listing payload per bare A-id (corroboration
    source beyond work authorships)."""
    stmt = (
        select(SourceRecord.source_pk, SourceRecord.payload)
        .join(HarvestRun, HarvestRun.id == SourceRecord.harvest_run_id)
        .where(
            SourceRecord.source == SOURCE,
            SourceRecord.entity_type == AUTHOR_ENTITY,
            HarvestRun.institution_id == institution_id,
        )
        .order_by(SourceRecord.source_pk, SourceRecord.harvested_at.desc(), SourceRecord.id.desc())
    )
    out: dict[str, str | None] = {}
    for pk, payload in (await session.execute(stmt)).all():
        out.setdefault(pk, bare_orcid(payload.get("orcid")))
    return out


async def sweep_author_works(
    client, session: AsyncSession, institution, a_ids: list[str]
) -> dict[str, Any]:
    """Budget-capped per-author works enrichment: OpenAlex works of the
    resolved authors, 50 pipe-OR ids per keyed call (the ut-metadata
    gap-fetch pattern). Lands in the works_stats store (filter_set
    author-sweep) so the openalex_works projection folds them in — this
    covers authors whose OpenAlex profile lacks the institution."""
    settings = get_settings()
    budget = settings.openalex_author_sweep_max_authors
    stats: dict[str, Any] = {"queried_authors": 0, "calls": 0, "works_seen": 0}
    if budget <= 0 or not a_ids:
        return stats
    ids = sorted({i for i in a_ids if i})[:budget]
    stats["queried_authors"] = len(ids)
    window_from = f"{institution.data_window_start}-01-01"
    ingest = IngestSession(session)

    async def commit_page(_page: int, _cursor: str | None) -> None:
        await ingest.commit()

    for n in range(0, len(ids), BATCH_SIZE):
        batch = ids[n : n + BATCH_SIZE]
        stats["calls"] += 1
        await ingest.start_run(
            SOURCE,
            "works_stats",
            f"{SWEEP_FILTER_PREFIX}:{n // BATCH_SIZE}",
            {"batch": batch, "from": window_from},
            institution_id=institution.id,
        )
        filters: dict[str, Any] = {
            "authorships.author.id": "|".join(batch),
            "from_publication_date": window_from,
            **(
                {"to_publication_date": f"{institution.data_window_end}-12-31"}
                if institution.data_window_end is not None
                else {}
            ),
        }
        async for item in client.works.iterate(
            page_size=PER_PAGE, filters=filters, on_page=commit_page
        ):
            payload = (
                item
                if isinstance(item, dict)
                else (item.model_dump(mode="json") if hasattr(item, "model_dump") else None)
            )
            if not payload or not payload.get("id"):
                await ingest.record_parse_failure(
                    {"source_pk": None, "reason": "work parse failure"}
                )
                continue
            await ingest.ingest_record(openalex_id_to_pk(payload.get("id")), payload)
            stats["works_seen"] += 1
        await ingest.finish_run("completed", {})
        await session.commit()
    return stats


def _weak_affiliation_rung(
    institution_id: int,
    by_work: dict[str, list[WorkPureAuthor]],
    doi_of_work: dict[str, str | None],
    by_doi: dict[str, list[dict[str, Any]]],
    aid_orcids: dict[str, set[str]],
    aid_names: dict[str, Counter],
    person_orcid: dict[str, str],
    person_name: dict[str, str],
    *,
    admitted_uuids: set[str],
    confirmed_uuids: set[str],
    claimed_ids: dict[str, set[str]],
    proposed: set[tuple[str, str]],
) -> dict[str, Any]:
    """Identity admission for org-dead-end corpus members (owner decision
    2026-10-31). Pure's OAI orgunits set serves no parent edges for
    sub-departments, so a person whose every authorship edge and profile
    affiliation lands on such flat orgs never passes tree.resolves — they
    never enter the cascade and stay off the author browse entirely (43
    live authors as of 2026-10-31; a non-OAI hierarchy source remains the
    full fix). Admit a confirmed id when the person's own works bind
    exactly one external id through BOTH deterministic name evidence
    (orcid-exact / name-exact / name-initials — family-unique and fuzzy
    stay out: 55% of edges carry empty affiliations, and soft name
    evidence on unaffiliated works is the namesake trap the org gate
    exists for) and a single consistent ORCID: the set of orcids on the
    person's matched entries (plus their profile orcid) must be exactly
    one value and equal the id's global orcid set in our store — impostor
    namesakes carry their own orcid, and a merged OpenAlex profile fails
    the equality. Persons without any orcid evidence stay unadmitted.
    An extra matched id is a fragment twin (rides along confirmed) when
    its global orcid set is empty or the same human's and it never sits
    on one authorship list with the primary; carrying a different orcid
    it is a namesake match and the person stays out. Two same-name
    persons selecting the same id cancel out."""
    rows_out: list[dict[str, Any]] = []
    skipped: Counter = Counter()
    strong_methods = (METHOD_ORCID, METHOD_NAME, METHOD_INITIALS)

    works_by_person: dict[str, set[str]] = defaultdict(set)
    for work_uuid, edge_rows in by_work.items():
        for row in edge_rows:
            works_by_person[row.person_uuid].add(work_uuid)

    for uuid in sorted(works_by_person):
        if uuid in admitted_uuids or uuid in confirmed_uuids:
            continue
        weak_outcomes: list[tuple[ExtEntry, str, str]] = []
        work_id_sets: dict[str, set[str]] = {}
        for work_uuid in sorted(works_by_person[uuid]):
            doi = doi_of_work.get(work_uuid)
            if not doi:
                continue
            entries = openalex_entries(by_doi.get(doi, []))
            if not entries:
                continue
            work_id_sets[work_uuid] = {e.id for e in entries if e.id}
            edge = next(r for r in by_work[work_uuid] if r.person_uuid == uuid)
            peers = {
                decompose_parts(r.first_names or "", r.family_names or "").family_only
                for r in by_work[work_uuid]
                if r.person_uuid != uuid
            }
            author = PureAuthor(uuid, edge.first_names or "", edge.family_names or "")
            entry, method = match(author, entries, person_orcid.get(uuid), peers)
            if entry is None or not entry.id or method not in strong_methods:
                continue
            weak_outcomes.append((entry, method, work_uuid))
        if not weak_outcomes:
            continue
        agg = aggregate([(e, m) for e, m, _w in weak_outcomes])
        if agg is None:
            continue
        primary, method, _conflicts = agg
        if not primary.id:
            continue
        claimed_elsewhere = claimed_ids.get(primary.id, set()) - {uuid}
        if claimed_elsewhere:
            skipped["id_claimed_elsewhere"] += 1
            continue
        person_orcids = {e.orcid for e, _m, _w in weak_outcomes if e.orcid}
        if person_orcid.get(uuid):
            person_orcids.add(person_orcid[uuid])
        if not person_orcids:
            skipped["orcid_missing"] += 1
            continue
        if aid_orcids.get(primary.id, set()) != person_orcids:
            skipped["orcid_mismatch"] += 1
            continue
        # OpenAlex profile fragmentation is the norm in this population
        # (van Doorn: 50 works name-match A5010733081, one work a bare
        # fragment). An extra matched id must not veto an otherwise
        # perfect binding: it is a twin when its own global orcid set is
        # empty or the same human's (⊆ person_orcids) and it never sits
        # on one authorship list with the primary (the cascade's twin
        # rule). A fragment carrying a DIFFERENT orcid is a namesake
        # whose profile absorbed one of the person's authorships — OpenAlex
        # split/merge noise; it does not veto when the orcid-perfect
        # primary is dominant (≥3 works and strictly more votes), only
        # lands in evidence.competing_ids. A person whose contradictory
        # evidence rivals the primary stays out.
        twins: list[ExtEntry] = []
        competing: list[str] = []
        other_ids = {e.id for e, _m, _w in weak_outcomes} - {primary.id}
        n_primary = len({w for e, _m, w in weak_outcomes if e.id == primary.id})
        vetoed = False
        for other in sorted(other_ids):
            other_orcids = aid_orcids.get(other, set())
            if other_orcids - person_orcids:
                competing.append(other)
                continue
            if claimed_ids.get(other, set()) - {uuid}:
                skipped["id_claimed_elsewhere"] += 1
                vetoed = True
                break
            co_occur = any(other in ids and primary.id in ids for ids in work_id_sets.values())
            if not co_occur:
                twins.append(next(e for e, _m, _w in weak_outcomes if e.id == other))
        if not vetoed and competing:
            n_competing = max(
                len({w for e, _m, w in weak_outcomes if e.id == c}) for c in competing
            )
            if n_primary < 3 or n_primary <= n_competing:
                skipped["orcid_contradiction"] += 1
                vetoed = True
        if vetoed:
            continue
        rows_out.append(
            {
                "institution_id": institution_id,
                "author_pure_uuid": uuid,
                "source": SOURCE,
                "external_id": primary.id,
                "status": "confirmed",
                "method": method,
                "confidence": CONFIDENCE.get(method),
                "n_works": len({w for e, _m, w in weak_outcomes if e.id == primary.id}),
                "orcid_corroborated": True,
                "evidence": {
                    "weak_affiliation": True,
                    "author_name": person_name.get(uuid),
                    "orcids": sorted(person_orcids),
                    "names": aid_names.get(primary.id, Counter()).most_common(3),
                    **({"competing_ids": sorted(competing)} if competing else {}),
                },
            }
        )
        proposed.add((uuid, primary.id))
        # Orcid-less / orcid-consistent fragments ride along as confirmed
        # twins (the cascade's fragmentation-twin rules, owner decision
        # 2026-10-31); n_works counts the person's weak-matched works
        # where the fragment was the matched id.
        for twin in twins:
            rows_out.append(
                {
                    "institution_id": institution_id,
                    "author_pure_uuid": uuid,
                    "source": SOURCE,
                    "external_id": twin.id,
                    "status": "confirmed",
                    "method": "fragmentation",
                    "confidence": CONFIDENCE.get(METHOD_FUZZY),
                    "n_works": len({w for e, _m, w in weak_outcomes if e.id == twin.id}),
                    "orcid_corroborated": False,
                    "evidence": {
                        "weak_affiliation": True,
                        "twin_of": primary.id,
                        "author_name": person_name.get(uuid),
                        "orcids": sorted(aid_orcids.get(twin.id, set())),
                        "names": aid_names.get(twin.id, Counter()).most_common(3),
                    },
                }
            )
            proposed.add((uuid, twin.id))

    # Same id chosen by two different unaffiliated persons = an OpenAlex
    # namesake merge; admit neither.
    by_id: dict[str, set[str]] = defaultdict(set)
    for row in rows_out:
        by_id[row["external_id"]].add(row["author_pure_uuid"])
    contested = [r for r in rows_out if len(by_id[r["external_id"]]) > 1]
    if contested:
        skipped["namesake_contested"] += len(contested)
        rows_out = [r for r in rows_out if len(by_id[r["external_id"]]) == 1]
    methods = Counter(r["method"] for r in rows_out)

    return {
        "rows": rows_out,
        "stats": {
            "admitted": len(rows_out),
            "methods": dict(methods),
            **{f"skipped_{k}": v for k, v in skipped.items()},
        },
    }


async def resolve_author_ids(
    session: AsyncSession,
    institution,
    *,
    run_sweeps: bool = True,
    listing_limit: int | None = None,
) -> dict[str, Any]:
    """Full resolution pass for one institution. run_sweeps=False (tests)
    resolves against store contents only."""
    started = time.monotonic()
    stats: dict[str, Any] = {}
    tree = await load_org_tree(session, institution)
    stats["root_resolved"] = tree.root is not None

    person_orcid: dict[str, str] = {}
    person_name: dict[str, str] = {}
    profile_orgs: dict[str, list[str]] = {}
    for row in (
        await session.execute(select(PurePerson).where(PurePerson.institution_id == institution.id))
    ).scalars():
        if row.orcid:
            person_orcid[row.uuid] = row.orcid
        if row.name:
            person_name.setdefault(row.uuid, row.name)
        # profile-affiliation arm: the CERIF payload's affiliation org uuids
        profile_orgs[row.uuid] = [
            aff.get("affiliation_id")
            for aff in (row.payload.get("cerif") or {}).get("affiliations") or []
            if isinstance(aff, dict) and aff.get("affiliation_id")
        ]

    # work_pure_authors grouped by work (work-entry spellings kept).
    by_work: dict[str, list[WorkPureAuthor]] = defaultdict(list)
    for row in (
        await session.execute(
            select(WorkPureAuthor).where(WorkPureAuthor.institution_id == institution.id)
        )
    ).scalars():
        by_work[row.work_pure_uuid].append(row)

    # Local work DOIs (matches the cascade's work-keyed design: no DOI,
    # no OpenAlex counterpart — authorship candidates ride the works that
    # carry one; the per-author sweep covers the rest).
    doi_of_work: dict[str, str | None] = {}
    for uuid, doi in (
        await session.execute(
            select(Work.pure_uuid, Work.doi_normalized).where(
                Work.institution_id == institution.id, Work.retired_at.is_(None)
            )
        )
    ).all():
        doi_of_work[uuid] = doi

    # OpenAlex works store: authorships combined per DOI (merged profiles
    # can carry one publication under two W-ids), plus the corroboration
    # indexes (A-id -> orcids / display names). Column-select only the two
    # fields the cascade needs: full ORM rows (title/year/...) plus the
    # identity map OOM-killed the live run at 14.6 GB.
    by_doi: dict[str, list[dict[str, Any]]] = defaultdict(list)
    aid_orcids: dict[str, set[str]] = defaultdict(set)
    aid_names: dict[str, Counter] = defaultdict(Counter)
    for doi_normalized, authorships in (
        await session.execute(
            select(OpenalexWork.doi_normalized, OpenalexWork.authorships).where(
                OpenalexWork.institution_id == institution.id
            )
        )
    ).all():
        authorships = authorships or []
        if doi_normalized:
            by_doi[doi_normalized].extend(authorships)
        for sh in authorships:
            if isinstance(sh, dict) and sh.get("a"):
                if sh.get("o"):
                    aid_orcids[sh["a"]].add(sh["o"])
                if sh.get("n"):
                    aid_names[sh["a"]][sh["n"]] += 1

    listing_orcids = await _listing_orcids(session, institution.id)
    for aid, orcid in listing_orcids.items():
        if orcid:
            aid_orcids[aid].add(orcid)
    aid_orcids_oa: dict[str, set[str]] = defaultdict(set)
    aid_names_oa: dict[str, Counter] = defaultdict(Counter)

    # OpenAIRE work store: the same work-anchored cascade against a second
    # external corpus (authorship names arrive inverted "Family, First";
    # decompose_name parses both orders). Ids are OpenAIRE person keys —
    # mostly orcid-derived — stored as separate source='openaire'
    # identity rows so the namespace never mixes with OpenAlex A-ids.
    by_doi_oa: dict[str, list[ExtEntry]] = defaultdict(list)
    oa_dois = sorted({d for d in doi_of_work.values() if d})
    for start in range(0, len(oa_dois), 20000):
        chunk = oa_dois[start : start + 20000]
        doi_expr = func.lower(SourceRecord.payload.op("->>")("doi"))
        # Project just the authors array server-side: fetching whole payloads
        # decoded 500k+ OpenAIRE results in Python and OOM-killed the live run.
        for doi, authors in (
            await session.execute(
                select(
                    doi_expr,
                    SourceRecord.payload.op("->")("authors").label("authors"),
                ).where(
                    SourceRecord.source == "openaire",
                    SourceRecord.entity_type == "work",
                    doi_expr.in_(chunk),
                )
            )
        ).all():
            for a in authors or []:
                if not isinstance(a, dict):
                    continue
                name = a.get("fullName") or " ".join(
                    p for p in (a.get("name"), a.get("surname")) if p
                )
                pid = a.get("pid")
                inner = pid.get("id") if isinstance(pid, dict) else None
                orcid = bare_orcid(inner.get("value") if isinstance(inner, dict) else None)
                entry_id = (a.get("id") or "").rsplit("/", 1)[-1] or None
                if not name and not orcid:
                    continue
                if entry_id:
                    if orcid:
                        aid_orcids_oa[entry_id].add(orcid)
                    if name:
                        aid_names_oa[entry_id][name] += 1
                by_doi_oa[doi].append(ExtEntry(entry_id, name or None, orcid))

    # ── the work-anchored cascade ────────────────────────────────────────
    outcomes: dict[str, dict[str, list[tuple[Any, str]]]] = {
        SOURCE: defaultdict(list),
        SOURCE_OPENAIRE: defaultdict(list),
    }
    id_works: dict[str, dict[str, dict[str, set[str]]]] = {
        SOURCE: defaultdict(lambda: defaultdict(set)),
        SOURCE_OPENAIRE: defaultdict(lambda: defaultdict(set)),
    }
    work_ids: dict[str, dict[str, list[set[str]]]] = {
        SOURCE: defaultdict(list),
        SOURCE_OPENAIRE: defaultdict(list),
    }
    works = 0
    works_matched = 0
    works_without_doi = 0
    works_without_openalex = 0
    for work_uuid, rows in sorted(by_work.items()):
        doi = doi_of_work.get(work_uuid)
        oa_authorships = by_doi.get(doi or "", [])
        if doi is None:
            works_without_doi += 1
            continue
        if not oa_authorships:
            works_without_openalex += 1
            continue
        # Org-tree filter (the affiliation rule): work-level affiliations
        # close on the institution root, or the person's profile does (the
        # two pure arms of the roster canon). The CERIF-flattened
        # primary-affiliation fallback already rode the edges.
        affiliated = [
            row
            for row in rows
            if tree.resolves(list(row.affiliations or []))
            or tree.resolves(profile_orgs.get(row.person_uuid, []))
        ]
        if not affiliated:
            continue
        works += 1
        authors = [
            PureAuthor(
                row.person_uuid,
                row.first_names or "",
                row.family_names or "",
            )
            for row in affiliated
        ]
        entries = openalex_entries(oa_authorships)
        if not entries:
            continue
        works_matched += 1
        fams = [decompose_parts(a.first, a.family).family_only for a in authors]
        ext_lists = (
            (SOURCE, entries),
            (SOURCE_OPENAIRE, by_doi_oa.get(doi, [])),
        )
        for src, ext in ext_lists:
            if not ext:
                continue
            for i, a in enumerate(authors):
                peer = {f for j, f in enumerate(fams) if j != i}
                entry, method = match(a, ext, person_orcid.get(a.uuid), peer)
                if entry is None:
                    continue
                outcomes[src][a.uuid].append((entry, method))
                # every id present on a work the person matched on: the
                # twin gate checks primary/alternate co-occurrence here
                work_ids[src][a.uuid].append({e.id for e in ext if e.id})
                if entry.id:
                    id_works[src][a.uuid][entry.id].add(work_uuid)

    # ── aggregation + corroboration + identity rows ─────────────────────
    updates: list[dict[str, Any]] = []
    arm_evidence = {
        SOURCE: (aid_orcids, aid_names),
        SOURCE_OPENAIRE: (aid_orcids_oa, aid_names_oa),
    }
    corroborated_alts = 0
    per_arm: dict[str, dict[str, Any]] = {}
    for src, (arm_orcids, arm_names) in arm_evidence.items():
        matched = 0
        methods: Counter = Counter()
        conflicted_authors = 0
        rows = 0
        for uuid, outs in sorted(outcomes[src].items()):
            agg = aggregate(outs)
            if agg is None:
                continue
            primary, method, conflicts = agg
            matched += 1
            methods[method] += 1
            if conflicts:
                conflicted_authors += 1
            porcid = person_orcid.get(uuid)
            ids_seen = {e.id for e, _m in outs if e.id}
            alternates = sorted(ids_seen - {primary.id}) if primary.id else sorted(ids_seen)

            if primary.id:
                primary_corroborated = bool(porcid) and porcid in arm_orcids.get(primary.id, set())
                updates.append(
                    {
                        "institution_id": institution.id,
                        "author_pure_uuid": uuid,
                        "source": src,
                        "external_id": primary.id,
                        "status": _derived_status(method, conflicts),
                        "method": method,
                        "confidence": CONFIDENCE.get(method),
                        "n_works": len(id_works[src][uuid][primary.id]),
                        "orcid_corroborated": primary_corroborated,
                        "evidence": {
                            "conflicts": conflicts,
                            "author_name": person_name.get(uuid),
                            "names": arm_names.get(primary.id, Counter()).most_common(3),
                        },
                    }
                )
            for aid in alternates:
                corroborated = bool(porcid) and porcid in arm_orcids.get(aid, set())
                if corroborated:
                    corroborated_alts += 1
                # Zero-conflict twins ride along (owner decision 2026-10-31):
                # an alternate is a twin of the person — not a competing
                # namesake — when its id never appears on a work where the
                # primary id also appears (one human is never two authorships
                # of one work, modulo merge artifacts), and the ORCID evidence
                # across primary and alternates names at most one human. A
                # co-occurring or orcid-contradicted id is a competitor and
                # stays a candidate for the review queue; rejects remain the
                # correction path.
                co_occur = primary.id is not None and any(
                    primary.id in idset and aid in idset for idset in work_ids[src].get(uuid, [])
                )
                ids_all = ([primary.id] if primary.id else []) + alternates
                seen_orcids = (
                    set().union(*(arm_orcids.get(i, set()) for i in ids_all)) if ids_all else set()
                )
                orcid_consistent = len(seen_orcids) <= 1
                is_twin = not co_occur and orcid_consistent
                updates.append(
                    {
                        "institution_id": institution.id,
                        "author_pure_uuid": uuid,
                        "source": src,
                        "external_id": aid,
                        "status": "confirmed" if is_twin else "candidate",
                        "method": "orcid-corroboration" if corroborated else "fragmentation",
                        "confidence": 0.9 if corroborated else CONFIDENCE.get(METHOD_FUZZY),
                        "n_works": len(id_works[src][uuid][aid]),
                        "orcid_corroborated": corroborated,
                        "evidence": {
                            "primary_id": primary.id,
                            "orcids_seen": sorted(arm_orcids.get(aid, set()))[:3],
                            "names": arm_names.get(aid, Counter()).most_common(3),
                            "author_name": person_name.get(uuid),
                            **({"co_occurs_with_primary": True} if co_occur else {}),
                        },
                    }
                )
        per_arm[src] = {
            "matched": matched,
            "methods": dict(methods),
            "conflicted_authors": conflicted_authors,
        }

    # ── profile-orcid ↔ author-listing join ──────────────────────────────
    # Deterministic identity join, no name matching involved: an OpenAlex
    # author profile that carries the pure person's own ORCID is that
    # person (ut-metadata admitted its roster this way). Only authors with
    # no confirmed OpenAlex row from the work-anchored cascade are
    # extended — the work-level pass stays the primary evidence.
    listing_by_orcid = {orcid: aid for aid, orcid in listing_orcids.items() if orcid}
    confirmed_uuids = {
        r["author_pure_uuid"]
        for r in updates
        if r["source"] == SOURCE and r["status"] == "confirmed"
    }
    proposed = {(r["author_pure_uuid"], r["external_id"]) for r in updates}
    listing_rows = 0
    for uuid, porcid in sorted(person_orcid.items()):
        if uuid in confirmed_uuids:
            continue
        aid = listing_by_orcid.get(porcid)
        if not aid or (uuid, aid) in proposed:
            continue
        updates.append(
            {
                "institution_id": institution.id,
                "author_pure_uuid": uuid,
                "source": SOURCE,
                "external_id": aid,
                "status": "confirmed",
                "method": METHOD_ORCID,
                "confidence": CONFIDENCE[METHOD_ORCID],
                "n_works": 0,
                "orcid_corroborated": True,
                "evidence": {
                    "source": "author-listing",
                    "author_name": person_name.get(uuid),
                },
            }
        )
        proposed.add((uuid, aid))
        confirmed_uuids.add(uuid)
        listing_rows += 1
    per_arm["orcid-listing"] = {"rows": listing_rows}

    # ── weak-affiliation rung (org-dead-end recovery) ────────────────────
    # Every id already bound by the cascade/listing rows (primaries AND
    # fragmentation twins) blocks re-binding to another person.
    claimed: dict[str, set[str]] = defaultdict(set)
    for r in updates:
        claimed[r["external_id"]].add(r["author_pure_uuid"])
    weak = _weak_affiliation_rung(
        institution.id,
        by_work,
        doi_of_work,
        by_doi,
        aid_orcids,
        aid_names,
        person_orcid,
        person_name,
        admitted_uuids={u for src in outcomes for u in outcomes[src]},
        confirmed_uuids=confirmed_uuids,
        claimed_ids=claimed,
        proposed=proposed,
    )
    updates.extend(weak["rows"])
    per_arm["weak-affiliation"] = weak["stats"]

    # Identities without an external id are noise (nothing collectable).
    updates = [u for u in updates if u["external_id"]]
    candidate_rows = sum(1 for u in updates if u["status"] == "candidate")
    confirmed_rows = len(updates) - candidate_rows
    # asyncpg caps one statement at 32767 bound params; each row binds 10.
    for start in range(0, len(updates), 2000):
        chunk = updates[start : start + 2000]
        stmt = pg_insert(AuthorIdentity).values(chunk)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    AuthorIdentity.institution_id,
                    AuthorIdentity.author_pure_uuid,
                    AuthorIdentity.source,
                    AuthorIdentity.external_id,
                ],
                set_={
                    "method": stmt.excluded.method,
                    "confidence": stmt.excluded.confidence,
                    "n_works": stmt.excluded.n_works,
                    "orcid_corroborated": stmt.excluded.orcid_corroborated,
                    "evidence": stmt.excluded.evidence,
                    # Admin decisions are sticky: rejected stays rejected,
                    # confirmed is never silently demoted (additive-only
                    # spirit); only candidates follow new evidence.
                    "status": case(
                        (AuthorIdentity.status == "candidate", stmt.excluded.status),
                        else_=AuthorIdentity.status,
                    ),
                    "updated_at": func.now(),
                },
            )
        )

    # ── sweeps + projection refresh ──────────────────────────────────────
    sweep_stats: dict[str, Any] = {}
    if run_sweeps:
        from aletheca import AlethecaClient

        settings = get_settings()
        client_kwargs: dict[str, Any] = {}
        if settings.openalex_api_key:
            client_kwargs["api_key"] = settings.openalex_api_key
        async with AlethecaClient(**client_kwargs) as client:
            sweep_stats["listing"] = await sweep_openalex_authors(
                client, session, institution, limit=listing_limit
            )
            confirmed_ids = [
                row.external_id
                for row in (
                    await session.execute(
                        select(AuthorIdentity.external_id)
                        .where(
                            AuthorIdentity.institution_id == institution.id,
                            AuthorIdentity.source == SOURCE,
                            AuthorIdentity.status == "confirmed",
                        )
                        .distinct()
                    )
                ).all()
            ]
            sweep_stats["author_works"] = await sweep_author_works(
                client, session, institution, confirmed_ids
            )
        from .openalex_works import rebuild_openalex_works

        sweep_stats["projection"] = await rebuild_openalex_works(session, institution)
    # commit unconditionally: without the sweeps the function is the only
    # writer, and an uncommitted identity upsert vanishes with the session
    # (a --no-sweeps re-run must persist its pass like any other).
    await session.commit()

    stats.update(
        {
            "works": works,
            "works_matched": works_matched,
            "works_without_doi": works_without_doi,
            "works_without_openalex": works_without_openalex,
            "authors_walked": len(outcomes[SOURCE]),
            # openalex arm stays the headline keys (job output compat)
            "matched": per_arm[SOURCE]["matched"],
            "methods": per_arm[SOURCE]["methods"],
            "conflicted_authors": per_arm[SOURCE]["conflicted_authors"],
            "identity_rows": len(updates),
            "confirmed_rows": confirmed_rows,
            "candidate_rows": candidate_rows,
            "corroborated_alts": corroborated_alts,
            "openaire": per_arm[SOURCE_OPENAIRE],
            "orcid_listing": per_arm["orcid-listing"]["rows"],
            "weak_affiliation": per_arm["weak-affiliation"],
            "sweeps": sweep_stats,
            "seconds": round(time.monotonic() - started, 1),
        }
    )
    logger.info("author ids[%s]: %s", institution.code, stats)
    return stats
