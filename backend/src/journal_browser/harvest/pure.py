"""Harvest Pure (ris.utwente.nl) publications via its anonymous OAI-PMH endpoint.

Port of ut-metadata's pure.py (transport + parsing logic kept 1:1 where the
protocol demands it), trimmed to journal-browser's collect-only publications
corpus:

- ``publications:year{YYYY}`` sets over ``oai_dc`` build canonical ``works``
  (per-year restart granularity: a crash re-runs one year).
- The ``openaire_cris_publications`` set over ``oai_cerif_openaire`` enriches
  ``cerif_issn`` / ``publisher`` / ``doi`` (targeted field extraction; the raw
  CERIF XML stays verbatim in source_records for any future re-parse).

Live facts inherited from ut-metadata (2026-09-04): publications:* sets serve
oai_dc; cris sets require oai_cerif_openaire; deletedRecord=no; granularity
YYYY-MM-DDThh:mm:ssZ. Pure reports no deletes: periodic full re-baselines mark
absent works retired instead of deleting evidence.
"""

import asyncio
import contextlib
import logging
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..ingest import IngestSession
from ..models import Work
from .common import RETRY_STATUS, retry_delay

logger = logging.getLogger(__name__)

SOURCE = "pure"
OAI_NS = "http://www.openarchives.org/OAI/2.0/"
DC_NS = "http://purl.org/dc/elements/1.1/"
DCT_NS = "http://purl.org/dc/terms/"

DEFAULT_YEAR_SET = "publications:year{year}"
CRIS_PUBLICATIONS_SET = "openaire_cris_publications"
PREFIX_DC = "oai_dc"
PREFIX_CERIF = "oai_cerif_openaire"

# badResumptionToken => restart the whole set from scratch, at most this often.
MAX_TOKEN_RESTARTS = 2
MAX_HTTP_ATTEMPTS = 5

# Full sweep = every configured window year (settings.data_window_*). Drives
# the retirement pass (works absent from a full sweep are marked, never deleted).


class PureOaiError(RuntimeError):
    """OAI-PMH protocol error (the <error code="..."> element) or parse failure."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"OAI-PMH error {code}" + (f": {message}" if message else ""))
        self.code = code


def oai_tag(local: str) -> str:
    return f"{{{OAI_NS}}}{local}"


class Pacer:
    """Monotonic minimum-interval pacing between requests."""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._next_ok = 0.0

    async def wait(self) -> None:
        delay = self._next_ok - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        self._next_ok = time.monotonic() + self.min_interval


# ── DOI extraction (port of ut-metadata identifiers.extract_doi) ────────────

_DOI_RE = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)
_ZW_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
_DOI_PREFIX_RE = re.compile(r"^(?:https?://)?(?:dx\.)?doi\.org/?", re.IGNORECASE)
_DOI_TAIL_RE = re.compile(r"[?#].*$")
_DOI_TRAIL = ".,;)-/"
_DOI_VERSION_RE = re.compile(r"\.v\d+$", re.IGNORECASE)


def _doi_clean(s: str | None) -> str | None:
    """Prewash: whitespace, zero-width chars, percent-encoding, resolver and
    ``doi:`` prefixes, query/fragment tails, trailing punctuation, version
    suffixes. None when nothing remains."""
    out = (s or "").strip()
    if "%" in out:
        out = unquote(out)
    out = _ZW_RE.sub("", out).strip().lower()
    while True:
        if m := _DOI_PREFIX_RE.match(out):
            out = out[m.end() :].strip()
        elif out.startswith("doi:"):
            out = out[4:].strip()
        elif out.startswith("/"):
            out = out[1:].strip()
        else:
            break
    out = _DOI_TAIL_RE.sub("", out).rstrip(_DOI_TRAIL)
    return _DOI_VERSION_RE.sub("", out) or None


def extract_doi(value: str) -> str | None:
    """Bare lowercase DOI found anywhere in a dc:identifier-ish string."""
    match = _DOI_RE.search(value)
    if match is None:
        return None
    return _doi_clean(match.group(0))


# ── OAI transport ────────────────────────────────────────────────────────────


async def _oai_get(base_url: str, params: dict[str, str], pacer: Pacer) -> ET.Element:
    """One OAI-PMH GET; honors Retry-After on 429/5xx, raises PureOaiError on <error>."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(1, MAX_HTTP_ATTEMPTS + 1):
            await pacer.wait()
            try:
                resp = await client.get(base_url, params=params)
            except httpx.TransportError as exc:
                if attempt == MAX_HTTP_ATTEMPTS:
                    raise
                logger.warning("OAI transport error (attempt %s): %s", attempt, exc)
                await asyncio.sleep(retry_delay(attempt, ""))
                continue
            if resp.status_code in RETRY_STATUS:
                if attempt == MAX_HTTP_ATTEMPTS:
                    resp.raise_for_status()
                delay = retry_delay(attempt, resp.headers.get("Retry-After", ""))
                logger.warning(
                    "OAI %s, retrying in %ss (attempt %s)",
                    resp.status_code,
                    delay,
                    attempt,
                )
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            error = root.find(oai_tag("error"))
            if error is not None:
                raise PureOaiError(error.get("code", "unknown"), error.text or "")
            return root
    raise PureOaiError("http_retries_exhausted")  # pragma: no cover


