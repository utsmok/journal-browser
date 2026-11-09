"""people.utwente.nl profile harvest: match authors, scrape, gap-fill.

For each author of the institution the directory's own JSON-RPC search
is queried (the same call its search UI makes; no cookie wall), the
result tiles are name-gated, and the best candidates' profile pages are
scraped. The decisive signal is the profile's public Pure portal link:
research.utwente.nl/en/persons/<pure uuid> — when that uuid equals the
author's pure uuid the match is verified outright ('matched', served on
the author page). A same-named page whose portal uuid differs belongs to
someone else ('missed'). A name-gated page without a portal link cannot
be verified and lands as 'candidate' for admin review via
author_identities source='people'.

Scraped orgs of matched profiles are resolved onto pure_orgs into
people_utwente_person_orgs — gap-fill evidence only (the
pure_person_orgs contract): derive consults it through dedicated arms
after native CERIF resolution and never overrides a native result.

Portrait bytes (the tile is the only place the URL appears without a
detail fetch) are downloaded for matched/candidate rows only:
*.utwente.nl over https, ≤1 MB, magic-byte sniffed PNG/JPEG/AVIF — the
directory serves AVIF only (no content negotiation; probed 2026-10-02
in ea-cli-refactor, re-verified live 2026-11-09).

Idempotent: authors with any people row are skipped (--retry-missed
re-attempts missed rows, --refresh re-attempts all); candidate identity
rows never overwrite admin decisions.
"""

import asyncio
import logging
import re
import urllib.parse
from datetime import UTC
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ingest import IngestSession
from ..models import (
    Author,
    AuthorIdentity,
    Institution,
    PeopleUtwentePerson,
    PeopleUtwentePersonOrg,
)
from .org_closure import load_org_tree
from .pure_portal import name_key  # org-tree match key (pure_portal_persons contract)
from .pure_portal_persons import match_org_name, org_bare_key, person_name_key, person_name_keys

logger = logging.getLogger(__name__)

PEOPLE_BASE_URL = "https://people.utwente.nl/"
RPC_URL = PEOPLE_BASE_URL + "wh_services/utwente_ppp/rpc/"
RESEARCH_PORTAL_URL = "https://research.utwente.nl"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

#: Tile pattern per the directory's SearchPersons fragment.
_PARENS_RE = re.compile(r"\([^)]*\)")

#: Dutch name particles dropped before initials comparison (tile and
#: author names disagree on particle casing only).
_PARTICLES = frozenset({"de", "van", "den", "der", "het", "ter", "te", "ten", "van het"})

#: Faculty abbreviations the org linklist uses to tag the faculty row
#: (the same five the directory itself distinguishes).
FACULTY_ABBS = frozenset({"BMS", "ET", "EEMCS", "ITC", "TNW"})

#: Name-gated candidates whose detail pages may be fetched per author.
MAX_DETAIL_FETCHES = 5

#: Portrait cap (avatar budget) and image magic sniffing.
MAX_AVATAR_BYTES = 1_000_000

#: Sleep between authors / between detail fetches of one author.
PACE_SECONDS = 0.5
DETAIL_PACE_SECONDS = 0.2


# ── Parsing (pure functions) ───────────────────────────────────────────────


def tile_clean_name(raw: str) -> str:
    """Tile title "Jong, J.J. de (Jan)" → match key "jj de jong":
    parenthesized common name stripped, "Last, First" reordered, then the
    shared person name_key (folded, punct → space, lowercased)."""
    name = _PARENS_RE.sub("", raw).strip()
    if "," in name:
        parts = name.split(",")
        name = " ".join(part.strip() for part in reversed(parts) if part.strip())
    return person_name_key(name)


def tile_common_name(raw: str) -> str | None:
    """The parenthesized common name "Jan" from a tile title, or None."""
    match = re.search(r"\(([^)]+)\)", raw)
    return match.group(1).strip().casefold() if match else None


