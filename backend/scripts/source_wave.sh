#!/usr/bin/env bash
# The weekly source wave: refreshes every primary and reference source the
# nightly wave never touches, for every active institution, in bootstrap
# DAG order.
#
# The nightly refresh_wave.sh only derives from stored data plus free
# OpenAlex endpoints. The sources that create works and coverage (Pure,
# openaccess.nl, JCT, OpenAPC, DOAJ, JISC) would otherwise run at bootstrap
# only, so new publications and coverage flags never enter a filled
# database. Every job here is idempotent, so rerunning the wave or any
# stage is safe.
#
# Only free/non-credit routes, by design: the Pure sweep reads the
# institution's OAI endpoint, the deal sources are two scrapes plus local
# ingests, DOAJ and OpenAPC are CSV downloads, and JISC is a keyed API that
# skips cleanly without JB_JISC_API_KEY. The one OpenAlex consumer,
# harvest_stats, gates itself on openalex_credits_remaining() and skips
# cleanly at a spent budget.
#
# Scheduled Sunday 22:00 UTC (override with JB_SOURCE_WAVE_CRON in .env),
# ahead of the Monday 01:30 nightly wave so both fit in one weekend night.
# A failing stage names itself and stops the wave. Resume past completed
# stages with --from STAGE, where STAGE is a script name ("reconcile") or
# a per-institution step ("pure:rug", "stats:rug"), e.g.:
#   bash scripts/source_wave.sh --from enrich_works.py
set -euo pipefail
cd "$(dirname "$0")/.."

run() {
  local script="$1"
  shift
  echo "== source_wave: $script $*"
  if ! uv run --no-dev python "jobs/$script" "$@"; then
    echo "source_wave: $script failed"
    exit 1
  fi
}

from=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from)
      [[ -n "${2:-}" ]] || { echo "source_wave: --from needs a stage name"; exit 2; }
      from="$2"
      shift 2
      ;;
    *)
      echo "source_wave: unknown option '$1' (usage: source_wave.sh [--from STAGE])"
      exit 2
      ;;
  esac
done

# "name||args" entries: name keys --from matching, args is the command line.
# Global deal + reference sources first, in bootstrap GLOBAL_STEPS order
# (reconcile needs both deal sources; ISSN-L backfill needs reconcile).
GLOBAL_STAGES=(
  "deals-openaccess-nl||scrape_openaccess_nl.py"
  "deals-jct||ingest_jct.py"
  "deals-reconcile||reconcile.py"
  "deals-issn-l||backfill_issn_l.py"
  "openapc||ingest_openapc.py"
  "doaj||harvest_doaj.py"
  "jisc||harvest_jisc.py"
)

codes="$(uv run --no-dev python -c '
import asyncio
from jobs.bootstrap import hosted_codes
print("\n".join(asyncio.run(hosted_codes())))
')"
if [[ -z "$codes" ]]; then
  echo "source_wave: no active institutions"
  exit 1
fi

STAGES=()
for stage in "${GLOBAL_STAGES[@]}"; do STAGES+=("$stage"); done
# Per-institution chain in bootstrap INST_STEPS order (minus reconcile:
# the global run above already derives participation for every hosted
# institution). CERIF entities and enrichment depend on the works sweep;
# OpenAIRE matching depends on the ISSN-L backfill.
for code in $codes; do
  STAGES+=(
    "pure:$code||harvest_pure.py --institution $code"
    "pure-cerif:$code||harvest_pure.py --cerif --institution $code"
    "pure-entities:$code||harvest_pure_entities.py --institution $code"
    "enrich:$code||enrich_works.py --institution $code"
    "openaire:$code||harvest_openaire.py --institution $code"
    "openaire-facts:$code||derive_openaire_facts.py --institution $code"
  )
done
# Flags recompute over the fresh corpus, then stats per institution
# (bootstrap DAG: stats depends on flags, enrich, openaire, openaire-facts
# and the global openapc stage above).
STAGES+=("flags||backfill_flags.py")
for code in $codes; do
  STAGES+=("stats:$code||harvest_stats.py --institution $code")
done

started=false
for entry in "${STAGES[@]}"; do
  name="${entry%%||*}"
  args="${entry#*||}"
  script="${args%% *}"
  rest=""
  [[ "$args" == *" "* ]] && rest="${args#* }"
  if [[ -n "$from" ]] && ! $started; then
    if [[ "$name" == "$from" || "$script" == "$from" ]]; then
      started=true
    else
      continue
    fi
  fi
  run "$script" $rest
done
if [[ -n "$from" ]] && ! $started; then
  echo "source_wave: unknown stage '$from'"
  exit 2
fi

echo "source_wave: complete"
uv run --no-dev python scripts/prewarm.py > /dev/null || echo "source_wave: prewarm failed"