def _token_attrs(root: ET.Element) -> dict[str, str]:
    """resumptionToken @cursor/@completeListSize progress attributes, if any."""
    el = root.find(f".//{oai_tag('resumptionToken')}")
    if el is None:
        return {}
    return {
        k: v
        for k, v in (
            ("cursor", el.get("cursor")),
            ("complete_list_size", el.get("completeListSize")),
        )
        if v
    }


async def _oai_pages(
    base_url: str,
    verb: str,
    base_params: dict[str, str],
    item_local: str,
    pacer: Pacer,
) -> AsyncIterator[tuple[list[ET.Element], dict[str, str]]]:
    """Yield (page of <item_local>, token progress attrs) across resumption pages.

    An OAI-PMH error (except noRecordsMatch) raises PureOaiError; the caller
    decides whether to restart (badResumptionToken).
    """
    token: str | None = None
    while True:
        params: dict[str, str] = (
            {"verb": verb, "resumptionToken": token} if token else {"verb": verb, **base_params}
        )
        try:
            root = await _oai_get(base_url, params, pacer)
        except PureOaiError as exc:
            if exc.code == "noRecordsMatch":
                return
            raise
        yield root.findall(f".//{oai_tag(item_local)}"), _token_attrs(root)
        token_el = root.find(f".//{oai_tag('resumptionToken')}")
        token = (token_el.text or "").strip() if token_el is not None else None
        if not token:
            return


# ── Parsing ──────────────────────────────────────────────────────────────────


def _header_fields(record: ET.Element) -> tuple[str, str, list[str], str | None]:
    """(oai_identifier, datestamp, set_specs, status) from a <record> header."""
    header = record.find(oai_tag("header"))
    if header is None:
        raise PureOaiError("parse", "record without header")
    return (
        (header.findtext(oai_tag("identifier")) or "").strip(),
        (header.findtext(oai_tag("datestamp")) or "").strip(),
        [s for el in header.findall(oai_tag("setSpec")) if el.text and (s := el.text.strip())],
        header.get("status"),
    )


def _flat_dc(record: ET.Element, namespace: str) -> dict[str, Any]:
    """Flat dc/dct dict: scalar value, or list once an element repeats."""
    out: dict[str, Any] = {}
    for el in record.findall(f".//{{{namespace}}}*"):
        value = " ".join(el.itertext()).strip()
        if not value:
            continue
        key = el.tag.rsplit("}", 1)[-1]
        seen = out.get(key)
        if seen is None:
            out[key] = value
        elif isinstance(seen, list):
            seen.append(value)
        else:
            out[key] = [seen, value]
    return out


def _inner_metadata_xml(record: ET.Element) -> str:
    """Inner XML of <metadata> as a string (verbatim-ish re-serialization)."""
    metadata = record.find(oai_tag("metadata"))
    if metadata is None:
        return ""
    return "".join(ET.tostring(child, encoding="unicode") for child in metadata)


def pure_uuid_for(oai_identifier: str) -> str:
    """Pure uuid from the OAI identifier
    (oai:ris.utwente.nl:publications:<uuid> -> <uuid>)."""
    tail = oai_identifier.rsplit(":", 1)[-1]
    return tail.rsplit("/", 1)[-1]


