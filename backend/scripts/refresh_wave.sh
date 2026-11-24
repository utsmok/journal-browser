#!/usr/bin/env bash
# The daily refresh wave: every harvest and derivation job a filled database
# needs, run in sequence as one command.
#
# Run after the daily OpenAlex credit reset (00:00 UTC), from backend/:
#   bash scripts/refresh_wave.sh
# Every job is idempotent, so rerunning the wave or any stage is safe.
#
# Credit-priced stages run first, while the budget is fresh: the 2026-11-07
# wave burned ~7h of the fresh daily budget on the then credit-priced
# oa-colors step, and a 5-second funder crash stopped the remaining stages
# via the exit gate. Measured 2026-11-20, singleton GETs bill $0; list
# pages cost $0.0001 and searches $0.001, so only those stages draw the
# budget. All OpenAlex stages gate on openalex_budget_ok() in harvest code
# and stop cleanly once the remaining budget falls below the
# JB_OPENALEX_RESERVE_USD reserve (default 0.25); harvest_publishers only
# costs credits on a fresh install, when its publisher cache is still empty.
#
# A failing stage names itself and alerts (scripts/lib.sh). The stages that
# depend on it are skipped, every other stage still runs, and the wave
# exits 1. Resume with the command it prints: --from STAGE runs that stage
# and every later one, e.g.:
#   bash scripts/refresh_wave.sh --from harvest_openalex_funders
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/lib.sh

# "stage[||requires]". Stage names match the backend/jobs/ scripts so --from
# takes a job name. requires lists the stages whose output this one reads:
# a failed stage skips its dependents and nothing else. Every stage comes
# after the stages it reads.
STAGES=(
  # Credit-priced sweep, while the daily budget is fresh (see header).
  harvest_stats
  # Store rebuild + backfills before author resolution: the resolver reads
  # openalex_work_authors and work_pure_authors, which the first two stages
  # rewrite (bootstrap DAG: author-ids depends on openalex-works and
  # pure-authors).
  build_openalex_works
  "backfill_parts||build_openalex_works"
  backfill_pure_authors
  "resolve_author_ids||build_openalex_works,backfill_pure_authors"
  # Local projection right after identity resolution: publishes confirmed
  # author identities to the served roster; no API calls.
  "ingest_authors||resolve_author_ids"
  # Local derivation from stored data, no API calls; reads works.oa_status,
  # which build_openalex_works re-synced above.
  "harvest_oa_colors||build_openalex_works"
  # Funder backfills: $0 single-entity GETs, then OpenAIRE. The OpenAlex
  # gap-fill reads work_funders; the alias derive reads both funders.
  harvest_work_funders
  "harvest_openalex_funders||harvest_work_funders"
  harvest_openaire_funders
  # Partner links from the stored OpenAlex and OpenAIRE work payloads, the
  # OpenAIRE funder names resolved to OpenAlex funders, then the ROR records
  # of new and stale partners (free, no key).
  derive_work_partners
  "derive_funder_aliases||harvest_work_funders,harvest_openaire_funders"
  "harvest_ror||derive_work_partners"
  # Credit-priced only on a fresh install (empty publisher cache).
  harvest_publishers
  # Slow CPU step last, so it never delays the priced stages.
  embed_journals
)

from=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from)
      [[ -n "${2:-}" ]] || { echo "wave: --from needs a stage name"; exit 2; }
      from="$2"
      shift 2
      ;;
    *)
      echo "wave: unknown option '$1' (usage: refresh_wave.sh [--from STAGE])"
      exit 2
      ;;
  esac
done

names=()
requires=()
for entry in "${STAGES[@]}"; do
  names+=("${entry%%||*}")
  if [[ "$entry" == *"||"* ]]; then requires+=("${entry#*||}"); else requires+=(""); fi
done

start=0
if [[ -n "$from" ]]; then
  start=""
  for i in "${!names[@]}"; do
    if [[ "${names[i]}" == "$from" ]]; then start="$i"; break; fi
  done
  [[ -n "$start" ]] || usage_error refresh_wave "unknown --from stage '$from' (stages: ${names[*]})"
fi

wave_begin refresh_wave "${from:+resume}"
reap_orphans

echo "== 0. OpenAlex daily credit budget"
budget="$(uv run --no-dev python -c '
import asyncio

from journal_browser.harvest.common import openalex_credits_remaining

remaining = asyncio.run(openalex_credits_remaining())
if remaining is None:
    print("unknown (rate-limit check failed; in-code gates stay open)")
elif remaining <= 0:
    print("0 USD (exhausted; priced stages stop at the reserve, resets 00:00 UTC)")
else:
    print(f"{remaining:.2f} USD")
')" || { echo "wave: budget check failed"; exit 1; }
echo "wave: daily OpenAlex credit budget: $budget"

for i in "${!names[@]}"; do
  (( i < start )) && continue
  stage="${names[i]}"
  if [[ -n "${requires[i]}" ]] && wave_failed_any "${requires[i]}"; then
    echo "wave: skipping $stage (needs ${requires[i]})"
    wave_skip "$stage"
    continue
  fi
  wave_stage "$stage"
  echo "== $(( i + 1 )). $stage"
  if uv run --no-dev python "jobs/$stage.py"; then
    continue
  fi
  wave_fail "$stage"
done

if [[ -n "$WAVE_FAILED" ]]; then
  echo "wave: failed stages: $WAVE_FAILED"
  echo "wave: resume with: $(job_command bash refresh_wave.sh "${WAVE_FAILED%% *}")"
  exit 1
fi

echo "wave: complete"
# Re-warm the caches the wave just invalidated, so the first visitor after
# the night does not pay for cold pages. A failure here never fails the wave.
uv run --no-dev python scripts/prewarm.py > /dev/null || echo "wave: prewarm failed"
