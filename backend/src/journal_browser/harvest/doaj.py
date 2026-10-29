"""DOAJ journal canon: the authoritative OA-model registry, via the CSV.

DOAJ publishes the full journal set as one CSV (the search API caps
pagination at 1,000 records). The file lands verbatim in the landing store,
then every row denormalizes onto journals by ISSN match (print/eISSN
against journals.issn_l and journals.issns). DOAJ's own APC declaration
becomes the gold/diamond canon, and its journal URL the canon homepage.

After a successful full parse, OA candidates without a match stamp
doaj_in_doaj=false, so NULL means "never swept" and classification only
trusts swept rows.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Text, bindparam, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Journal
from .common import (
    HarvestDataError,
    download_to_landing,
    issn_checksum_ok,
    normalize_issn,
    parse_csv_rows,
    require_headers,
    run_harvest,
)

logger = logging.getLogger(__name__)

SOURCE = "doaj"
ENTITY_TYPE = "journal"
CSV_URL = "https://doaj.org/csv"

_C = {
    "title": "Journal title",
    "homepage_url": "Journal URL",
    "pissn": "Journal ISSN (print version)",
    "eissn": "Journal EISSN (online version)",
    "publisher": "Publisher",
    "apc": "APC",
    "apc_amount": "APC amount",
}


def journal_fields(row: dict[str, str]) -> dict[str, Any] | None:
    """Normalize one CSV row into journals column values; None without any
    checksum-valid ISSN (nothing to match on)."""
    issns = [
        i
        for i in (normalize_issn(row.get(_C[k])) for k in ("pissn", "eissn"))
        if i and issn_checksum_ok(i)
    ]
    if not issns:
        return None
    has_apc = (row.get(_C["apc"]) or "").strip().lower() == "yes"
    apc_max = apc_currency = None
    if has_apc:
        # "<amount> <CURRENCY>", occasionally several joined by ';'; the
        # first declaration is the display charge.
        parts = (row.get(_C["apc_amount"]) or "").split(";")[0].split()
        if len(parts) == 2 and parts[0].replace(".", "", 1).isdigit():
            apc_max, apc_currency = float(parts[0]), parts[1][:3].upper()
    return {
        "homepage_url": (row.get(_C["homepage_url"]) or "").strip() or None,
        "has_apc": has_apc,
        "apc_max": apc_max,
        "apc_currency": apc_currency,
        "issns": issns,
    }


async def _stamp_not_listed(session: AsyncSession) -> int:
    """OA candidates that a complete sweep never matched: not in DOAJ."""
    result = await session.execute(
        Journal.__table__.update()
        .where(
            Journal.__table__.c.doaj_in_doaj.is_(None),
            (Journal.__table__.c.is_oa.is_(True))
            | (Journal.__table__.c.is_in_doaj.is_(True)),
        )
        .values(doaj_in_doaj=False)
    )
    return result.rowcount or 0


async def _apply_rows(session: AsyncSession, fields_list: list[dict[str, Any]]) -> int:
    """Denormalize parsed rows onto journals; returns matched journals."""
    all_issns = {i for f in fields_list for i in f["issns"]}
    ordered = sorted(all_issns)
    matched: dict[str, dict[str, Any]] = {}
    # asyncpg caps query arguments at 32,767: the in_() list must chunk.
    for at in range(0, len(ordered), 20_000):
        chunk = ordered[at : at + 20_000]
        # jsonb ?| needs an explicitly typed text[]; a bare list binds as jsonb.
        variants = bindparam("variant_issns", chunk, type_=ARRAY(Text))
        rows = (
            await session.execute(
                select(Journal.issn_l, Journal.issns).where(
                    Journal.issn_l.in_(chunk) | Journal.issns.op("?|")(variants)
                )
            )
        ).all()
        for issn_l, issns in rows:
            if issn_l in matched:
                continue
            # A record matches via its own ISSNs or any journal variant ISSN.
            fields = next(
                (
                    f
                    for f in fields_list
                    if issn_l in f["issns"] or set(issns or ()) & set(f["issns"])
                ),
                None,
            )
            if fields is not None:  # pragma: no branch - defensive
                matched[issn_l] = fields
    now = datetime.now(UTC)
    params = [
        dict(
            b_issn_l=issn_l,
            b_has_apc=f["has_apc"],
            b_apc_max=f["apc_max"],
            b_apc_currency=f["apc_currency"],
            b_homepage=f["homepage_url"],
            b_now=now,
        )
        for issn_l, f in matched.items()
    ]
    if params:
        await session.execute(
            Journal.__table__.update()
            .where(Journal.__table__.c.issn_l == bindparam("b_issn_l"))
            .values(
                doaj_in_doaj=True,
                doaj_has_apc=bindparam("b_has_apc"),
                doaj_apc_max=bindparam("b_apc_max"),
                doaj_apc_currency=bindparam("b_apc_currency"),
                doaj_homepage_url=bindparam("b_homepage"),
                doaj_harvested_at=bindparam("b_now"),
            ),
            params,
        )
    return len(params)


async def harvest_doaj(session: AsyncSession) -> dict[str, Any]:
    """Download the DOAJ journal CSV and denormalize it onto journals."""

    async def body(ingest) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        data, _ = await download_to_landing(
            session, ingest, SOURCE, ENTITY_TYPE, CSV_URL, ".csv", source_pk="journals"
        )
        rows = parse_csv_rows(data)
        require_headers(rows, set(_C.values()), "doaj journals")
        fields_list = [f for row in rows if (f := journal_fields(row))]
        if not fields_list:
            raise HarvestDataError("DOAJ CSV parsed to zero ISSN-bearing rows")
        matched = await _apply_rows(session, fields_list)
        stamped = await _stamp_not_listed(session)
        return {
            "rows": len(rows),
            "issn_rows": len(fields_list),
            "journals_matched": matched,
            "stamped_not_listed": stamped,
        }

    return await run_harvest(SOURCE, ENTITY_TYPE, "all", {"csv": CSV_URL}, body, session)