def _cerif_publication_fields(metadata_el: ET.Element | None) -> dict[str, Any]:
    """Targeted CERIF Publication extraction: the fields works needs.

    The full generic CERIF mapper stays in ut-metadata; everything else in
    the record remains available verbatim via payload["metadata_xml"].
    """
    if metadata_el is None:
        return {}
    root = next(iter(metadata_el), None)
    if root is None or root.tag.rsplit("}", 1)[-1] != "Publication":
        return {}
    local = lambda el: el.tag.rsplit("}", 1)[-1]  # noqa: E731
    fields: dict[str, Any] = {}
    for child in root:
        name = local(child)
        text = " ".join(child.itertext()).strip()
        if name == "DOI" and text:
            fields["doi"] = text
        elif name == "ISSN" and text:
            fields.setdefault("issn", text)
        elif name == "Type":
            fields["type"] = text.rsplit(":", 1)[-1]
        elif name == "Access":
            fields["oa_status"] = text
        elif name == "Publishers":
            for pub in child:
                for sub in pub:
                    if local(sub) == "OrgUnit":
                        for n in sub:
                            if local(n) == "Name" and (t := " ".join(n.itertext()).strip()):
                                fields["publisher"] = t
    return fields


def record_payload(record: ET.Element) -> tuple[str, dict[str, Any]]:
    """(source_pk, payload) for a non-deleted record; source_pk = oai_identifier."""
    oai_identifier, datestamp, set_specs, _ = _header_fields(record)
    payload: dict[str, Any] = {
        "oai_identifier": oai_identifier,
        "datestamp": datestamp,
        "set_specs": set_specs,
        "metadata_xml": _inner_metadata_xml(record),
    }
    dc = _flat_dc(record, DC_NS)
    payload["dc"] = dc
    if dct := _flat_dc(record, DCT_NS):
        payload["dc_dct"] = dct
    identifiers = dc.get("identifier")
    identifier_values = (
        identifiers if isinstance(identifiers, list) else ([identifiers] if identifiers else [])
    )
    for value in identifier_values:
        doi = extract_doi(value)
        if doi:
            payload["doi_normalized"] = doi
            break
    return oai_identifier, payload


# ── Canonical upsert ─────────────────────────────────────────────────────────


def _norm_title(title: str) -> str:
    """Case/punctuation-folded title for fuzzy matching."""
    folded = title.casefold()
    return re.sub(r"[^0-9a-z]+", " ", folded).strip()


def _normalize_access(raw: str | None) -> str | None:
    """Compact access-status literal from Pure's vocabularies.

    Eprints (oai_dc rights): info:eu-repo/semantics/openAccess -> openAccess.
    COAR (cerif Access): .../access_right/c_abf2 -> coar:c_abf2.
    """
    if not raw:
        return None
    raw = raw.strip()
    if "info:eu-repo/semantics/" in raw:
        return raw.rsplit("/", 1)[-1] or None
    if "coar/access_right/" in raw:
        code = raw.rsplit("/", 1)[-1]
        return f"coar:{code}" if code else None
    return raw


# Pure/Eprints/COAR access literals -> the closed works.oa_status set
# (harvest.common.OA_STATUSES). Pure openAccess means the fulltext is public
# in the institutional repository, i.e. green; anything not publicly readable
# now maps to closed; unknown literals drop to None (raw stays in payloads).
_OA_MAP = {
    "openaccess": "green",
    "closedaccess": "closed",
    "embargoedaccess": "closed",
    "restrictedaccess": "closed",
    "metadataonly": "closed",
    "coar:c_abf2": "green",  # open access
    "coar:c_16ec": "closed",  # closed access
    "coar:c_f1cf": "closed",  # embargoed access
    "coar:c_998f": "closed",  # restricted access
}


def canonical_access(raw: str | None) -> str | None:
    """Pure access literal -> canonical oa_status; None when unmappable."""
    compact = _normalize_access(raw)
    if compact is None:
        return None
    return _OA_MAP.get(compact.lower().replace(" ", "").replace("-", ""))


def _dc_first(value: Any) -> str | None:
    if isinstance(value, list):
        return str(value[0]).strip() if value else None
    return str(value).strip() if value else None


def year_for_set(set_spec: str) -> int | None:
    """publications:year2023 -> 2023; None otherwise."""
    if set_spec.startswith("publications:year"):
        try:
            return int(set_spec.rsplit("year", 1)[1])
        except ValueError:
            return None
    return None


