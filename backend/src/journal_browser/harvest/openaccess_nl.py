"""openaccess.nl harvester: overview page -> publisher pages -> deal pages.

Drupal site without a JSON API; we collect raw HTML into the landing store
before parsing anything (docs/research/openaccess-nl.md). Deal pages are the
source_records; overview/publisher pages are landing copies only. JCT linking
is deliberately NOT done here (reconcile job owns that).
"""

import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ingest import IngestSession, apply_overrides
from ..models import Deal, Publisher
from .common import download_to_landing, run_harvest

logger = logging.getLogger(__name__)

# Deal fields this source rewrites on every scrape; ManualOverride rows
# (admin edits via /admin/deals) win over the scraped value.
_DEAL_FIELDS = [
    "status",
    "start_year",
    "end_year",
    "cap_text",
    "cap_numbers",
    "summary",
    "needs_curation",
    "needs_curation_reason",
]

SOURCE = "openaccess.nl"
BASE_URL = "https://www.openaccess.nl"
OVERVIEW_URL = f"{BASE_URL}/en/publishing/publisher-deals"

_DURATION_RE = re.compile(r"^(20\d{2})(?:\s*[-–/]\s*(20\d{2}))?$")
_YEAR_COUNT_RE = re.compile(r"^(19\d{2}|20\d{2})$")
_COUNT_RE = re.compile(r"\b(\d{2,5})\b")
# Pooling words between a number and its year mean the number spans several
# years ("500 in total for both 2025 and 2026") -> no per-year assignment.
_CAP_POOLING_RE = re.compile(r"\b(total|both|across|combined|shared|between)\b", re.IGNORECASE)
_ARTICLE_TYPES_RE = re.compile(
    r"article\s+types?|publication\s+types?|types?\s+of\s+(?:publications?|articles?)",
    re.IGNORECASE,
)
_CAP_SENTENCE_RE = re.compile(r"cap", re.IGNORECASE)
_MAX_SENTENCE_RE = re.compile(r"maximum", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _text(el: Any) -> str:
    """Element text as lines, blank lines dropped (one line per list item)."""
    lines = [line.strip() for line in el.get_text("\n", strip=True).split("\n")]
    return "\n".join(line for line in lines if line)


def parse_duration(text: str | None) -> tuple[int | None, int | None]:
    """'2025-2027' -> (2025, 2027); '2025' -> (2025, 2025); else (None, None)."""
    if not text:
        return None, None
    m = _DURATION_RE.match(text.strip())
    if not m:
        return None, None
    start = int(m.group(1))
    return start, int(m.group(2)) if m.group(2) else start


def parse_overview(html: str) -> list[dict[str, str]]:
    """Current + archive publisher rows from the overview tabs."""
    soup = _soup(html)
    out: list[dict[str, str]] = []
    for pane in soup.select(".tab-pane"):
        status = "current" if pane.get("id") == "current" else "archive"
        for row in pane.select("tr.row-header"):
            link = row.select_one("td.views-field-title a[href]")
            dur = row.select_one("td.views-field-field-looptijd-deal")
            if link is None or dur is None:
                continue
            href = link["href"]
            out.append(
                {
                    "slug": href.rstrip("/").rsplit("/", 1)[-1],
                    "name": link.get_text(strip=True),
                    "duration_text": dur.get_text(strip=True),
                    "status": status,
                }
            )
    return out


def parse_publisher_page(html: str) -> list[dict[str, Any]]:
    """licence-data-item blocks -> one entry per historical deal."""
    soup = _soup(html)
    deals: list[dict[str, Any]] = []
    for item in soup.select(".licence-data-item"):
        duration_text = None
        per_year: dict[str, int] = {}
        status: str | None = None
        for tr in item.select("table tr"):
            th = tr.find("th")
            td = tr.find("td")
            if th is None or td is None:
                continue
            label = th.get_text(strip=True).rstrip(":")
            value = td.get_text(strip=True)
            if label == "Deal duration":
                duration_text = value
            elif _YEAR_COUNT_RE.match(label) and value.isdigit():
                per_year[label] = int(value)
            elif label == "Status licence" and value.lower() in ("current", "archive"):
                status = value.lower()
        link = item.select_one("a.licence-data-item__read-more[href]")
        if duration_text is None or status is None or link is None:
            logger.warning("skipping incomplete licence-data-item (duration=%s)", duration_text)
            continue
        start_year, end_year = parse_duration(duration_text)
        deals.append(
            {
                "duration_text": duration_text,
                "start_year": start_year,
                "end_year": end_year,
                "per_year_oa_counts": per_year or None,
                "status": status,
                "deal_path": link["href"],
            }
        )
    return deals


def _marker_label(el: Any) -> str | None:
    """Section markers are <p><em><strong>Title</strong></em>...</p> paragraphs.

    Trailing junk after the strong text is tolerated (De Gruyter writes
    'License and conditions :'), and titles are canonicalized: AIP uses
    'Details and conditions of the licence'.
    """
    if el.name != "p":
        return None
    em = el.find("em")
    if em is None or em.find("strong") is None:
        return None
    label = em.find("strong").get_text(strip=True).rstrip(":?.! ").strip().lower()
    rest = re.sub(re.escape(label), "", el.get_text(strip=True), count=1, flags=re.IGNORECASE)
    if rest.strip(":?.! "):
        return None  # real content, not a bare marker
    if "condition" in label:
        return "license and conditions"
    if label.startswith("how does it work"):
        return "how does it work"
    return label


def _page_sections(soup: BeautifulSoup) -> tuple[str | None, dict[str, list[str]]]:
    """Flatten node content body-text children into (summary, {section: [lines]})."""
    summary: str | None = None
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for body in soup.select("div.body-text"):
        if "node__content" not in (body.parent.get("class") or []):
            continue
        for child in body.find_all(["p", "ul", "ol", "table"], recursive=False):
            label = _marker_label(child)
            if label is not None:
                current = label
                continue
            text = _text(child)
            if not text:
                continue
            if current is None and child.name == "p" and summary is None:
                summary = text
            else:
                sections.setdefault(current or "", []).append(text)
    return summary, sections


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.replace("\n", " ")) if s.strip()]