def _initials_key(key: str) -> tuple[str, str]:
    """(given-name initials, surname) after dropping particles.

    person_name_key keeps initials as single-char tokens ("J.J. de" →
    "j j de jong"), so given-name initials are the first letters of every
    token before the surname: "j j de jong" → ("jj", "jong"), "jan de
    jong" → ("j", "jong"), "a h boekhout" → ("ah", "boekhout")."""
    tokens = [t for t in key.split() if t not in _PARTICLES]
    if not tokens:
        return "", ""
    surname = tokens[-1]
    return "".join(t[0] for t in tokens[:-1]), surname


def name_match_tier(author_key: str, author_reversed_key: str, tile: dict[str, Any]) -> int:
    """0 = no name match, 1 = initials-compatible, 2 = exact key match.

    Initials tier: particle-stripped surname tails equal and the initials
    strings equal or the author's a prefix of the tile's (tiles may carry
    middle initials the roster name lacks). The parenthesized common name
    ("Jong, J.J. de (Jan)") must equal the author's first given token
    when the tile carries initials — "jj" alone would match any J.
    """
    tile_key = str(tile.get("name_clean") or "")
    if not tile_key:
        return 0
    if tile_key in (author_key, author_reversed_key):
        return 2
    tile_initials, tile_surname = _initials_key(tile_key)
    for key in (author_key, author_reversed_key):
        init, surname = _initials_key(key)
        if not surname or tile_surname != surname:
            continue
        # Tiles may carry middle initials the roster name lacks: the
        # author's given initials must equal the tile's or be its prefix.
        if tile_initials == init or (init and tile_initials.startswith(init)):
            common = tile.get("common_name")
            if common and init != tile_initials:
                # Initials differ beyond the author's name: only accept
                # when the tile's common name ("Jong, J.J. de (Jan)")
                # names the author's first given token.
                first = author_key.split()[0] if author_key else ""
                if common != first:
                    continue
            return 1
    return 0


def parse_tiles(results_html: str) -> list[dict[str, Any]]:
    """Every person tile of a SearchPersons results fragment, document
    order (≤10): title, name_clean, common_name, slug, url, photo_url,
    org_abbrs (the tile's org abbreviation lines)."""
    from bs4 import Tag

    soup = _soup(results_html)
    tiles: list[dict[str, Any]] = []
    for tile in soup.find_all("div", class_="ut-person-tile")[:10]:
        if not isinstance(tile, Tag):
            continue
        title_el = tile.find("h3", class_="ut-person-tile__title")
        if not title_el or not isinstance(title_el, Tag):
            continue
        raw_name = title_el.get_text(strip=True)
        clean = tile_clean_name(raw_name)
        if not clean:
            continue
        slug = tile.get("data-link")
        if not slug:
            continue
        photo_el = tile.find("img", class_="ut-person-tile__image")
        photo_src = photo_el.get("src") if isinstance(photo_el, Tag) else None
        org_abbrs = [
            line.strip()
            for org_el in tile.find_all(class_="ut-person-tile__orgs")
            for line in org_el.get_text().splitlines()
            if line.strip()
        ]
        tiles.append(
            {
                "name": raw_name,
                "name_clean": clean,
                "common_name": tile_common_name(raw_name),
                "slug": str(slug),
                "url": urllib.parse.urljoin(PEOPLE_BASE_URL, str(slug)),
                "photo_url": urllib.parse.urljoin(PEOPLE_BASE_URL, str(photo_src))
                if photo_src
                else None,
                "org_abbrs": org_abbrs,
            }
        )
    return tiles


