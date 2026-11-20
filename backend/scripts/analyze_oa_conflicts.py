"""Ground-truth OpenAIRE vs OpenAlex OA-colour conflicts on the live DB.

Usage (from backend/): uv run python scripts/analyze_oa_conflicts.py [--total 94]

Read-only DB access. The conflict population mirrors the journal card
cross-check (detail_enrichment._OPENAIRE_INFO_SQL): per institution and DOI,
the most-open openalex_works row vs the openaire_work_facts colour reached
through works, non-retired works only. It samples the population
deterministically (md5 order, fixed allocation), fetches free evidence per
DOI, and rates each source's colour against that evidence.

Evidence and what it can prove (all free):
- DOAJ (via OpenAlex source.is_in_doaj, confirmed against the DOAJ API
  when needed): the journal is fully OA -> gold or diamond.
- Crossref licence (plus a landing-page licence grep for rows still
  ambiguous): an open licence applies at the publisher -> gold or hybrid.
- OpenAlex locations (structural facts only, not its verdict): a repository
  copy exists -> green is defensible when no publisher OA evidence exists.
- bronze (free-to-read at the publisher without a licence) cannot be proven
  or ruled out by any cheap signal; claims of bronze that survive no
  positive evidence count as unverifiable, never wrong.

Output: one line per sampled work, then per-source accuracy with counts.
Deterministic given the same DB state; API evidence may drift over time.
"""

import argparse
import asyncio
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, ".")
from journal_browser.config import get_settings

#: The conflict population: one row per (institution, DOI), most-open
#: OpenAlex store colour vs the OpenAIRE facts colour.
CONFLICT_SQL = text(
    """
    WITH oa AS (
        SELECT DISTINCT ON (institution_id, doi_normalized)
               institution_id, doi_normalized, oa_status
        FROM openalex_works
        WHERE doi_normalized IS NOT NULL AND oa_status IS NOT NULL
        ORDER BY institution_id, doi_normalized,
                 CASE oa_status
                     WHEN 'diamond' THEN 5 WHEN 'gold' THEN 4 WHEN 'hybrid' THEN 3
                     WHEN 'bronze' THEN 2 WHEN 'green' THEN 1 ELSE 0
                 END DESC,
                 w_id
    )
    SELECT i.code AS inst, w.doi_normalized AS doi, w.journal_issn_l AS issn_l,
           lower(oaf.oa_color) AS openaire, oa.oa_status AS openalex
    FROM openaire_work_facts oaf
    JOIN works w
      ON w.institution_id = oaf.institution_id AND w.pure_uuid = oaf.pure_uuid
    JOIN institutions i ON i.id = w.institution_id
    JOIN oa ON oa.institution_id = w.institution_id
           AND oa.doi_normalized = w.doi_normalized
    WHERE oaf.oa_color IS NOT NULL AND w.retired_at IS NULL
      AND lower(oaf.oa_color) <> oa.oa_status
    ORDER BY md5(i.code || ':' || w.doi_normalized)
    """
)

#: Open licence markers in Crossref licence URLs and landing-page text.
CC_RE = re.compile(
    r"creativecommons\.org/(?:licenses|licences|publicdomain)/[\w.\-]+"
    r"|elsevier\.com/open-access/userlicense",
    re.IGNORECASE,
)

BUDGET_TIMEOUT = 20.0


@dataclass
class Evidence:
    record_oa: str | None = None  # OpenAlex's own oa_status label (audit only)
    is_oa_record: bool | None = None
    doaj: bool | None = None  # journal fully OA (OpenAlex flag or DOAJ API)
    licence: str | None = None  # matched open-licence text, Crossref or landing
    repo_present: bool | None = None
    oa_at_publisher: bool | None = None  # best OA copy sits on a journal page
    landing_tried: bool = False
    errors: list[str] = field(default_factory=list)


def allocate(counts: dict[tuple[str, str], int], total: int, cap: int, floor: int):
    """Deterministic proportional allocation: floor per pair, cap per pair,
    largest remainder fills the rest."""
    pairs = sorted(counts, key=lambda p: (-counts[p], p))
    sizes = {
        p: min(max(floor, round(counts[p] * total / sum(counts.values()))), cap, counts[p])
        for p in pairs
    }
    return pairs, sizes


async def _get_json(client: httpx.AsyncClient, url: str) -> object | None:
    for attempt in range(2):
        try:
            r = await client.get(url)
            if r.status_code == 429 and attempt == 0:
                await asyncio.sleep(3.0)
                continue
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as exc:
            if attempt == 1:
                return {"__error__": str(exc)[:120]}
            await asyncio.sleep(1.5)
    return None