def _pair_year(
    line: str, count: tuple[int, int, int], years: list[tuple[int, int, int]]
) -> str | None:
    """Year a count belongs to: '<count> in <year>' first, else previous year."""
    start, end, _ = count
    for ystart, _yend, value in years:
        if ystart >= end:  # nearest following year: "<count> in <year>"
            gap = line[end:ystart]
            if (
                len(gap) <= 25
                and not set(gap) & {",", ".", ";", ":"}
                and not _CAP_POOLING_RE.search(gap)
            ):
                return str(value)
            break
    for _ystart, yend, value in reversed(years):
        if yend <= start:  # nearest previous year: "In <year>, ... <count>"
            gap = line[yend:start]
            if len(gap) <= 80 and "." not in gap and not _CAP_POOLING_RE.search(gap):
                return str(value)
            break
    return None


def _extract_cap(lines: list[str]) -> tuple[dict[str, int] | None, bool, list[str]]:
    """(cap_numbers, ambiguous, cap_sentences) from cap/maximum lines.

    Pairing runs per list-item line (cap sentences may continue across
    sentence boundaries, e.g. "... of 733 articles. In 2025, ... 707 ...").
    Two different counts claiming the same year, or counts+years with no
    clean pairing, count as ambiguous -> needs_curation, no fabricated dict.
    shortcut: "week 42 in 2025"-style week numbers would pair wrongly; upgrade
    only if such phrasing ever appears on openaccess.nl.
    """
    cap_lines = [ln for ln in lines if _CAP_SENTENCE_RE.search(ln) or _MAX_SENTENCE_RE.search(ln)]
    numbers: dict[str, int] = {}
    ambiguous = False
    for line in cap_lines:
        tokens = [(m.start(), m.end(), int(m.group(1))) for m in _COUNT_RE.finditer(line)]
        years = [t for t in tokens if 1900 <= t[2] <= 2099]
        counts = [t for t in tokens if not 1900 <= t[2] <= 2099 and t[2] >= 20]
        if not years or not counts:
            continue
        pairs: dict[str, int] = {}
        for count in counts:
            year = _pair_year(line, count, years)
            if year is None:
                continue
            if pairs.get(year, count[2]) != count[2]:
                ambiguous = True
            pairs[year] = count[2]
        if not pairs:
            ambiguous = True  # counts and years present but nothing paired cleanly
        numbers.update(pairs)
    cap_sentences = [s for ln in cap_lines for s in _sentences(ln)]
    return (numbers or None), ambiguous, cap_sentences


def parse_deal_page(html: str, url: str) -> dict[str, Any]:
    """Deal page -> structured payload (collect-only; no fabrication)."""
    soup = _soup(html)
    summary, sections = _page_sections(soup)
    conditions_lines = sections.get("license and conditions", [])
    workflow_lines = sections.get("how does it work", [])
    conditions_text = "\n".join(conditions_lines) or None
    workflow_text = "\n".join(workflow_lines) or None

    sentences = _sentences(conditions_text) if conditions_text else []
    article_types_text = " ".join(s for s in sentences if _ARTICLE_TYPES_RE.search(s)) or None
    cap_numbers, cap_ambiguous, cap_sentences = _extract_cap(conditions_lines)
    cap_text = " ".join(cap_sentences) or None

    contract_url = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ".pdf" not in href.lower():
            continue
        absolute = urljoin(url, href)
        host = absolute.split("/")[2].lower()
        if host in ("www.openaccess.nl", "openaccess.nl"):
            contract_url = absolute
            break

    reasons: list[str] = []
    if not summary:
        reasons.append("missing summary")
    if conditions_text is None:
        reasons.append("missing 'License and conditions' section")
    if workflow_text is None:
        reasons.append("missing 'How does it work?' section")
    if cap_ambiguous:
        reasons.append("ambiguous cap numbers")

    return {
        "url": url,
        "summary": summary,
        "conditions_text": conditions_text,
        "workflow_text": workflow_text,
        "article_types_text": article_types_text,
        "cap_text": cap_text,
        "cap_numbers": cap_numbers,
        "contract_url": contract_url,
        "openaccess_nl_url": url,
        "curation_reasons": reasons,
    }