def parse_profile(html: str, tile: dict[str, Any]) -> dict[str, Any]:
    """Scrape one profile page into the stored shape: canonical name
    (h1 + common-name suffix), mailto email, org linklist (faculty row
    first), portal person URL, photo url (tile fallback)."""
    from bs4 import Tag

    soup = _soup(html)

    canonical = None
    header = soup.find("h1", class_="pageheader__title")
    if isinstance(header, Tag):
        # Title + common-name suffix are separate spans; join with space
        # ("dr. J.J. de Jong (Jan)", not "de Jong(Jan)").
        canonical = " ".join(part.strip() for part in header.stripped_strings) or None

    email = None
    for a in soup.find_all("a"):
        href = a.get("href") or ""
        if str(href).startswith("mailto:"):
            email = str(href).removeprefix("mailto:").strip() or None
            break

    orgs: list[dict[str, str | None]] = []
    faculty_abbr = None
    containers = soup.find_all(class_="widget-linklist--smallicons")
    if containers:
        for a_tag in containers[0].find_all("a"):
            text_el = a_tag.find(class_="widget-linklist__text")
            text_content = (
                text_el.get_text(" ", strip=True) if text_el else a_tag.get_text(" ", strip=True)
            )
            if not text_content:
                continue
            # Only org rows link to utwente.nl unit pages; the mailto /
            # research-portal / scholar / linkedin / vcard rows don't.
            href = str(a_tag.get("href") or "")
            parsed = urllib.parse.urlparse(href)
            is_org_link = parsed.hostname in ("www.utwente.nl", "utwente.nl") or (
                parsed.hostname == "people.utwente.nl" and parsed.path.startswith("/orgs/")
            )
            if not is_org_link:
                continue
            match = re.fullmatch(r"(.*?)\s*\(([^()]+)\)", text_content)
            name, abbr = (match.group(1).strip(), match.group(2)) if match else (text_content, None)
            entry = {"name": name, "abbr": abbr}
            if abbr in FACULTY_ABBS:
                faculty_abbr = abbr
                orgs.insert(0, entry)
            else:
                orgs.append(entry)

    portal_url = None
    for a in soup.find_all("a"):
        href = str(a.get("href") or "")
        if "/en/persons/" in href and "research.utwente.nl" in href:
            portal_url = (
                href if href.startswith("http") else urllib.parse.urljoin(RESEARCH_PORTAL_URL, href)
            )
            break

    return {
        "slug": tile["slug"],
        "canonical_name": canonical or tile.get("name"),
        "email": email,
        "orgs": orgs,
        "faculty_abbr": faculty_abbr,
        "portal_person_url": portal_url,
        "photo_url": tile.get("photo_url"),
    }


def portal_uuid(portal_person_url: str | None) -> str | None:
    """The pure uuid inside a portal profile URL, or None."""
    if not portal_person_url:
        return None
    tail = portal_person_url.rstrip("/").rsplit("/", 1)[-1]
    return tail or None


def sniff_image(data: bytes) -> str | None:
    """Media type for PNG/JPEG/AVIF magic bytes, else None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"):
        return "image/avif"
    return None


def _soup(html: str):
    """html.parser (pure Python) — NOT lxml: libxml2 has native
    crash/hang bug classes on malformed pages (ea-cli 2026-09-12)."""
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "html.parser")


# ── Client ─────────────────────────────────────────────────────────────────


async def rpc_search(client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
    """One SearchPersons RPC call → parsed tiles; [] on any transport or
    shape failure (shape changes are retried on the next run, never
    treated as a directory miss)."""
    try:
        resp = await client.post(
            RPC_URL,
            headers={"accept": "application/json", "user-agent": _UA},
            json={
                "id": 1,
                "method": "SearchPersons",
                "params": [{"query": query, "page": 0, "resultsperpage": 10, "langcode": "en"}],
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"SearchPersons HTTP {resp.status_code} for {query!r}")
        payload = resp.json()
        result = payload.get("result")
        if not isinstance(result, dict) or result.get("resultshtml") is None:
            raise RuntimeError(
                f"SearchPersons response shape changed (top-level keys {sorted(payload)})"
            )
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        logger.warning("people-utwente: search failed for %r: %s", query, exc)
        return []
    return parse_tiles(str(result["resultshtml"]))


async def fetch_profile(client: httpx.AsyncClient, tile: dict[str, Any]) -> dict[str, Any] | None:
    """Scrape one candidate's profile page; None on non-200."""
    try:
        resp = await client.get(
            tile["url"], headers={"accept": "text/html", "user-agent": _UA}, follow_redirects=True
        )
    except httpx.HTTPError as exc:
        logger.warning("people-utwente: profile fetch failed for %s: %s", tile["url"], exc)
        return None
    if resp.status_code != 200:
        logger.warning("people-utwente: profile HTTP %s for %s", resp.status_code, tile["url"])
        return None
    return parse_profile(resp.text, tile)