async def fetch_openalex(client: httpx.AsyncClient, doi: str, mailto: str) -> Evidence:
    ev = Evidence()
    payload = await _get_json(client, f"https://api.openalex.org/works/doi:{doi}?mailto={mailto}")
    if not isinstance(payload, dict) or payload.get("__error__") or payload.get("id") is None:
        ev.errors.append(f"openalex: {payload}")
        return ev
    oa = payload.get("open_access") or {}
    ev.record_oa = oa.get("oa_status")
    ev.is_oa_record = bool(oa.get("is_oa"))
    sources = [
        loc.get("source") or {} for loc in (payload.get("locations") or []) if isinstance(loc, dict)
    ]
    ev.repo_present = any(s.get("type") == "repository" for s in sources)
    best = payload.get("best_oa_location") or {}
    ev.oa_at_publisher = (best.get("source") or {}).get("type") == "journal"
    ev.doaj = any(s.get("is_in_doaj") is True for s in sources)
    return ev


async def fetch_crossref(client: httpx.AsyncClient, doi: str, mailto: str) -> str | None:
    payload = await _get_json(client, f"https://api.crossref.org/works/{doi}?mailto={mailto}")
    if not isinstance(payload, dict) or payload.get("__error__"):
        return None
    msg = payload.get("message") or {}
    for lic in msg.get("license") or []:
        url = lic.get("URL") or ""
        if CC_RE.search(url):
            return url
    return None


async def fetch_doaj(client: httpx.AsyncClient, issn: str) -> bool | None:
    payload = await _get_json(
        client, f"https://doaj.org/api/search/journals/issn%3A{issn}?pageSize=1"
    )
    if not isinstance(payload, dict) or payload.get("__error__"):
        return None
    return bool(payload.get("total"))


async def fetch_landing(client: httpx.AsyncClient, doi: str) -> str | None:
    try:
        r = await client.get(
            f"https://doi.org/{doi}",
            headers={"User-Agent": "oa-colour-audit/1.0 (mailto in settings)"},
        )
        if r.status_code != 200:
            return None
        m = CC_RE.search(r.text[:400_000])
        return m.group(0) if m else None
    except httpx.HTTPError:
        return None


def classify(ev: Evidence, openaire: str, openalex: str) -> tuple[str, set[str] | None]:
    """Evidence -> (tier, acceptable colours or None when unverifiable)."""
    if ev.record_oa is None and ev.errors:
        return "no_evidence", None
    if ev.doaj:
        return "journal_oa", {"gold", "diamond"}
    if ev.licence:
        return "publisher_licence", {"gold", "hybrid"}
    # No proven publisher OA. A repository copy makes green defensible.
    if ev.repo_present:
        return "repository_copy", {"green"}
    if ev.is_oa_record is False:
        return "no_oa_found", {"closed"}
    if ev.oa_at_publisher:
        # Open at the publisher, but which flavour (gold/hybrid vs bronze)
        # needs the licence or DOAJ signal that did not fire.
        return "publisher_oa", {"gold", "hybrid", "bronze"}
    return "unresolved", None