async def _upsert_publisher(session: AsyncSession, slug: str, name: str) -> Publisher:
    pub = await session.scalar(select(Publisher).where(Publisher.openaccess_nl_slug == slug))
    if pub is None:
        pub = await session.scalar(select(Publisher).where(Publisher.name == name))
        if pub is None:
            pub = Publisher(name=name, openaccess_nl_slug=slug)
            session.add(pub)
        else:
            pub.openaccess_nl_slug = slug
        await session.flush()
    return pub


async def _upsert_deal(
    session: AsyncSession, publisher_id: int, item: dict[str, Any], page: dict[str, Any]
) -> bool:
    """Upsert by natural key (publisher, duration). Returns needs_curation."""
    deal = await session.scalar(
        select(Deal).where(
            Deal.publisher_id == publisher_id,
            Deal.duration_text == item["duration_text"],
        )
    )
    needs_curation = bool(page["curation_reasons"])
    values = {
        "status": item["status"],
        "start_year": item["start_year"],
        "end_year": item["end_year"],
        "summary": page["summary"],
        "conditions_text": page["conditions_text"],
        "workflow_text": page["workflow_text"],
        "article_types_text": page["article_types_text"],
        "cap_text": page["cap_text"],
        "cap_numbers": page["cap_numbers"],
        "contract_url": page["contract_url"],
        "openaccess_nl_url": page["openaccess_nl_url"],
        "per_year_oa_counts": item["per_year_oa_counts"],
        "provenance": [
            {
                "source": SOURCE,
                "url": page["url"],
                "fetched_at": datetime.now(UTC).isoformat(),
            }
        ],
        "needs_curation": needs_curation,
        "needs_curation_reason": "; ".join(page["curation_reasons"]) or None,
    }
    if deal is None:
        deal = Deal(publisher_id=publisher_id, duration_text=item["duration_text"], **values)
        session.add(deal)
        await session.flush()  # id needed for the override row_key
    else:
        for key, value in values.items():
            setattr(deal, key, value)
    await apply_overrides(session, "deals", str(deal.id), deal, _DEAL_FIELDS)
    return needs_curation


def _body(limit: int | None):
    async def body(ingest: IngestSession) -> dict[str, Any]:
        session = ingest.session
        stats = {"publishers": 0, "deals_parsed": 0, "needs_curation": 0}

        data, _ = await download_to_landing(
            session, ingest, SOURCE, "overview", OVERVIEW_URL, ".html", source_pk="overview"
        )
        # Current pane first, then archive-only publishers (cheap: same crawl).
        # Slugs can appear in both panes — keep the first (current) entry.
        pubs: dict[str, dict[str, str]] = {}
        for pub in parse_overview(data.decode("utf-8", errors="replace")):
            pubs.setdefault(pub["slug"], pub)
        selected = list(pubs.values())
        if limit is not None:
            selected = selected[:limit]

        # Politeness: strictly sequential — one request at a time, fetch_bytes already retries.
        for pub in selected:
            publisher_url = f"{BASE_URL}/en/publisher/{pub['slug']}"
            try:
                data, _ = await download_to_landing(
                    session,
                    ingest,
                    SOURCE,
                    "publisher",
                    publisher_url,
                    ".html",
                    source_pk=pub["slug"],
                )
                items = parse_publisher_page(data.decode("utf-8", errors="replace"))
            except Exception as exc:
                await ingest.record_parse_failure(
                    {"source_pk": pub["slug"], "reason": f"publisher page: {exc}"}
                )
                await ingest.commit()
                continue
            stats["publishers"] += 1
            try:
                publisher = await _upsert_publisher(session, pub["slug"], pub["name"])
            except Exception as exc:
                await ingest.record_parse_failure(
                    {"source_pk": pub["slug"], "reason": f"publisher upsert: {exc}"}
                )
                await ingest.commit()
                continue
            for item in items:
                deal_url = urljoin(BASE_URL, item["deal_path"])
                deal_pk = item["deal_path"].rstrip("/").rsplit("/", 1)[-1]
                try:
                    data, _ = await download_to_landing(
                        session, ingest, SOURCE, "deal", deal_url, ".html", source_pk=deal_pk
                    )
                    page = parse_deal_page(data.decode("utf-8", errors="replace"), deal_url)
                    await ingest.ingest_record(deal_pk, {**page, "publisher_slug": pub["slug"]})
                    if await _upsert_deal(session, publisher.id, item, page):
                        stats["needs_curation"] += 1
                    stats["deals_parsed"] += 1
                except Exception as exc:
                    await ingest.record_parse_failure(
                        {"source_pk": deal_pk, "reason": f"deal page: {exc}"}
                    )
            await ingest.commit()
        return stats

    return body


async def harvest(session: AsyncSession, limit: int | None = None) -> dict[str, Any]:
    """Run the full openaccess.nl scrape."""
    return await run_harvest(
        SOURCE, "deal", "all", {"url": OVERVIEW_URL, "limit": limit}, _body(limit), session
    )
