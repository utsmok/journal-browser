#!/usr/bin/env bash
# The weekly source wave: refreshes every primary and reference source the
# nightly wave never touches, for every active institution, in bootstrap
# DAG order.
#
# The nightly refresh_wave.sh only derives from stored data plus $0 OpenAlex
# singletons (list pages and searches cost credits). The sources that create
# works and coverage (Pure,
# openaccess.nl, JCT, OpenAPC, DOAJ, JISC) would otherwise run at bootstrap
# only, so new publications and coverage flags never enter a filled
# database. Every job here is idempotent, so rerunning the wave or any
# stage is safe.
#
# Only free/non-credit routes, by design: the Pure sweep reads the
# institution's OAI endpoint, the deal sources are two scrapes plus local
# ingests, DOAJ and OpenAPC are CSV downloads, and JISC is a keyed API that
# skips cleanly without JB_JISC_API_KEY. The one OpenAlex consumer,
# harvest_stats, gates itself on openalex_budget_ok() and stops
# cleanly once the remaining budget falls below the reserve.
#
# Scheduled Sunday 22:00 UTC (override with JB_SOURCE_WAVE_CRON in .env),
# ahead of the Monday 01:30 nightly wave so both fit in one weekend night.
# A failing stage names itself and alerts (scripts/lib.sh). The stages
# that depend on it are skipped, every other stage still runs, and the wave
# exits 1. Resume with the command it prints: --from STAGE runs that stage
# and every later one, where STAGE is a script name ("reconcile") or a
# per-institution step ("pure:rug", "stats:rug"), e.g.:
#   bash scripts/source_wave.sh --from enrich:ut
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/lib.sh

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

run() {
  local script="$1"
  shift
  echo "== source_wave: $script $*"
  uv run --no-dev python "jobs/$script" "$@"
}

# Split a stage entry into NAME, SCRIPT, ARGS and REQUIRES.
stage_parts() {
  local entry="$1"
  NAME="${entry%%||*}"
  entry="${entry#*||}"
  REQUIRES=""
  if [[ "$entry" == *"||"* ]]; then
    REQUIRES="${entry#*||}"
    entry="${entry%%||*}"
  fi
  SCRIPT="${entry%% *}"
  ARGS=""
  if [[ "$entry" == *" "* ]]; then ARGS="${entry#* }"; fi
}

# "name||args[||requires]": name keys --from, args is the command line,
# requires lists the stages whose output this one reads (the DEPS maps in
# jobs/bootstrap.py). A failed stage skips the stages that require it; the
# others still run. Every stage comes after the stages it reads.
# Global deal + reference sources first, in bootstrap GLOBAL_STEPS order
# (reconcile needs both deal sources; ISSN-L backfill needs reconcile).
STAGES=(
  "deals-openaccess-nl||scrape_openaccess_nl.py"
  "deals-jct||ingest_jct.py"
  "deals-reconcile||reconcile.py||deals-openaccess-nl,deals-jct"
  "deals-issn-l||backfill_issn_l.py||deals-reconcile"
  "openapc||ingest_openapc.py"
  "doaj||harvest_doaj.py"
  "jisc||harvest_jisc.py"
)

wave_begin source_wave "${from:+resume}"
reap_orphans

codes="$(uv run --no-dev python -c '
import asyncio
from jobs.bootstrap import hosted_codes
print("\n".join(asyncio.run(hosted_codes())))
')"
if [[ -z "$codes" ]]; then
  echo "source_wave: no active institutions"
  exit 1
fi

# Per-institution chain in bootstrap INST_STEPS order (minus reconcile:
# the global run above already derives participation for every hosted
# institution). CERIF entities and enrichment depend on the works sweep;
# OpenAIRE matching depends on the ISSN-L backfill.
for code in $codes; do
  STAGES+=(
    "pure:$code||harvest_pure.py --institution $code"
    "pure-cerif:$code||harvest_pure.py --cerif --institution $code||pure:$code"
    "pure-entities:$code||harvest_pure_entities.py --institution $code||pure:$code"
    "enrich:$code||enrich_works.py --institution $code||pure:$code"
    "openaire:$code||harvest_openaire.py --institution $code||pure:$code,deals-issn-l"
    "openaire-facts:$code||derive_openaire_facts.py --institution $code||openaire:$code"
  )
done
# Flags recompute over the fresh corpus, then stats per institution
# (bootstrap DAG: stats depends on flags, enrich, openaire, openaire-facts
# and the global openapc stage above).
STAGES+=("flags||backfill_flags.py")
for code in $codes; do
  STAGES+=(
    "stats:$code||harvest_stats.py --institution $code||enrich:$code,openaire:$code,openaire-facts:$code,openapc,flags"
  )
done

start=0
if [[ -n "$from" ]]; then
  start=""
  for i in "${!STAGES[@]}"; do
    stage_parts "${STAGES[i]}"
    if [[ "$NAME" == "$from" || "$SCRIPT" == "$from" || "${SCRIPT%.py}" == "$from" ]]; then
      start="$i"
      break
    fi
  done
  [[ -n "$start" ]] ||
    usage_error source_wave "unknown --from stage '$from' (stages: $(printf '%s\n' "${STAGES[@]}" | cut -d'|' -f1 | tr '\n' ' '))"
fi

for i in "${!STAGES[@]}"; do
  (( i < start )) && continue
  stage_parts "${STAGES[i]}"
  if [[ -n "$REQUIRES" ]] && wave_failed_any "$REQUIRES"; then
    echo "source_wave: skipping $NAME (needs $REQUIRES)"
    wave_skip "$NAME"
    continue
  fi
  wave_stage "$NAME"
  # $ARGS is a command line: the words must split.
  # shellcheck disable=SC2086
  if run "$SCRIPT" $ARGS; then
    continue
  fi
  wave_fail "$NAME"
done

if [[ -n "$WAVE_FAILED" ]]; then
  echo "source_wave: failed stages: $WAVE_FAILED"
  echo "source_wave: resume with: $(job_command bash source_wave.sh "${WAVE_FAILED%% *}")"
  exit 1
fi

echo "source_wave: complete"
# Re-warm the caches the wave just invalidated, so the first visitor after
# the night does not pay for cold pages. A failure here never fails the wave.
uv run --no-dev python scripts/prewarm.py > /dev/null || echo "source_wave: prewarm failed"