async def fetch_photo(client: httpx.AsyncClient, photo_url: str) -> tuple[bytes, str] | None:
    """Download + validate a portrait: *.utwente.nl over https only,
    ≤1 MB, magic-sniffed PNG/JPEG/AVIF (the directory serves AVIF)."""
    parsed = urllib.parse.urlparse(photo_url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not host.endswith(".utwente.nl"):
        logger.warning("people-utwente: photo url rejected (%s)", photo_url)
        return None
    try:
        resp = await client.get(photo_url, headers={"user-agent": _UA}, follow_redirects=True)
    except httpx.HTTPError as exc:
        logger.warning("people-utwente: photo fetch failed for %s: %s", photo_url, exc)
        return None
    if resp.status_code != 200:
        return None
    if len(resp.content) > MAX_AVATAR_BYTES:
        logger.warning("people-utwente: photo exceeds %d bytes (%s)", MAX_AVATAR_BYTES, photo_url)
        return None
    media_type = sniff_image(resp.content)
    if media_type is None:
        logger.warning("people-utwente: photo is not PNG/JPEG/AVIF (%s)", photo_url)
        return None
    return resp.content, media_type


# ── Harvest ────────────────────────────────────────────────────────────────


def resolve_org_uuids(
    orgs: list[dict[str, str]],
    org_candidates: dict[str, list[str]],
    org_candidates_bare: dict[str, list[str]],
    org_aliases: dict[str, str],
) -> dict[str, str]:
    """Scraped org name → pure_org uuid (unique matches only):
    curated alias → org-tree name_key → prefix-stripped fallback."""
    resolved: dict[str, str] = {}
    for org in orgs:
        name = (org.get("name") or "").strip()
        if not name:
            continue
        uuids = match_org_name(name, org_aliases, org_candidates, org_candidates_bare)
        if len(uuids) == 1:
            resolved[name] = uuids[0]
    return resolved


async def harvest_people_utwente(
    session: AsyncSession,
    institution: Institution,
    *,
    ingest: IngestSession,
    limit: int | None = None,
    retry_missed: bool = False,
    refresh: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    """Walk the author roster, resolve people.utwente.nl profiles.

    Returns per-outcome stats (searched / matched / candidate / missed /
    photos / org_edges / identity_rows / skipped / errors)."""
    stats = {
        "searched": 0,
        "matched": 0,
        "candidate": 0,
        "missed": 0,
        "photos": 0,
        "org_edges": 0,
        "identity_rows": 0,
        "skipped": 0,
        "errors": 0,
    }

    # Author pool: existing people rows gate re-runs.
    existing = {
        row.person_uuid: row
        for row in (
            await session.execute(
                select(PeopleUtwentePerson).where(
                    PeopleUtwentePerson.institution_id == institution.id
                )
            )
        ).scalars()
    }
    pool: list[Author] = []
    for row in (
        await session.execute(
            select(Author)
            .where(Author.institution_id == institution.id)
            .order_by(Author.confirmed.desc(), Author.n_works.desc(), Author.pure_uuid)
        )
    ).scalars():
        prior = existing.get(row.pure_uuid)
        if prior is not None and not ((retry_missed and prior.status == "missed") or refresh):
            stats["skipped"] += 1
            continue
        pool.append(row)
        if limit is not None and len(pool) >= limit:
            break

    if not pool:
        return stats

    # Org resolution indexes (the portal-bind pattern: name_key exact,
    # prefix-stripped fallback, curated aliases pass-through).
    tree = await load_org_tree(session, institution)
    org_candidates: dict[str, list[str]] = {}
    org_candidates_bare: dict[str, list[str]] = {}
    for uuid, org in tree.orgs.items():
        org_candidates.setdefault(name_key(org.name), []).append(uuid)
        org_candidates_bare.setdefault(org_bare_key(org.name), []).append(uuid)
    org_aliases: dict[str, str] = {}

    async with httpx.AsyncClient(timeout=30) as client:
        for author in pool:
            stats["searched"] += 1
            try:
                outcome = await _resolve_author(client, author)
            except Exception as exc:
                stats["errors"] += 1
                logger.exception("people-utwente: author %s failed: %s", author.pure_uuid, exc)
                continue

            if not dry_run:
                await _store_outcome(
                    session,
                    institution,
                    author,
                    outcome,
                    existing.get(author.pure_uuid),
                    client=client,
                    refresh=refresh,
                    stats=stats,
                    org_candidates=org_candidates,
                    org_candidates_bare=org_candidates_bare,
                    org_aliases=org_aliases,
                    ingest=ingest,
                )
            else:
                stats[outcome["status"]] += 1
            await asyncio.sleep(PACE_SECONDS)

    return stats


async def _resolve_author(client: httpx.AsyncClient, author: Author) -> dict[str, Any]:
    """Search + verify one author. Outcome dict: status
    (matched/candidate/missed), profile (when a page was scraped),
    tier (2 exact / 1 initials), reason (misses), candidates_seen."""
    author_key, author_reversed = person_name_keys(author.name)
    tiles = await rpc_search(client, author.name)
    if not tiles:
        return {"status": "missed", "profile": None, "tier": 0, "reason": "no_candidates"}

    ranked = sorted(
        (tile for tile in tiles if (tier := name_match_tier(author_key, author_reversed, tile))),
        key=lambda tile: -name_match_tier(author_key, author_reversed, tile),
    )
    if not ranked:
        return {"status": "missed", "profile": None, "tier": 0, "reason": "name_gate"}

    # Verify candidates in tier order; a portal uuid that differs from
    # the author's pure uuid disqualifies that candidate (someone else).
    best_unverified: tuple[int, dict[str, Any], dict[str, Any]] | None = None
    mismatch_seen = False
    for tile in ranked[:MAX_DETAIL_FETCHES]:
        await asyncio.sleep(DETAIL_PACE_SECONDS)
        profile = await fetch_profile(client, tile)
        if profile is None:
            continue
        uuid = portal_uuid(profile["portal_person_url"])
        if uuid is None:
            if (
                best_unverified is None
                or name_match_tier(author_key, author_reversed, tile) > best_unverified[0]
            ):
                best_unverified = (
                    name_match_tier(author_key, author_reversed, tile),
                    tile,
                    profile,
                )
            continue
        if uuid.lower() == author.pure_uuid.lower():
            return {
                "status": "matched",
                "profile": profile,
                "tier": name_match_tier(author_key, author_reversed, tile),
                "reason": None,
            }
        mismatch_seen = True

    if best_unverified is not None:
        tier, tile, profile = best_unverified
        return {
            "status": "candidate",
            "profile": profile,
            "tier": tier,
            "reason": "no_portal_link",
        }
    return {
        "status": "missed",
        "profile": None,
        "tier": 0,
        "reason": "uuid_mismatch" if mismatch_seen else "fetch_failed",
    }


async def _store_outcome(
    session: AsyncSession,
    institution: Institution,
    author: Author,
    outcome: dict[str, Any],
    prior: PeopleUtwentePerson | None,
    *,
    client: httpx.AsyncClient,
    refresh: bool,
    stats: dict[str, int],
    org_candidates: dict[str, list[str]],
    org_candidates_bare: dict[str, list[str]],
    org_aliases: dict[str, str],
    ingest: IngestSession,
) -> None:
    """Persist one outcome: the people row, matched-org edges, the
    candidate identity row, and the verbatim profile in source_records."""
    from datetime import datetime

    status = outcome["status"]
    profile = outcome["profile"]
    stats[status] += 1

    row = prior or PeopleUtwentePerson(institution_id=institution.id, person_uuid=author.pure_uuid)
    row.status = status
    row.slug = profile["slug"] if profile else None
    row.canonical_name = profile["canonical_name"] if profile else None
    row.email = profile["email"] if profile else None
    row.orgs = profile["orgs"] if profile else []
    row.faculty_abbr = profile["faculty_abbr"] if profile else None
    row.portal_person_url = profile["portal_person_url"] if profile else None
    row.photo_url = profile["photo_url"] if profile else None
    row.match_method = (
        "uuid" if status == "matched" else ("name" if status == "candidate" else None)
    )
    row.match_confidence = 1.0 if status == "matched" else (0.9 if status == "candidate" else None)
    row.reason = outcome.get("reason")
    row.synced_at = datetime.now(UTC)

    # Photo bytes: matched/candidate pages only; skip when already stored
    # unless --refresh (portrait URLs are stable across refreshes).
    if profile and profile.get("photo_url") and (refresh or row.photo_bytes is None):
        photo = await fetch_photo(client, profile["photo_url"])
        if photo is not None:
            row.photo_bytes, row.photo_media_type = photo
            stats["photos"] += 1

    session.add(row)

    if profile:
        await ingest.ingest_records([(profile["slug"], {**profile, "status": status})])

    if status == "matched" and profile:
        resolved = resolve_org_uuids(
            profile["orgs"], org_candidates, org_candidates_bare, org_aliases
        )
        await session.execute(
            delete(PeopleUtwentePersonOrg).where(
                PeopleUtwentePersonOrg.institution_id == institution.id,
                PeopleUtwentePersonOrg.person_uuid == author.pure_uuid,
            )
        )
        for org_name, org_uuid in resolved.items():
            abbr = next((o.get("abbr") for o in profile["orgs"] if o.get("name") == org_name), None)
            session.add(
                PeopleUtwentePersonOrg(
                    institution_id=institution.id,
                    person_uuid=author.pure_uuid,
                    org_uuid=org_uuid,
                    people_slug=profile["slug"],
                    org_abbr=abbr,
                )
            )
        stats["org_edges"] += len(resolved)

    if status == "candidate":
        # Admin-review row; never overwrite an admin decision
        # (confirmed/rejected rows are sticky across runs).
        identity = await session.scalar(
            select(AuthorIdentity).where(
                AuthorIdentity.institution_id == institution.id,
                AuthorIdentity.author_pure_uuid == author.pure_uuid,
                AuthorIdentity.source == "people",
                AuthorIdentity.external_id == profile["slug"],  # type: ignore[union-attr]
            )
        )
        if identity is None:
            session.add(
                AuthorIdentity(
                    institution_id=institution.id,
                    author_pure_uuid=author.pure_uuid,
                    source="people",
                    external_id=profile["slug"],
                    status="candidate",
                    method="name" if outcome["tier"] == 2 else "initials",
                    confidence=row.match_confidence,
                    evidence={
                        "canonical_name": profile["canonical_name"],
                        "portal_person_url": profile["portal_person_url"],
                        "org_abbrs": [o.get("abbr") for o in profile["orgs"] if o.get("abbr")],
                    },
                )
            )
            stats["identity_rows"] += 1
        elif identity.status == "candidate":
            identity.evidence = {
                "canonical_name": profile["canonical_name"],
                "portal_person_url": profile["portal_person_url"],
                "org_abbrs": [o.get("abbr") for o in profile["orgs"] if o.get("abbr")],
            }