def rate(color: str, acceptable: set[str] | None, source: str = "") -> str:
    if acceptable is None:
        return "unverifiable"
    if color in acceptable:
        # In the publisher_oa tier the OpenAlex label itself defined the
        # set, so membership is circular rather than confirmatory.
        if acceptable == {"gold", "hybrid", "bronze"} and source == "openalex":
            return "unverifiable"
        return "correct"
    # bronze is free-to-read at the publisher without a licence; no cheap
    # signal can rule it out next to {green} or {closed}.
    if color == "bronze" and acceptable in ({"green"}, {"closed"}):
        return "unverifiable"
    return "wrong"


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--total", type=int, default=94, help="sample size across all pairs")
    ap.add_argument("--cap", type=int, default=8, help="max sample per colour pair")
    ap.add_argument("--floor", type=int, default=3, help="min sample per colour pair")
    ap.add_argument("--landing-cap", type=int, default=60, help="max landing-page fetches")
    ap.add_argument("--mailto", default=None, help="politeness email (default: settings)")
    args = ap.parse_args()

    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        rows = (await session.execute(CONFLICT_SQL)).mappings().all()
    await engine.dispose()

    counts: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows:
        counts[(r["openaire"], r["openalex"])] += 1
    print(f"population: {len(rows)} conflicts across {len(counts)} colour pairs")
    for pair, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[1])):
        print(f"  {pair[0]:>7} vs {pair[1]:<7} {n}")

    _, sizes = allocate(counts, args.total, args.cap, args.floor)
    per_pair_seen: dict[tuple[str, str], int] = defaultdict(int)
    sample: list[dict] = []
    for r in rows:  # rows are already in deterministic md5 order
        pair = (r["openaire"], r["openalex"])
        if per_pair_seen[pair] < sizes[pair]:
            per_pair_seen[pair] += 1
            sample.append(dict(r))

    mailto = args.mailto or get_settings().contact_email or "oa-colour-audit@localhost"
    doaj_cache: dict[str, bool | None] = {}
    landing_left = [args.landing_cap]
    sem = asyncio.Semaphore(6)
    async with httpx.AsyncClient(timeout=BUDGET_TIMEOUT, follow_redirects=True) as client:

        async def gather(row: dict) -> dict:
            async with sem:
                ev = await fetch_openalex(client, row["doi"], mailto)
                ev.licence = await fetch_crossref(client, row["doi"], mailto)
                if ev.doaj is not True and row["issn_l"] and row["issn_l"] not in doaj_cache:
                    doaj_cache[row["issn_l"]] = await fetch_doaj(client, row["issn_l"])
                if ev.doaj is not True and row["issn_l"] in doaj_cache:
                    ev.doaj = doaj_cache[row["issn_l"]]
                tier, acceptable = classify(ev, row["openaire"], row["openalex"])
                # Landing grep only while a publisher-OA claim is unproven:
                # unresolved tiers, or repo-only tiers where OpenAIRE still
                # claims a publisher-side colour.
                needs_landing = acceptable is None or (
                    acceptable == {"green"} and row["openaire"] in {"gold", "hybrid"}
                )
                if landing_left[0] > 0 and needs_landing:
                    landing_left[0] -= 1
                    ev.landing_tried = True
                    ev.licence = await fetch_landing(client, row["doi"])
                tier, acceptable = classify(ev, row["openaire"], row["openalex"])
            return {"row": row, "ev": ev, "tier": tier, "acceptable": acceptable}

        results = await asyncio.gather(*(gather(r) for r in sample))

    tally: dict[str, dict[str, dict[str, int]]] = {
        "openaire": defaultdict(lambda: {"correct": 0, "wrong": 0, "unverifiable": 0}),
        "openalex": defaultdict(lambda: {"correct": 0, "wrong": 0, "unverifiable": 0}),
    }
    for res in results:
        row, ev, acceptable = res["row"], res["ev"], res["acceptable"]
        oa_verdict = rate(row["openaire"], acceptable, "openaire")
        ax_verdict = rate(row["openalex"], acceptable, "openalex")
        tally["openaire"][f"{row['openaire']}|{row['openalex']}"][oa_verdict] += 1
        tally["openalex"][f"{row['openaire']}|{row['openalex']}"][ax_verdict] += 1
        print(
            f"{row['inst']} {row['doi']} {row['openaire']}|{row['openalex']}"
            f" tier={res['tier']} oa={ev.record_oa} doaj={ev.doaj}"
            f" lic={'yes' if ev.licence else '-'} repo={ev.repo_present}"
            f" land={'y' if ev.landing_tried else '-'}"
            f" -> openaire:{oa_verdict} openalex:{ax_verdict}"
        )

    summary: dict[str, dict] = {"sampled": len(results), "per_pair": {}, "accuracy": {}}
    for source, per_pair in tally.items():
        summary["per_pair"][source] = {k: dict(v) for k, v in per_pair.items()}
        totals = {"correct": 0, "wrong": 0, "unverifiable": 0}
        for v in per_pair.values():
            for k in totals:
                totals[k] += v[k]
        rated = totals["correct"] + totals["wrong"]
        acc = totals["correct"] / rated if rated else None
        summary["accuracy"][source] = {**totals, "accuracy": acc}
    print(json.dumps(summary, indent=2))
    a = summary["accuracy"]["openaire"]["accuracy"]
    b = summary["accuracy"]["openalex"]["accuracy"]
    if a is None or b is None:
        print("verdict: not enough rated rows; raise --total or inspect the sample above")
    else:
        winner = "openaire" if a > b else "openalex"
        print(f"verdict: {winner} more accurate ({a:.2f} vs {b:.2f} over rated rows)")


if __name__ == "__main__":
    asyncio.run(main())
