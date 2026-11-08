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
# via the exit gate. harvest_stats and the resolve_author_ids sweep gate
# themselves on openalex_credits_remaining() in harvest code and skip
# cleanly at a zero budget; harvest_publishers only costs credits on a
# fresh install, when its publisher cache is still empty.
#
# A failing stage names itself and stops the wave. Resume past the completed
# stages with --from STAGE, e.g.:
#   bash scripts/refresh_wave.sh --from harvest_openalex_funders
set -euo pipefail
cd "$(dirname "$0")/.."

# Stage names match the backend/jobs/ scripts so --from takes a job name.
STAGES=(
  # Credit-priced sweeps, while the daily budget is fresh (see header).
  harvest_stats
  resolve_author_ids
  # Local derivation from stored data, no API calls.
  harvest_oa_colors
  build_openalex_works
  backfill_pure_authors
  # Funder backfills: free single-entity GETs, then OpenAIRE.
  harvest_work_funders
  harvest_openalex_funders
  harvest_openaire_funders
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

start=""
if [[ -n "$from" ]]; then
  for i in "${!STAGES[@]}"; do
    if [[ "${STAGES[i]}" == "$from" ]]; then
      start="$i"
      break
    fi
  done
  if [[ -z "$start" ]]; then
    echo "wave: unknown --from stage '$from' (stages: ${STAGES[*]})"
    exit 2
  fi
fi
start="${start:-0}"

echo "== 0. OpenAlex daily credit budget"
budget="$(uv run python -c '
import asyncio

from journal_browser.harvest.common import openalex_credits_remaining

remaining = asyncio.run(openalex_credits_remaining())
if remaining is None:
    print("unknown (rate-limit check failed; in-code gates stay open)")
elif remaining <= 0:
    print("0 USD (exhausted; priced stages self-skip, resets 00:00 UTC)")
else:
    print(f"{remaining:.2f} USD")
')" || { echo "wave: budget check failed"; exit 1; }
echo "wave: daily OpenAlex credit budget: $budget"

for i in "${!STAGES[@]}"; do
  (( i < start )) && continue
  stage="${STAGES[i]}"
  echo "== $(( i + 1 )). $stage"
  uv run python "jobs/$stage.py" || { echo "wave: $stage failed"; exit 1; }
done

echo "wave: complete"
