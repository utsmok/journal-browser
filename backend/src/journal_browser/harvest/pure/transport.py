import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator

import httpx

from ..common import RETRY_STATUS, retry_delay

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
