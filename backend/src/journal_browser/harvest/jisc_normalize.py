"""JISC Open Policy Finder normalizer: landing payloads -> canon tables.

Reads the latest source_records payload per (entity_type, source_pk)
(landed by jobs/harvest_jisc.py), upserts the six jisc_* tables, then
stamps journals.jisc_* by matching the publications' real ISSNs against
journals.issns containment — never issn_l alone. Idempotent: reruns
upsert the same provider PKs.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Text, bindparam, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    IssnMap,
    JiscFunder,
    JiscFunderGroup,
    JiscPolicy,
    JiscPublication,
    JiscPublisher,
    JiscRepository,
    Journal,
    SourceRecord,
)
from .common import HarvestDataError, normalize_issn, run_harvest
from .jisc_opf import SOURCE, SWEEP_TYPES

logger = logging.getLogger(__name__)

POLICY_URI = "https://openpolicyfinder.jisc.ac.uk/publication/{}"
ROUTE_ORDER = ("submitted", "accepted", "published")
UPSERT_CHUNK = 2_000  # asyncpg caps statements at 32,767 binds
MATCH_CHUNK = 20_000  # in_() list + one array bind stay under the cap


def _strip_phrases(value: Any) -> Any:
    """Drop every *_phrases sibling (search corpus only) at any depth."""
    if isinstance(value, dict):
        return {k: _strip_phrases(v) for k, v in value.items() if not k.endswith("_phrases")}
    if isinstance(value, list):
        return [_strip_phrases(v) for v in value]
    return value


def _int_or_none(raw: Any) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _int_list(values: Any) -> list[int]:
    return [i for v in values or [] if (i := _int_or_none(v)) is not None]


def _yesno(raw: Any) -> bool | None:
    """OPF yes/no field -> bool; anything else None."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() == "yes"


def _ccode(raw: Any) -> str | None:
    """ISO-2 country: the string form truncated to two chars."""
    return raw[:2] if isinstance(raw, str) and len(raw) >= 2 else None


def _url(raw: Any) -> str | None:
    """First URL string from a scalar or a [{url, ...}] list."""
    if isinstance(raw, str):
        return raw.strip() or None
    if not isinstance(raw, list):
        return None
    for entry in raw:
        if isinstance(entry, dict) and isinstance(entry.get("url"), str) and entry["url"].strip():
            return entry["url"].strip()
    return None