async def upsert_work(
    session: AsyncSession,
    payload: dict[str, Any],
    *,
    institution_id: int,
    year: int,
    run_id: int,
) -> None:
    """Upsert one canonical work of one institution from a harvested oai_dc payload."""
    dc = payload.get("dc", {})
    title = _dc_first(dc.get("title"))
    if not title:
        raise PureOaiError("parse", f"record without dc:title: {payload['oai_identifier']}")
    cerif = payload.get("cerif") or {}
    doi = payload.get("doi_normalized") or extract_doi(cerif.get("doi") or "")
    uuid = pure_uuid_for(payload["oai_identifier"])
    if doi:
        # Pure occasionally carries the same publication under two uuids
        # (e.g. article + chapter views); doi_normalized is UNIQUE, so the
        # twin keeps the DOI and this row stays NULL-doi (fuzzy-matchable).
        owner = await session.scalar(
            select(Work.pure_uuid).where(
                Work.institution_id == institution_id,
                Work.doi_normalized == doi,
                Work.pure_uuid != uuid,
            )
        )
        if owner:
            logger.warning(
                "duplicate DOI %s across pure works %s and %s; storing %s without doi",
                doi,
                owner,
                uuid,
                uuid,
            )
            doi = None
    oa_status = canonical_access(_dc_first(cerif.get("oa_status")) or _dc_first(dc.get("rights")))
    stmt = (
        pg_insert(Work)
        .values(
            institution_id=institution_id,
            pure_uuid=uuid,
            doi_normalized=doi,
            title=title,
            norm_title=_norm_title(title),
            year=year,
            work_type=_dc_first(dc.get("type")),
            publisher=_dc_first(dc.get("publisher")),
            cerif_issn=_dc_first(cerif.get("issn")),
            oa_status=oa_status,
            first_seen_run=run_id,
            last_seen_run=run_id,
        )
        .on_conflict_do_update(
            index_elements=[Work.institution_id, Work.pure_uuid],
            set_={
                "doi_normalized": doi,
                "title": title,
                "norm_title": _norm_title(title),
                "year": year,
                "work_type": _dc_first(dc.get("type")),
                "publisher": _dc_first(dc.get("publisher")),
                "cerif_issn": _dc_first(cerif.get("issn")),
                "oa_status": oa_status,
                "last_seen_run": run_id,
                "retired_at": None,
                "updated_at": datetime.now(UTC),
            },
        )
    )
    await session.execute(stmt)


async def backfill_cerif(
    session: AsyncSession, uuid: str, cerif: dict[str, Any], *, institution_id: int
) -> None:
    """Backfill cerif-derived fields onto an existing work; never nulls.

    doi_normalized is UNIQUE across works and cerif records can repeat a
    DOI another uuid already claimed, so the DOI is only set when free.
    """
    values: dict[str, Any] = {"updated_at": datetime.now(UTC)}
    if issn := _dc_first(cerif.get("issn")):
        values["cerif_issn"] = issn
    if publisher := _dc_first(cerif.get("publisher")):
        values["publisher"] = publisher
    if oa := canonical_access(_dc_first(cerif.get("oa_status"))):
        values["oa_status"] = oa
    if doi := extract_doi(cerif.get("doi") or ""):
        owner = await session.scalar(
            select(Work.pure_uuid).where(
                Work.institution_id == institution_id,
                Work.doi_normalized == doi,
                Work.pure_uuid != uuid,
            )
        )
        if owner is None:
            values["doi_normalized"] = doi
    if len(values) == 1:
        return
    from sqlalchemy import update

    await session.execute(
        update(Work)
        .where(Work.institution_id == institution_id, Work.pure_uuid == uuid)
        .values(**values)
    )


async def _ingest_oai_record(
    ingest: IngestSession,
    record: ET.Element,
    *,
    institution_id: int,
    year: int,
    run_id: int,
    entity_type: str,
) -> str:
    """Store one <record> verbatim + upsert the canonical row; returns kind."""
    oai_identifier, datestamp, set_specs, status = _header_fields(record)
    if status == "deleted":
        # deletedRecord=no on this endpoint, so a deleted header is an anomaly.
        ingest.parse_failures += 1
        ingest.records_seen += 1
        logger.warning(
            "deleted record header on endpoint with deletedRecord=no: %s (%s)",
            oai_identifier,
            datestamp,
        )
        return "deleted"
    _, payload = record_payload(record)
    if entity_type == "work_cerif":
        metadata = record.find(oai_tag("metadata"))
        cerif = _cerif_publication_fields(metadata)
        if cerif:
            payload["cerif"] = cerif
    kind, _ = await ingest.ingest_record(oai_identifier, payload)
    if entity_type == "work":
        await upsert_work(
            ingest.session, payload, institution_id=institution_id, year=year, run_id=run_id
        )
    elif entity_type == "work_cerif" and payload.get("cerif"):
        await backfill_cerif(
            ingest.session,
            pure_uuid_for(oai_identifier),
            payload["cerif"],
            institution_id=institution_id,
        )
    return kind


