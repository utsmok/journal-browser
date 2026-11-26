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

Runs with no DSN; the only API spend is the budget-capped per-author
works enrichment (50 batched A-ids per keyed call, stopping cleanly
below the JB_OPENALEX_RESERVE_USD reserve) covering authors whose
OpenAlex profile lacks the institution. The author listing sweep is
retired: author profiles are
gathered from stored work authorships, with paced $0 single-entity
GETs filling gaps.

Memory: the pass never holds a work-level store. It walks the local DOIs
in slices, reading the cascade's and the weak-affiliation rung's evidence
off the same per-slice stores, and streams the OpenAlex works store once,
indexing only the ids someone matched; identity rows are upserted a
chunk at a time. The one-shot run loaded four whole tables first and the
2 GB scheduler killed it before any work started.
"""

import logging
import time
from collections import Counter, defaultdict
from operator import itemgetter
from typing import Any

from sqlalchemy import case, distinct, exists, func, or_, select, text
from sqlalchemy.dialects.postgresql import distinct_on
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
from .common import openalex_budget_ok, paced_single_gets, require_openalex_key
from .openalex_journals import openalex_id_to_pk, resolve_institution_openalex_id
from .org_closure import load_org_tree

logger = logging.getLogger(__name__)

SOURCE = "openalex"
SOURCE_OPENAIRE = "openaire"


def openaire_author_orcid(author: dict[str, Any]) -> str | None:
    """Bare ORCID from one OpenAIRE CERIF author entry, confirmed only.

    Graph v12 (2026-11) adds coauthorship-inferred identifiers marked
    scheme=orcid_pending; those must never drive the orcid-exact rung, so
    only confirmed orcid-scheme pids (and scheme-less legacy pids) count."""
    pid = author.get("pid")
    inner = pid.get("id") if isinstance(pid, dict) else None
    if not isinstance(inner, dict):
        return None
    orcid = bare_orcid(inner.get("value"))
    if not orcid:
        return None
    if str(inner.get("scheme") or "").lower() == "orcid_pending":
        return None
    return orcid


AUTHOR_ENTITY = "authors"
SWEEP_FILTER_PREFIX = "author-sweep"
BATCH_SIZE = 50  # OpenAlex pipe-OR ceiling (ut-metadata gap-fetch size)
PER_PAGE = 100  # OpenAlex documented per_page maximum

#: Local DOIs per OpenAIRE lookup. The store has no index on the payload's
#: DOI, so every lookup scans the OpenAIRE work rows: this is the slice
#: the one-shot run used, which keeps the number of scans, and each
#: scan's row set and order, as they were. The slice also fixes the order
#: of tied names in the evidence (Counter.most_common keeps first-seen
#: order within the slice): 7000-DOI slices wrote the same 46k rows with
#: 193 evidences reordered, so keep this value to match earlier runs.
DOI_SLICE = 20000
#: Values per indexed IN () lookup: asyncpg caps a statement at 32767
#: bound parameters.
LOOKUP_CHUNK = 5000
#: Author profiles fetched (and held) per gather round before they are
#: stored and released. The one-shot gather held every todo profile.
GATHER_CHUNK = 500
#: Rows per streamed partition of the works store.
STREAM_PARTITION = 200
#: Identity rows per upsert: asyncpg caps one statement at 32767 bound
#: params; each row binds 10.
UPSERT_CHUNK = 2000

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


async def gather_openalex_authors(
    client, session: AsyncSession, institution, limit: int | None = None
) -> dict[str, Any]:
    """Land author profiles for the authors cited by the institution's
    stored work payloads — local extraction + paced free single-entity
    GETs; no listing sweep.

    Work authorships carry the author id (and orcid) for exactly the
    authors the resolution cascade needs. Authors already in
    source_records keep their stored profile; gaps fetch full profiles,
    falling back to authorship stubs ({id, orcid, display_name}) on 404
    or parse failure so orcid corroboration never loses recall. Costs no
    credits (the affiliations.institution.ror listing it replaces did,
    and 429-crashed at a zero budget)."""
    inst_id = await resolve_institution_openalex_id(client, session, institution)
    listing = await session.stream(
        text(
            "SELECT DISTINCT ON (COALESCE(a->>'id', a->'author'->>'id'))"
            " COALESCE(a->>'id', a->'author'->>'id') AS aid_url,"
            " COALESCE(a->'author'->>'orcid', a->>'orcid') AS orcid,"
            " COALESCE(a->>'display_name', a->'author'->>'display_name') AS name"
            " FROM source_records sr"
            " JOIN harvest_runs hr ON hr.id = sr.harvest_run_id"
            " CROSS JOIN LATERAL jsonb_array_elements(sr.payload->'authorships') a"
            " WHERE sr.source = :source AND sr.entity_type = :entity"
            " AND hr.institution_id = :iid"
            " AND jsonb_typeof(sr.payload->'authorships') = 'array'"
            " AND jsonb_typeof(a->'author') = 'object'"
            " AND a->'author'->>'id' IS NOT NULL"
        ).execution_options(stream_results=True, max_row_buffer=STREAM_PARTITION),
        {"source": SOURCE, "entity": "work", "iid": institution.id},
    )
    authorship_by_url: dict[str, tuple[str | None, Any]] = {}
    async for partition in listing.partitions(STREAM_PARTITION):
        for r in partition:
            authorship_by_url[r.aid_url] = (bare_orcid(r.orcid), r.name)
    known = {
        pk
        for (pk,) in (
            await session.execute(
                select(SourceRecord.source_pk)
                .join(HarvestRun, HarvestRun.id == SourceRecord.harvest_run_id)
                .where(
                    SourceRecord.source == SOURCE,
                    SourceRecord.entity_type == AUTHOR_ENTITY,
                    HarvestRun.institution_id == institution.id,
                )
                .distinct()
            )
        ).all()
    }
    todo = sorted({u for u in authorship_by_url if openalex_id_to_pk(u) not in known})
    if limit is not None:
        todo = todo[:limit]
    stats: dict[str, Any] = {
        "authors_in_works": len(authorship_by_url),
        "already_stored": len(authorship_by_url) - len(todo),
        "todo": len(todo),
        "fetched": 0,
        "stubs": 0,
        "failed": 0,
    }
    ingest = IngestSession(session)
    await ingest.start_run(
        SOURCE,
        AUTHOR_ENTITY,
        "authorships-delta",
        {"route": "delta", "institution_openalex_id": inst_id, "page_size": PER_PAGE},
        institution_id=institution.id,
    )
    if not todo:
        await ingest.finish_run("completed", dict(stats))
        await session.commit()
        return stats
    # One batch of profiles in memory at a time: each batch is stored and
    # committed before the next is fetched.
    for start in range(0, len(todo), GATHER_CHUNK):
        batch = todo[start : start + GATHER_CHUNK]
        payloads, failed = await paced_single_gets(client.authors.get, batch)
        stats["failed"] += len(failed)
        if failed:
            logger.warning(
                "author gather: %d of %d lookups failed in the batch at %d, e.g. %s",
                len(failed),
                len(batch),
                start,
                sorted(failed)[:5],
            )
        for url, entity in payloads.items():
            payload = entity.model_dump(mode="json") if entity is not None else None
            if payload and payload.get("id"):
                await ingest.ingest_record(openalex_id_to_pk(payload.get("id")), payload)
                stats["fetched"] += 1
                continue
            # 404 / parse failure: land the authorship stub so the cascade's
            # orcid corroboration keeps working for this author.
            orcid, name = authorship_by_url[url]
            await ingest.ingest_record(
                openalex_id_to_pk(url),
                {"id": url, "orcid": orcid, "display_name": name},
            )
            stats["stubs"] += 1
        await ingest.commit()
    await ingest.finish_run("completed", stats)
    await session.commit()
    return stats


async def _listing_orcids(session: AsyncSession, institution_id: int) -> dict[str, str | None]:
    """Latest stored author listing ORCID per bare A-id (corroboration
    source beyond work authorships). Projects only payload->>'orcid' with
    server-side DISTINCT ON so hundreds of MB of full author payloads
    never cross the wire."""
    stmt = (
        select(
            SourceRecord.source_pk,
            SourceRecord.payload.op("->>")("orcid"),
        )
        .ext(distinct_on(SourceRecord.source_pk))
        .join(HarvestRun, HarvestRun.id == SourceRecord.harvest_run_id)
        .where(
            SourceRecord.source == SOURCE,
            SourceRecord.entity_type == AUTHOR_ENTITY,
            HarvestRun.institution_id == institution_id,
        )
        .order_by(
            SourceRecord.source_pk,
            SourceRecord.harvested_at.desc(),
            SourceRecord.id.desc(),
        )
    )
    return {pk: bare_orcid(raw_orcid) for pk, raw_orcid in (await session.execute(stmt)).all()}


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
    stats: dict[str, Any] = {
        "queried_authors": 0,
        "calls": 0,
        "works_seen": 0,
        "skipped": None,
    }
    if budget <= 0 or not a_ids:
        return stats
    if not await openalex_budget_ok("sweep_author_works", stats):
        # Pipe-OR works filters are list-class and cost credits; stop below
        # the reserve instead of 429ing through the rest of the resolve run.
        stats["skipped"] = "openalex budget below the reserve (resets 00:00 UTC)"
        logger.info("sweep_author_works skipped: %s", stats["skipped"])
        return stats
    # Cursor sweeps paginate only with a key; keyless, the sweep would
    # land one page and finish 'completed' with partial data.
    require_openalex_key("sweep_author_works")
    ids = sorted({i for i in a_ids if i})[:budget]
    stats["queried_authors"] = len(ids)
    window_from = f"{institution.data_window_start}-01-01"
    ingest = IngestSession(session)

    async def commit_page(_page: int, _cursor: str | None) -> None:
        await ingest.commit()

    for n in range(0, len(ids), BATCH_SIZE):
        batch = ids[n : n + BATCH_SIZE]
        if not await openalex_budget_ok("sweep_author_works", stats):
            break
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
        parse_failures: list[tuple[dict[str, Any], Exception]] = []
        async for item in client.works.iterate(
            page_size=PER_PAGE,
            filters=filters,
            on_page=commit_page,
            on_error="skip",
            failures=parse_failures,
        ):
            payload = item.model_dump(mode="json")
            if not payload.get("id"):
                await ingest.record_parse_failure(
                    {"source_pk": None, "reason": "work parse failure"}
                )
                continue
            await ingest.ingest_record(openalex_id_to_pk(payload.get("id")), payload)
            stats["works_seen"] += 1
        for raw, exc in parse_failures:
            await ingest.record_parse_failure({"source_pk": raw.get("id"), "reason": str(exc)})
        await ingest.finish_run("completed", {})
        await session.commit()
    return stats


#: Match rungs the weak-affiliation rung admits on. family-unique and fuzzy
#: stay out: 55% of edges carry empty affiliations, and soft name evidence
#: on unaffiliated works is the namesake trap the org gate exists for.
_STRONG_METHODS = (METHOD_ORCID, METHOD_NAME, METHOD_INITIALS)


def _weak_evidence(
    work_uuid: str,
    rows: list[Any],
    entries: list[ExtEntry],
    person_orcid: dict[str, str],
    id_sets: dict[str, dict[str, frozenset[str]]],
    matches: dict[str, list[tuple[str, ExtEntry, str]]],
) -> None:
    """Weak-affiliation evidence on one work that has OpenAlex entries, for
    every author edge of it: the ids on the work (the twin gate reads them
    whatever the match came to) and the matches of the deterministic name
    rungs. Who is admitted is known only after the last slice, so every
    author is recorded here and the cascade's persons are dropped
    afterwards."""
    ids = frozenset(e.id for e in entries if e.id)
    fams = [decompose_parts(r.first_names or "", r.family_names or "").family_only for r in rows]
    for i, row in enumerate(rows):
        id_sets[row.person_uuid][work_uuid] = ids
        author = PureAuthor(row.person_uuid, row.first_names or "", row.family_names or "")
        peer = {f for j, f in enumerate(fams) if j != i}
        entry, method = match(author, entries, person_orcid.get(row.person_uuid), peer)
        if entry is not None and entry.id and method in _STRONG_METHODS:
            matches[row.person_uuid].append((work_uuid, entry, method))


def _weak_rows(
    institution_id: int,
    weak: dict[str, tuple[list[tuple[ExtEntry, str, str]], dict[str, frozenset[str]]]],
    aid_orcids: dict[str, set[str]],
    aid_names: dict[str, Counter],
    person_orcid: dict[str, str],
    person_name: dict[str, str],
    *,
    admitted_uuids: set[str],
    confirmed_uuids: set[str],
    claimed_ids: dict[str, set[str]],
) -> tuple[list[dict[str, Any]], Counter]:
    """Identity admission for org-dead-end corpus members (owner decision
    2026-10-31), from the evidence _weak_evidence collected. Pure's OAI
    orgunits set serves no parent edges for sub-departments, so a person
    whose every authorship edge and profile affiliation lands on such
    flat orgs never passes tree.resolves — they never enter the cascade
    and stay off the author browse entirely (43 live authors as of
    2026-10-31; a non-OAI hierarchy source remains the full fix). Admit a
    confirmed id when the person's own works bind exactly one external id
    through BOTH deterministic name evidence (orcid-exact / name-exact /
    name-initials — family-unique and fuzzy stay out: 55% of edges carry
    empty affiliations, and soft name evidence on unaffiliated works is
    the namesake trap the org gate exists for) and a single consistent
    ORCID: the set of orcids on the person's matched entries (plus their
    profile orcid) must be exactly one value — multiple distinct values
    is merged-profile/human ambiguity the rung refuses
    (skipped_orcid_ambiguous) — and that one value must equal the id's
    global orcid set in our store — impostor namesakes carry their own
    orcid, and a merged OpenAlex profile fails the equality. Persons
    without any orcid evidence stay unadmitted. An extra matched id is a
    fragment twin (rides along confirmed) when its global orcid set is
    empty or the same human's and it never sits on one authorship list
    with the primary; carrying a different orcid it is a namesake match
    and the person stays out. Two same-name persons selecting the same
    id cancel out (_uncontested_weak_rows, once every person is in).

    `claimed_ids` must already hold every id the cascade and the
    ORCID-listing join bound. Returns the rows and the skip counts."""
    rows_out: list[dict[str, Any]] = []
    skipped: Counter = Counter()
    for uuid in sorted(weak):
        if uuid in admitted_uuids or uuid in confirmed_uuids:
            continue
        weak_outcomes, work_id_sets = weak[uuid]
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
        # Exactly ONE human orcid across the person's evidence (the
        # Xiang Zhang class: multiple distinct values means the evidence
        # spans several humans — merged profiles, family shared names —
        # and name evidence alone cannot tell them apart).
        if len(person_orcids) > 1:
            skipped["orcid_ambiguous"] += 1
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
    return rows_out, skipped


def _uncontested_weak_rows(
    rows_out: list[dict[str, Any]], skipped: Counter
) -> list[dict[str, Any]]:
    """Same id chosen by two different unaffiliated persons = an OpenAlex
    namesake merge; admit neither."""
    by_id: dict[str, set[str]] = defaultdict(set)
    for row in rows_out:
        by_id[row["external_id"]].add(row["author_pure_uuid"])
    contested = [r for r in rows_out if len(by_id[r["external_id"]]) > 1]
    if contested:
        skipped["namesake_contested"] += len(contested)
        return [r for r in rows_out if len(by_id[r["external_id"]]) == 1]
    return rows_out


async def _edges_by_work(
    session: AsyncSession, institution_id: int, work_uuids: list[str]
) -> dict[str, list[Any]]:
    """work_pure_authors rows grouped by work (work-entry spellings kept)
    for the given works. The column rows carry the attributes of the ORM
    rows the cascade reads."""
    by_work: dict[str, list[Any]] = defaultdict(list)
    stmt = select(
        WorkPureAuthor.work_pure_uuid,
        WorkPureAuthor.person_uuid,
        WorkPureAuthor.first_names,
        WorkPureAuthor.family_names,
        WorkPureAuthor.affiliations,
    ).where(WorkPureAuthor.institution_id == institution_id)
    for start in range(0, len(work_uuids), LOOKUP_CHUNK):
        rows = await session.execute(
            stmt.where(WorkPureAuthor.work_pure_uuid.in_(work_uuids[start : start + LOOKUP_CHUNK]))
        )
        for row in rows:
            by_work[row.work_pure_uuid].append(row)
    return by_work


async def _openalex_by_doi(
    session: AsyncSession, institution_id: int, dois: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """OpenAlex authorships combined per DOI (merged profiles can carry one
    publication under two W-ids), for the given DOIs."""
    by_doi: dict[str, list[dict[str, Any]]] = defaultdict(list)
    stmt = select(OpenalexWork.doi_normalized, OpenalexWork.authorships).where(
        OpenalexWork.institution_id == institution_id
    )
    for start in range(0, len(dois), LOOKUP_CHUNK):
        rows = await session.execute(
            stmt.where(OpenalexWork.doi_normalized.in_(dois[start : start + LOOKUP_CHUNK]))
        )
        for doi_normalized, authorships in rows:
            if doi_normalized:
                by_doi[doi_normalized].extend(authorships or [])
    return by_doi


async def _load_persons(
    session: AsyncSession, institution
) -> tuple[dict[str, str], dict[str, str], dict[str, list[str]]]:
    """person_orcid, person_name and the profile orgs the cascade reads,
    for the persons the pass can reach: everyone with an ORCID (the
    author-listing join walks them) plus everyone with an authorship
    edge. Column-selects the four fields: the one-shot run's full ORM
    rows of every person, payloads included, were a large slice of its
    memory."""
    has_edge = exists().where(
        WorkPureAuthor.institution_id == PurePerson.institution_id,
        WorkPureAuthor.person_uuid == PurePerson.uuid,
    )
    person_orcid: dict[str, str] = {}
    person_name: dict[str, str] = {}
    profile_orgs: dict[str, list[str]] = {}
    for uuid, orcid, name, affiliations in (
        await session.execute(
            select(
                PurePerson.uuid,
                PurePerson.orcid,
                PurePerson.name,
                PurePerson.payload["cerif"]["affiliations"],
            ).where(
                PurePerson.institution_id == institution.id,
                or_(func.coalesce(PurePerson.orcid, "") != "", has_edge),
            )
        )
    ).all():
        if orcid:
            person_orcid[uuid] = orcid
        if name:
            person_name.setdefault(uuid, name)
        # profile-affiliation arm: the CERIF payload's affiliation org uuids
        profile_orgs[uuid] = [
            aff.get("affiliation_id")
            for aff in affiliations or []
            if isinstance(aff, dict) and aff.get("affiliation_id")
        ]
    return person_orcid, person_name, profile_orgs


async def _load_openaire_slice(
    session: AsyncSession,
    chunk: list[str],
    by_doi_oa: dict[str, list[ExtEntry]],
    aid_orcids_oa: dict[str, set[str]],
    aid_names_oa: dict[str, Counter],
) -> None:
    """Fold one DOI slice of the OpenAIRE work store into the per-DOI
    entries and the corroboration indexes."""
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
            name = a.get("fullName") or " ".join(p for p in (a.get("name"), a.get("surname")) if p)
            orcid = openaire_author_orcid(a)
            entry_id = (a.get("id") or "").rsplit("/", 1)[-1] or None
            if not name and not orcid:
                continue
            if entry_id:
                if orcid:
                    aid_orcids_oa[entry_id].add(orcid)
                if name:
                    aid_names_oa[entry_id][name] += 1
            by_doi_oa[doi].append(ExtEntry(entry_id, name or None, orcid))


async def _corroboration_index(
    session: AsyncSession, institution_id: int, wanted: set[str]
) -> tuple[dict[str, set[str]], dict[str, Counter]]:
    """A-id -> ORCIDs and display-name counts over the institution's
    stored OpenAlex authorships, for the ids in `wanted` only. The
    one-shot run indexed every author on every stored work; only the ids
    someone matched are ever read. The stream is the works store in table
    order, so a name's rank among equals is the first-seen order the
    one-shot Counters had."""
    aid_orcids: dict[str, set[str]] = defaultdict(set)
    aid_names: dict[str, Counter] = defaultdict(Counter)
    result = await session.stream(
        select(OpenalexWork.doi_normalized, OpenalexWork.authorships)
        .where(OpenalexWork.institution_id == institution_id)
        .execution_options(stream_results=True, max_row_buffer=STREAM_PARTITION)
    )
    async for partition in result.partitions(STREAM_PARTITION):
        for _doi, authorships in partition:
            for sh in authorships or []:
                aid = sh.get("a") if isinstance(sh, dict) else None
                if not aid or aid not in wanted:
                    continue
                if sh.get("o"):
                    aid_orcids[aid].add(sh["o"])
                if sh.get("n"):
                    aid_names[aid][sh["n"]] += 1
    return aid_orcids, aid_names


async def _upsert_identities(session: AsyncSession, chunk: list[dict[str, Any]]) -> None:
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


class _IdentitySink:
    """Identity rows on their way to author_identities, upserted a chunk
    at a time (asyncpg caps one statement at 32767 bound params; each
    row binds 10). Also keeps what the later rungs read back from the
    rows: the ids each person already bound, who is confirmed, and the
    row counts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.pending: list[dict[str, Any]] = []
        self.claimed: dict[str, set[str]] = defaultdict(set)
        self.confirmed_uuids: set[str] = set()
        self.proposed: set[tuple[str, str]] = set()
        self.rows = 0
        self.candidate_rows = 0

    async def add(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            # Identities without an external id are noise (nothing collectable).
            if not row["external_id"]:
                continue
            self.pending.append(row)
            self.rows += 1
            self.candidate_rows += row["status"] == "candidate"
            self.claimed[row["external_id"]].add(row["author_pure_uuid"])
            self.proposed.add((row["author_pure_uuid"], row["external_id"]))
            if row["source"] == SOURCE and row["status"] == "confirmed":
                self.confirmed_uuids.add(row["author_pure_uuid"])
        if len(self.pending) >= UPSERT_CHUNK:
            await self.flush()

    async def flush(self) -> None:
        for start in range(0, len(self.pending), UPSERT_CHUNK):
            await _upsert_identities(self.session, self.pending[start : start + UPSERT_CHUNK])
        self.pending.clear()


async def _cascade_identities(
    institution,
    outcomes: dict[str, dict[str, list[tuple[str, str | None, str, frozenset[str]]]]],
    arm_evidence: dict[str, tuple[dict[str, set[str]], dict[str, Counter]]],
    person_orcid: dict[str, str],
    person_name: dict[str, str],
    sink: _IdentitySink,
) -> tuple[dict[str, dict[str, Any]], int]:
    """aggregation + corroboration + identity rows of the work-anchored
    cascade. Returns the per-arm stats and the corroborated alternates."""
    corroborated_alts = 0
    per_arm: dict[str, dict[str, Any]] = {}
    for src, (arm_orcids, arm_names) in arm_evidence.items():
        matched = 0
        methods: Counter = Counter()
        conflicted_authors = 0
        for uuid, outs in sorted(outcomes[src].items()):
            agg = aggregate([(ExtEntry(eid, None, None), m) for _w, eid, m, _ids in outs])
            if agg is None:
                continue
            primary, method, conflicts = agg
            matched += 1
            methods[method] += 1
            if conflicts:
                conflicted_authors += 1
            porcid = person_orcid.get(uuid)
            ids_seen = {eid for _w, eid, _m, _ids in outs if eid}
            alternates = sorted(ids_seen - {primary.id}) if primary.id else sorted(ids_seen)
            rows: list[dict[str, Any]] = []

            if primary.id:
                primary_corroborated = bool(porcid) and porcid in arm_orcids.get(primary.id, set())
                rows.append(
                    {
                        "institution_id": institution.id,
                        "author_pure_uuid": uuid,
                        "source": src,
                        "external_id": primary.id,
                        "status": _derived_status(method, conflicts),
                        "method": method,
                        "confidence": CONFIDENCE.get(method),
                        "n_works": sum(1 for o in outs if o[1] == primary.id),
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
                    primary.id in ids and aid in ids for _w, _eid, _m, ids in outs
                )
                ids_all = ([primary.id] if primary.id else []) + alternates
                seen_orcids = (
                    set().union(*(arm_orcids.get(i, set()) for i in ids_all)) if ids_all else set()
                )
                orcid_consistent = len(seen_orcids) <= 1
                is_twin = not co_occur and orcid_consistent
                rows.append(
                    {
                        "institution_id": institution.id,
                        "author_pure_uuid": uuid,
                        "source": src,
                        "external_id": aid,
                        "status": "confirmed" if is_twin else "candidate",
                        "method": "orcid-corroboration" if corroborated else "fragmentation",
                        "confidence": 0.9 if corroborated else CONFIDENCE.get(METHOD_FUZZY),
                        "n_works": sum(1 for o in outs if o[1] == aid),
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
            await sink.add(rows)
        per_arm[src] = {
            "matched": matched,
            "methods": dict(methods),
            "conflicted_authors": conflicted_authors,
        }
    return per_arm, corroborated_alts


async def resolve_author_ids(
    session: AsyncSession,
    institution,
    *,
    run_sweeps: bool = True,
    listing_limit: int | None = None,
) -> dict[str, Any]:
    """Full resolution pass for one institution. run_sweeps=False (tests)
    resolves against store contents only.

    What stays in memory for the whole pass is global by nature and kept
    compact: one record per matched (person, work), the persons' ORCIDs
    and the corroboration indexes of the ids anyone matched. Every
    work-level store is read per slice of local DOIs and dropped before
    the next slice, and identity rows go to the table a chunk at a time."""
    started = time.monotonic()
    stats: dict[str, Any] = {}
    iid = institution.id
    tree = await load_org_tree(session, institution)
    stats["root_resolved"] = tree.root is not None
    person_orcid, person_name, profile_orgs = await _load_persons(session, institution)

    # Local work DOIs (matches the cascade's work-keyed design: no DOI, no
    # OpenAlex counterpart — authorship candidates ride the works that
    # carry one; the per-author sweep covers the rest).
    active_dois = sorted(
        d
        for (d,) in (
            await session.execute(
                select(Work.doi_normalized).where(
                    Work.institution_id == iid, Work.retired_at.is_(None)
                )
            )
        ).all()
        if d
    )
    edge_works = await session.scalar(
        select(func.count(distinct(WorkPureAuthor.work_pure_uuid))).where(
            WorkPureAuthor.institution_id == iid
        )
    )

    # OpenAIRE work store: the same work-anchored cascade against a second
    # external corpus (authorship names arrive inverted "Family, First";
    # decompose_name parses both orders). Ids are OpenAIRE person keys —
    # mostly orcid-derived — stored as separate source='openaire'
    # identity rows so the namespace never mixes with OpenAlex A-ids.
    by_doi_oa: dict[str, list[ExtEntry]] = defaultdict(list)
    aid_orcids_oa: dict[str, set[str]] = defaultdict(set)
    aid_names_oa: dict[str, Counter] = defaultdict(Counter)

    # ── the work-anchored cascade ────────────────────────────────────────
    # One record per matched (person, work): the work, the matched id and
    # method, and the ids on the work (the twin gate reads them). The
    # aggregation needs nothing more — n_works counts the person's records
    # with that id — so the entry objects, the per-work id sets and the
    # id -> works sets of the one-shot run are gone. The stores of one DOI
    # slice are loaded, walked and dropped before the next slice.
    outcomes: dict[str, dict[str, list[tuple[str, str | None, str, frozenset[str]]]]] = {
        SOURCE: defaultdict(list),
        SOURCE_OPENAIRE: defaultdict(list),
    }
    # The same walk collects the weak-affiliation rung's evidence for
    # every author edge, so the works are loaded once for both.
    weak_id_sets: dict[str, dict[str, frozenset[str]]] = defaultdict(dict)
    weak_matches: dict[str, list[tuple[str, ExtEntry, str]]] = defaultdict(list)
    works = 0
    works_matched = 0
    works_without_openalex = 0
    sliced_works = 0
    for start in range(0, len(active_dois), DOI_SLICE):
        chunk = active_dois[start : start + DOI_SLICE]
        await _load_openaire_slice(session, chunk, by_doi_oa, aid_orcids_oa, aid_names_oa)
        doi_of_slice = dict(
            (
                await session.execute(
                    select(Work.pure_uuid, Work.doi_normalized).where(
                        Work.institution_id == iid,
                        Work.retired_at.is_(None),
                        Work.doi_normalized.in_(chunk),
                    )
                )
            ).all()
        )
        by_work = await _edges_by_work(session, iid, list(doi_of_slice))
        sliced_works += len(by_work)
        by_doi = await _openalex_by_doi(session, iid, chunk)
        for work_uuid, rows in sorted(by_work.items()):
            doi = doi_of_slice[work_uuid]
            oa_authorships = by_doi.get(doi, [])
            if not oa_authorships:
                works_without_openalex += 1
                continue
            entries = openalex_entries(oa_authorships)
            if entries:
                # every author edge, admitted or not (see the weak rung)
                _weak_evidence(work_uuid, rows, entries, person_orcid, weak_id_sets, weak_matches)
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
            if not entries:
                continue
            works_matched += 1
            authors = [
                PureAuthor(
                    row.person_uuid,
                    row.first_names or "",
                    row.family_names or "",
                )
                for row in affiliated
            ]
            fams = [decompose_parts(a.first, a.family).family_only for a in authors]
            ext_lists = (
                (SOURCE, entries),
                (SOURCE_OPENAIRE, by_doi_oa.get(doi, [])),
            )
            for src, ext in ext_lists:
                if not ext:
                    continue
                # every id present on the work: the twin gate checks
                # primary/alternate co-occurrence here
                ids = frozenset(e.id for e in ext if e.id)
                for i, a in enumerate(authors):
                    peer = {f for j, f in enumerate(fams) if j != i}
                    entry, method = match(a, ext, person_orcid.get(a.uuid), peer)
                    if entry is None or method is None:
                        continue
                    outcomes[src][a.uuid].append((work_uuid, entry.id, method, ids))
        logger.info(
            "author ids[%s]: cascade DOI slice %d-%d done",
            institution.code,
            start,
            start + len(chunk),
        )
    # The slices hand a person's works back in several rounds.
    for arm in outcomes.values():
        for outs in arm.values():
            outs.sort(key=itemgetter(0))
    # A work with edges but no DOI on an active work never reaches a slice.
    works_without_doi = (edge_works or 0) - sliced_works

    # ── weak-affiliation matches (org-dead-end recovery) ────────────────
    # Per person in work order, for the authors the cascade did not admit;
    # the ids they matched name what the corroboration index must cover.
    admitted_uuids = {u for src in outcomes for u in outcomes[src]}
    weak: dict[str, tuple[list[tuple[ExtEntry, str, str]], dict[str, frozenset[str]]]] = {}
    for uuid, matched in weak_matches.items():
        if uuid in admitted_uuids:
            continue
        matched.sort(key=itemgetter(0))
        weak[uuid] = ([(entry, method, w) for w, entry, method in matched], weak_id_sets[uuid])
    del by_doi_oa, weak_id_sets, weak_matches

    # Corroboration indexes (A-id -> orcids / display names) for the ids
    # the cascade and the weak rung matched. Column-select only the two
    # fields the pass needs: full ORM rows (title/year/...) plus the
    # identity map OOM-killed the live run at 14.6 GB.
    wanted = {
        eid
        for arm in outcomes.values()
        for outs in arm.values()
        for _w, eid, _m, _ids in outs
        if eid
    }
    wanted.update(
        e.id for weak_outcomes, _sets in weak.values() for e, _m, _w in weak_outcomes if e.id
    )
    aid_orcids, aid_names = await _corroboration_index(session, iid, wanted)
    listing_orcids = {
        aid: orcid for aid, orcid in (await _listing_orcids(session, iid)).items() if orcid
    }
    for aid, orcid in listing_orcids.items():
        if aid in wanted:
            aid_orcids[aid].add(orcid)

    # ── aggregation + corroboration + identity rows ─────────────────────
    sink = _IdentitySink(session)
    per_arm, corroborated_alts = await _cascade_identities(
        institution,
        outcomes,
        {SOURCE: (aid_orcids, aid_names), SOURCE_OPENAIRE: (aid_orcids_oa, aid_names_oa)},
        person_orcid,
        person_name,
        sink,
    )

    # ── profile-orcid ↔ author-listing join ──────────────────────────────
    # Deterministic identity join, no name matching involved: an OpenAlex
    # author profile that carries the pure person's own ORCID is that
    # person (ut-metadata admitted its roster this way). Only authors with
    # no confirmed OpenAlex row from the work-anchored cascade are
    # extended — the work-level pass stays the primary evidence.
    listing_by_orcid = {orcid: aid for aid, orcid in listing_orcids.items()}
    listing_rows = 0
    for uuid, porcid in sorted(person_orcid.items()):
        if uuid in sink.confirmed_uuids:
            continue
        aid = listing_by_orcid.get(porcid)
        if not aid or (uuid, aid) in sink.proposed:
            continue
        await sink.add(
            [
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
            ]
        )
        sink.confirmed_uuids.add(uuid)
        listing_rows += 1
    per_arm["orcid-listing"] = {"rows": listing_rows}

    # ── weak-affiliation rung (org-dead-end recovery) ────────────────────
    # Every id already bound by the cascade/listing rows (primaries AND
    # fragmentation twins) blocks re-binding to another person.
    rows_out, skipped = _weak_rows(
        institution.id,
        weak,
        aid_orcids,
        aid_names,
        person_orcid,
        person_name,
        admitted_uuids=admitted_uuids,
        confirmed_uuids=sink.confirmed_uuids,
        claimed_ids=sink.claimed,
    )
    weak_rows = _uncontested_weak_rows(rows_out, skipped)
    await sink.add(weak_rows)
    per_arm["weak-affiliation"] = {
        "admitted": len(weak_rows),
        "methods": dict(Counter(r["method"] for r in weak_rows)),
        **{f"skipped_{k}": v for k, v in skipped.items()},
    }
    await sink.flush()

    # ── sweeps + projection refresh ──────────────────────────────────────
    sweep_stats: dict[str, Any] = {}
    if run_sweeps:
        from aletheca import AlethecaClient

        settings = get_settings()
        client_kwargs: dict[str, Any] = {}
        if settings.openalex_api_key:
            client_kwargs["api_key"] = settings.openalex_api_key
        async with AlethecaClient(**client_kwargs) as client:
            sweep_stats["gather"] = await gather_openalex_authors(
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
            "identity_rows": sink.rows,
            "confirmed_rows": sink.rows - sink.candidate_rows,
            "candidate_rows": sink.candidate_rows,
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