def _display_name(raw: Any) -> str | None:
    """Display name from a scalar, a {name} object, or a
    [{name|title, language, preferred}] list: English first, entries
    flagged preferred:"name" on top, then the first entry."""
    if isinstance(raw, str):
        return raw.strip() or None
    entries = raw if isinstance(raw, list) else [raw] if isinstance(raw, dict) else []
    named: list[tuple[bool, bool, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        value = entry.get("name") or entry.get("title")
        if isinstance(value, str) and value.strip():
            named.append(
                (
                    str(entry.get("language") or "").lower().startswith("en"),
                    entry.get("preferred") == "name",
                    value.strip(),
                )
            )
    if not named:
        return None
    named.sort(key=lambda t: (not t[0], not t[1]))
    return named[0][2]


def _date_modified(payload: dict[str, Any]) -> datetime | None:
    """system_metadata.date_modified ("2025-09-25 08:09:08") as UTC."""
    raw = (payload.get("system_metadata") or {}).get("date_modified")
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp


def _pub_issns(payload: dict[str, Any]) -> list[str]:
    """Checksum-tolerant normalized ISSN strings of a publication record."""
    out = []
    for entry in payload.get("issns") or []:
        if isinstance(entry, dict) and (issn := normalize_issn(entry.get("issn"))):
            out.append(issn)
    return list(dict.fromkeys(out))


def _publication_row(pk: str, p: dict[str, Any]) -> dict[str, Any] | None:
    """jisc_publications row; the id lists link to the swept publisher/
    policy rows, embedded objects stay in the raw payload only."""
    pub_id = _int_or_none(p.get("id", pk))
    if pub_id is None:
        return None
    return {
        "id": pub_id,
        "title": _display_name(p.get("title")),
        "pub_type": p.get("type"),
        "url": _url(p.get("url")),
        "listed_in_doaj": _yesno(p.get("listed_in_doaj")),
        "issns": _strip_phrases(p.get("issns")),
        "publisher_ids": _int_list(
            (link.get("publisher") or {}).get("id") for link in p.get("publishers") or []
        ),
        "policy_ids": _int_list(pol.get("id") for pol in p.get("publisher_policy") or []),
        "date_modified": _date_modified(p),
    }


def _publisher_row(pk: str, p: dict[str, Any]) -> dict[str, Any] | None:
    """jisc_publishers row; a record without any usable name is skipped
    (the column is NOT NULL)."""
    pub_id = _int_or_none(p.get("id", pk))
    name = _display_name(p.get("name"))
    if pub_id is None or name is None:
        return None
    return {
        "id": pub_id,
        "name": name,
        "url": _url(p.get("url")),
        "country": _ccode(p.get("country")),
        "ror": next(
            (
                str(i.get("identifier"))
                for i in p.get("identifiers") or []
                if isinstance(i, dict) and i.get("type") == "ror" and i.get("identifier")
            ),
            None,
        ),
        "publication_count": _int_or_none(p.get("publication_count")),
        "imprint_of_id": _int_or_none((p.get("imprint_of") or {}).get("id")),
        "date_modified": _date_modified(p),
    }


def _policy_row(pk: str, p: dict[str, Any]) -> dict[str, Any] | None:
    """jisc_policies row; permitted_oa kept verbatim (phrases stripped)."""
    pol_id = _int_or_none(p.get("id", pk))
    if pol_id is None:
        return None
    return {
        "id": pol_id,
        "publisher_id": _int_or_none((p.get("publisher") or {}).get("id")),
        "open_access_prohibited": _yesno(p.get("open_access_prohibited")),
        "internal_moniker": p.get("internal_moniker"),
        "urls": _strip_phrases(p.get("urls")),
        "workflow_dates": _strip_phrases(p.get("workflow_dates")),
        "permitted_oa": _strip_phrases(p.get("permitted_oa")),
        "publication_count": _int_or_none(p.get("publication_count")),
        "date_modified": _date_modified(p),
    }


def _funder_row(pk: str, p: dict[str, Any]) -> dict[str, Any] | None:
    """jisc_funders row; both OA policy blocks kept verbatim (stripped)."""
    funder_id = _int_or_none(p.get("id", pk))
    if funder_id is None:
        return None
    meta = p.get("funder_metadata") or {}
    return {
        "id": funder_id,
        "name": _display_name(meta.get("name")),
        "country": _ccode(meta.get("country")),
        "url": _url(meta.get("url")),
        "identifiers": _strip_phrases(meta.get("identifiers")),
        "publications_policy": _strip_phrases(p.get("open_access_publications_policy")),
        "data_archiving_policy": _strip_phrases(p.get("open_access_data_archiving_policy")),
        "date_modified": _date_modified(p),
    }


def _funder_group_row(pk: str, p: dict[str, Any]) -> dict[str, Any] | None:
    """jisc_funder_groups row; the group name lives in funder_group_metadata."""
    group_id = _int_or_none(p.get("id", pk))
    if group_id is None:
        return None
    meta = p.get("funder_group_metadata") or {}
    return {
        "id": group_id,
        "name": _display_name(meta.get("name")),
        "funders": _strip_phrases(p.get("funders")),
        "date_modified": _date_modified(p),
    }


def _repository_row(pk: str, p: dict[str, Any]) -> dict[str, Any] | None:
    """jisc_repositories row (OpenDOAR)."""
    repo_id = _int_or_none(p.get("id", pk))
    if repo_id is None:
        return None
    meta = p.get("repository_metadata") or {}
    return {
        "id": repo_id,
        "name": _display_name(meta.get("name")),
        "type": meta.get("type"),
        "url": _url(meta.get("url")),
        "oai_url": meta.get("oai_url"),
        "software": _display_name(meta.get("software")),
        "content_subjects": _strip_phrases(meta.get("content_subjects")),
        "content_types": _strip_phrases(meta.get("content_types")),
        "full_text_record_count": _int_or_none(meta.get("full_text_record_count")),
        "metadata_record_count": _int_or_none(meta.get("metadata_record_count")),
        "date_modified": _date_modified(p),
    }


_SIMPLE: dict[str, tuple[Any, Any]] = {
    "publisher": (JiscPublisher, _publisher_row),
    "publisher_policy": (JiscPolicy, _policy_row),
    "funder": (JiscFunder, _funder_row),
    "funder_group": (JiscFunderGroup, _funder_group_row),
    "repository": (JiscRepository, _repository_row),
}


async def _upsert(session: AsyncSession, model: Any, rows: list[dict[str, Any]]) -> int:
    """Chunked INSERT ... ON CONFLICT (id) DO UPDATE: idempotent refresh;
    harvested_at re-stamps to now() on every rerun."""
    if not rows:
        return 0
    table = model.__table__
    for at in range(0, len(rows), UPSERT_CHUNK):
        chunk = rows[at : at + UPSERT_CHUNK]
        stmt = pg_insert(table).values(chunk)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={
                    **{c: getattr(stmt.excluded, c) for c in chunk[0] if c != "id"},
                    "harvested_at": text("now()"),
                },
            )
        )
    return len(rows)