# ── Set harvest (producer/consumer, per-page commit) ─────────────────────────

# Producer->consumer queue item: (records, token progress attrs) per page;
# None is the end sentinel.
PageItem = tuple[list[ET.Element], dict[str, str]] | None


async def _produce_oai_pages(
    base_url: str,
    base_params: dict[str, str],
    set_spec: str,
    pacer: Pacer,
    stats: dict[str, Any],
    queue: asyncio.Queue[PageItem],
) -> None:
    """Drive the resumption chain onto the queue; restart on badResumptionToken."""
    try:
        for attempt in range(MAX_TOKEN_RESTARTS + 1):
            try:
                async for page, token_attrs in _oai_pages(
                    base_url, "ListRecords", base_params, "record", pacer
                ):
                    await queue.put((page, token_attrs))
                return
            except PureOaiError as exc:
                if exc.code != "badResumptionToken" or attempt == MAX_TOKEN_RESTARTS:
                    raise
                stats["token_restarts"] += 1
                logger.warning(
                    "badResumptionToken on set %s (attempt %s); restarting set",
                    set_spec,
                    attempt + 1,
                )
    finally:
        task = asyncio.current_task()
        if task is not None and task.cancelling() == 0:
            await queue.put(None)


async def _consume_oai_pages(
    ingest: IngestSession,
    queue: asyncio.Queue[PageItem],
    stats: dict[str, Any],
    *,
    institution_id: int,
    year: int,
    entity_type: str,
    limit: int | None,
) -> None:
    """Parse + ingest a page, then commit it (a crash loses at most one page)."""
    while True:
        item = await queue.get()
        if item is None:
            break
        page, token_attrs = item
        stats["pages"] += 1
        if token_attrs.get("complete_list_size", "").isdigit():
            stats["complete_list_size"] = int(token_attrs["complete_list_size"])
        limit_reached = False
        for record in page:
            try:
                kind = await _ingest_oai_record(
                    ingest,
                    record,
                    institution_id=institution_id,
                    year=year,
                    run_id=ingest.run_id,
                    entity_type=entity_type,
                )
            except (PureOaiError, ET.ParseError) as exc:
                # Record-level parse problems leave the session healthy;
                # DB-level errors must propagate (the transaction is dead).
                await ingest.record_parse_failure(
                    {"source_pk": None, "reason": f"{type(exc).__name__}: {exc}"}
                )
                continue
            stats[kind] += 1
            if limit is not None and ingest.records_seen >= limit:
                stats["limit_reached"] = True
                limit_reached = True
                break
        await ingest.commit()
        if limit_reached:
            break


async def _harvest_set(
    ingest: IngestSession,
    set_spec: str,
    metadata_prefix: str,
    *,
    base_url: str,
    institution_id: int,
    from_date: str | None = None,
    until_date: str | None = None,
    limit: int | None = None,
    pacer: Pacer | None = None,
) -> dict[str, Any]:
    """ListRecords over one set with resumption; restart on badResumptionToken."""
    settings = get_settings()
    pacer = pacer or Pacer(settings.pure_oai_min_spacing)
    base_params = {"metadataPrefix": metadata_prefix, "set": set_spec}
    if from_date:
        base_params["from"] = from_date
    if until_date:
        base_params["until"] = until_date

    stats: dict[str, Any] = {
        "pages": 0,
        "token_restarts": 0,
        "new": 0,
        "duplicate": 0,
        "deleted": 0,
        "complete_list_size": None,
    }
    queue: asyncio.Queue[PageItem] = asyncio.Queue(maxsize=3)
    prod = asyncio.create_task(
        _produce_oai_pages(base_url, base_params, set_spec, pacer, stats, queue)
    )
    year = year_for_set(set_spec) or 0
    cons = asyncio.create_task(
        _consume_oai_pages(
            ingest,
            queue,
            stats,
            institution_id=institution_id,
            year=year,
            entity_type=ingest.entity_type or "work",
            limit=limit,
        )
    )
    try:
        await cons
    finally:
        if not prod.done():
            prod.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await prod
    if not prod.cancelled():
        exc = prod.exception()
        if exc is not None:
            raise exc
    return stats


# ── Retirement (full re-baseline; Pure reports no deletes) ──────────────────


async def retire_absent(session: AsyncSession, run_ids: list[int], institution_id: int) -> int:
    """Mark the institution's works not seen in any of these sweep runs as retired.

    Never deletes. A no-run call is a no-op: `NOT IN ()` would retire
    every row.
    """
    if not run_ids:
        return 0
    from sqlalchemy import update

    result = await session.execute(
        update(Work)
        .where(
            Work.institution_id == institution_id,
            Work.last_seen_run.not_in(run_ids),
            Work.retired_at.is_(None),
        )
        .values(retired_at=datetime.now(UTC))
    )
    return result.rowcount or 0


# ── Job entry points ─────────────────────────────────────────────────────────


async def harvest_pure_years(
    session: AsyncSession,
    institution,
    years: list[int],
    *,
    limit: int | None = None,
    full_sweep: bool = False,
) -> dict[str, Any]:
    """Harvest one institution's publications:year{Y} sets (oai_dc) into
    source_records + works.

    One harvest_run per year set. full_sweep=True covers every window year
    of the institution in one go and retires works absent from the sweep
    afterwards — so `years` MUST span the whole window, or retirement would
    stamp works that were simply not part of this (partial) run.
    """
    base_url = institution.pure_oai_base_url
    if not base_url:
        raise ValueError(f"institution {institution.code!r} has no pure_oai_base_url")
    if full_sweep:
        expected = set(institution.window_years)
        if set(years) != expected:
            raise ValueError(
                f"full_sweep requires every window year {sorted(expected)}, got {sorted(years)}"
            )
    stats: dict[str, Any] = {"sets": {}}
    totals = {"records_seen": 0, "records_stored": 0, "parse_failures": 0}
    run_ids: list[int] = []
    for year in years:
        set_spec = DEFAULT_YEAR_SET.format(year=year)
        ingest = IngestSession(session)
        config = {
            "base_url": base_url,
            "metadata_prefix": PREFIX_DC,
            "full_sweep": full_sweep,
        }
        await ingest.start_run(SOURCE, "work", set_spec, config, institution_id=institution.id)
        run_ids.append(ingest.run_id)
        try:
            set_stats = await _harvest_set(
                ingest,
                set_spec,
                PREFIX_DC,
                base_url=base_url,
                institution_id=institution.id,
                limit=limit,
            )
        except Exception as exc:
            # Commit the failed-run marker: finish_run only flushes, and the
            # re-raise would otherwise roll the run row back into nothing.
            await ingest.finish_run("failed", {"error": f"{type(exc).__name__}: {exc}"[:200]})
            with contextlib.suppress(Exception):
                await session.commit()
            raise
        final = await ingest.finish_run("completed", set_stats)
        await ingest.commit()
        stats["sets"][set_spec] = final
        for key in totals:
            totals[key] += final.get(key, 0) or 0
    # Retirement is only sound against the runs of THIS sweep: per-year sets
    # each get their own harvest_run, so retiring against only the last run
    # would retire every other year.
    stats["retired"] = (
        await retire_absent(session, run_ids, institution.id) if full_sweep else 0
    )
    await session.commit()
    stats.update(totals)
    return stats


async def harvest_pure_cerif(
    session: AsyncSession,
    institution,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Enrichment pass: openaire_cris_publications over oai_cerif_openaire.

    Stores records verbatim (entity_type=work_cerif) and backfills
    cerif_issn/publisher/doi/oa_status onto matching works rows.
    """
    base_url = institution.pure_oai_base_url
    if not base_url:
        raise ValueError(f"institution {institution.code!r} has no pure_oai_base_url")
    ingest = IngestSession(session)
    config = {"base_url": base_url, "metadata_prefix": PREFIX_CERIF}
    await ingest.start_run(
        SOURCE, "work_cerif", CRIS_PUBLICATIONS_SET, config, institution_id=institution.id
    )
    try:
        set_stats = await _harvest_set(
            ingest,
            CRIS_PUBLICATIONS_SET,
            PREFIX_CERIF,
            base_url=base_url,
            institution_id=institution.id,
            limit=limit,
        )
    except Exception as exc:
        await ingest.finish_run("failed", {"error": f"{type(exc).__name__}: {exc}"[:200]})
        with contextlib.suppress(Exception):
            await session.commit()
        raise
    final = await ingest.finish_run("completed", set_stats)
    await ingest.commit()
    return final