async def _latest_payloads(session: AsyncSession) -> dict[str, dict[str, dict[str, Any]]]:
    """Newest landing payload per (entity_type, source_pk); recency key is
    harvested_at with id breaking ties (ix_source_records_lookup order)."""
    latest: dict[str, dict[str, dict[str, Any]]] = {}
    for entity_type in SWEEP_TYPES:
        ranked = (
            select(
                SourceRecord.source_pk,
                SourceRecord.payload,
                func.row_number()
                .over(
                    partition_by=SourceRecord.source_pk,
                    order_by=[SourceRecord.harvested_at.desc(), SourceRecord.id.desc()],
                )
                .label("rn"),
            )
            .where(SourceRecord.source == SOURCE, SourceRecord.entity_type == entity_type)
            .subquery()
        )
        rows = await session.execute(
            select(ranked.c.source_pk, ranked.c.payload).where(ranked.c.rn == 1)
        )
        latest[entity_type] = dict(rows.all())
    return latest


async def _issn_l_map(session: AsyncSession, issns: set[str]) -> dict[str, str]:
    """ISSN -> ISSN-L for the union of OPF ISSNs. The journals.issns
    containment result overwrites IssnMap so resolution and journal
    stamping stay consistent."""
    mapping: dict[str, str] = {}
    ordered = sorted(issns)
    for at in range(0, len(ordered), MATCH_CHUNK):
        chunk = ordered[at : at + MATCH_CHUNK]
        for issn, issn_l in (
            await session.execute(
                select(IssnMap.issn, IssnMap.issn_l).where(IssnMap.issn.in_(chunk))
            )
        ).all():
            mapping[issn] = issn_l
        # jsonb ?| needs an explicitly typed text[]; a bare list binds as jsonb.
        variants = bindparam("variant_issns", chunk, type_=ARRAY(Text))
        for issn_l, issn_variants in (
            await session.execute(
                select(Journal.issn_l, Journal.issns).where(
                    Journal.issn_l.in_(chunk) | Journal.issns.op("?|")(variants)
                )
            )
        ).all():
            if issn_l:
                for issn in {issn_l, *(issn_variants or [])}:
                    mapping[issn] = issn_l
    return mapping


def _blank_route() -> dict[str, Any]:
    return {
        "locations": [],
        "repositories": [],
        "licenses": [],
        "embargo_months": None,
        "conditions": [],
        "additional_oa_fee": None,
        "fee_only": False,
    }


def _embargo_months(embargo: Any) -> int | None:
    """Minimum stated embargo in months; entries without amount+units or
    with units other than months/years are ignored."""
    months: int | None = None
    for entry in embargo or []:
        if not isinstance(entry, dict):
            continue
        units = str(entry.get("units") or "").lower()
        value = _int_or_none(entry.get("amount_units"))
        if value is None or not units:
            continue
        if units.startswith("year"):
            value *= 12
        elif not units.startswith("month"):
            continue
        months = value if months is None else min(months, value)
    return months


def _merge_policies(payloads: list[dict[str, Any]], sherpa_id: int) -> dict[str, Any]:
    """journals.jisc_policy display object across every OPF publication
    record matching one journal: permitted_oa routes union per
    article_version, embargo months take the minimum stated, and
    open_access_prohibited is an OR. License versions stay verbatim in
    jisc_policies.permitted_oa, so the display keeps license names only."""
    routes: dict[str, dict[str, Any]] = {}
    prohibited = False
    moniker: str | None = None
    urls: list[Any] = []
    fee_stated: dict[str, int] = {}
    fee_yes: dict[str, int] = {}
    for payload in payloads:
        for pol in _strip_phrases(payload.get("publisher_policy")) or []:
            prohibited = prohibited or _yesno(pol.get("open_access_prohibited")) is True
            if moniker is None and pol.get("internal_moniker"):
                moniker = pol.get("internal_moniker")
            if not urls:
                urls = pol.get("urls") or []
            for oa in pol.get("permitted_oa") or []:
                if not isinstance(oa, dict):
                    continue
                fee = _yesno(oa.get("additional_oa_fee"))
                versions = oa.get("article_version")
                versions = versions if isinstance(versions, list) else [versions]
                loc = oa.get("location") or {}
                for version in versions:
                    if not isinstance(version, str):
                        continue
                    route = routes.setdefault(version, _blank_route())
                    route["locations"] = sorted(
                        {*route["locations"], *(str(v) for v in loc.get("location") or [])}
                    )
                    route["repositories"] = sorted(
                        {
                            *route["repositories"],
                            *(str(v) for v in loc.get("named_repository") or []),
                        }
                    )
                    route["licenses"] = sorted(
                        {
                            *route["licenses"],
                            *(
                                str(lic.get("license"))
                                for lic in oa.get("license") or []
                                if isinstance(lic, dict) and lic.get("license")
                            ),
                        }
                    )
                    route["conditions"] = sorted(
                        {*route["conditions"], *(str(c) for c in oa.get("conditions") or [])}
                    )
                    if fee is True:
                        route["additional_oa_fee"] = "yes"
                    elif fee is False and route["additional_oa_fee"] is None:
                        route["additional_oa_fee"] = "no"
                    # Green semantics: a version only self-archives free when
                    # at least one of its routes is not fee-gated.
                    if fee is not None:
                        fee_stated[version] = fee_stated.get(version, 0) + 1
                        if fee is True:
                            fee_yes[version] = fee_yes.get(version, 0) + 1
                    months = _embargo_months(loc.get("embargo"))
                    if months is not None and (
                        route["embargo_months"] is None or months < route["embargo_months"]
                    ):
                        route["embargo_months"] = months
    ordered = {v: routes[v] for v in ROUTE_ORDER if v in routes}
    ordered.update({k: routes[k] for k in routes if k not in ROUTE_ORDER})
    for version, route in ordered.items():
        stated = fee_stated.get(version, 0)
        route["fee_only"] = stated > 0 and fee_yes.get(version, 0) == stated
    return {
        "routes": ordered,
        "open_access_prohibited": prohibited,
        "internal_moniker": moniker,
        "urls": urls,
        "policy_uri": POLICY_URI.format(sherpa_id),
    }


async def _stamp_journals(
    session: AsyncSession,
    pubs_by_id: dict[int, dict[str, Any]],
    issns_by_id: dict[int, list[str]],
) -> tuple[int, int]:
    """Stamp journals.jisc_* for every journal an OPF publication matches
    (via its issn_l or any journals.issns variant). Several publications
    can match one journal through different ISSNs: their policies merge
    into one display object. Returns (journals_matched, embargo_present)."""
    all_issns = sorted({i for issns in issns_by_id.values() for i in issns})
    journal_issns: dict[str, list[str]] = {}
    for at in range(0, len(all_issns), MATCH_CHUNK):
        chunk = all_issns[at : at + MATCH_CHUNK]
        variants = bindparam("variant_issns", chunk, type_=ARRAY(Text))
        for issn_l, issns in (
            await session.execute(
                select(Journal.issn_l, Journal.issns).where(
                    Journal.issn_l.in_(chunk) | Journal.issns.op("?|")(variants)
                )
            )
        ).all():
            journal_issns[issn_l] = [str(i) for i in (issns or [])]

    now = datetime.now(UTC)
    params: list[dict[str, Any]] = []
    embargo_present = 0
    for issn_l, issns in journal_issns.items():
        # A publication matches via its own ISSNs or any journal variant ISSN.
        pids = sorted(pid for pid, pl in issns_by_id.items() if {issn_l, *issns} & set(pl))
        if not pids:
            continue
        policy = _merge_policies([pubs_by_id[pid] for pid in pids], pids[0])
        accepted_embargo = policy["routes"].get("accepted", {}).get("embargo_months")
        if accepted_embargo is not None:
            embargo_present += 1
        params.append(
            {
                "b_issn_l": issn_l,
                "b_prohibited": policy["open_access_prohibited"],
                "b_sherpa_id": pids[0],
                "b_submitted": "submitted" in policy["routes"]
                and not policy["routes"]["submitted"].get("fee_only"),
                "b_accepted": "accepted" in policy["routes"]
                and not policy["routes"]["accepted"].get("fee_only"),
                "b_published": "published" in policy["routes"]
                and not policy["routes"]["published"].get("fee_only"),
                "b_embargo": accepted_embargo,
                "b_policy": policy,
                "b_now": now,
            }
        )
    if params:
        await session.execute(
            Journal.__table__.update()
            .where(Journal.__table__.c.issn_l == bindparam("b_issn_l"))
            .values(
                jisc_in_opf=True,
                jisc_oa_prohibited=bindparam("b_prohibited"),
                jisc_sherpa_id=bindparam("b_sherpa_id"),
                jisc_allows_sa_submitted=bindparam("b_submitted"),
                jisc_allows_sa_accepted=bindparam("b_accepted"),
                jisc_allows_sa_published=bindparam("b_published"),
                jisc_embargo_accepted_months=bindparam("b_embargo"),
                jisc_policy=bindparam("b_policy", type_=JSONB),
                jisc_harvested_at=bindparam("b_now"),
            ),
            params,
        )
    return len(params), embargo_present


async def normalize_jisc(session: AsyncSession) -> dict[str, Any]:
    """Normalize all landed jisc_opf records: upsert the six canon tables
    and stamp the matched journals."""

    async def body(ingest) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        latest = await _latest_payloads(session)
        if not any(latest.values()):
            raise HarvestDataError("no jisc_opf source_records; run jobs/harvest_jisc.py first")

        stats: dict[str, Any] = {}
        for entity_type, (model, builder) in _SIMPLE.items():
            rows = [row for pk, p in latest[entity_type].items() if (row := builder(pk, p))]
            stats[model.__tablename__] = await _upsert(session, model, rows)

        pubs_by_id: dict[int, dict[str, Any]] = {}
        issns_by_id: dict[int, list[str]] = {}
        for pk, p in latest["publication"].items():
            if (pub_id := _int_or_none(p.get("id", pk))) is not None:
                pubs_by_id[pub_id] = p
                issns_by_id[pub_id] = _pub_issns(p)
        mapping = await _issn_l_map(session, {i for pl in issns_by_id.values() for i in pl})
        pub_rows = []
        for pk, p in latest["publication"].items():
            if row := _publication_row(pk, p):
                row["issn_l"] = next(
                    (mapping[i] for i in issns_by_id[row["id"]] if i in mapping), None
                )
                pub_rows.append(row)
        stats["jisc_publications"] = await _upsert(session, JiscPublication, pub_rows)
        matched, embargo_present = await _stamp_journals(session, pubs_by_id, issns_by_id)
        stats["journals_matched"] = matched
        stats["embargo_present"] = embargo_present
        return stats

    return await run_harvest(SOURCE, "normalized", "all", {"from": "source_records"}, body, session)
