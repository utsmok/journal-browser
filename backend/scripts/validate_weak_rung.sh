#!/usr/bin/env bash
# Weak-affiliation rung status probe (READ-ONLY).
#
# The original one-shot validation script ran resolve + ingest on live;
# the rung went live on 2026-10-31 (5,322 confirmed weak rows, van Doorn
# spot-checked), so that version was retired. This replacement checks the
# invariants the weak-rung decision rests on with SELECT-only access:
#   1. population snapshot (authors / identities / weak / candidates)
#   2. weak rows by method
#   3. invariants: weak rows are confirmed; no weak author carries >1
#      distinct ORCID (the Xiang Zhang class the gate exists to prevent)
#   4. van Doorn spot check (the name-exact case that motivated the rung)
# Safe to run any time; safe for agents (no writes, no resolve/ingest).
set -euo pipefail
cd "$(dirname "$0")/.."

LIVE_URL="postgresql+asyncpg://journal:journal@localhost:5434/journalbrowser"
PSQL_LIVE="${LIVE_URL/postgresql+asyncpg:/postgresql:}"

echo "== 0. db up check"
pg_isready -h localhost -p 5434 -U journal >/dev/null || { echo "postgres down"; exit 1; }

echo "== 1. live population snapshot"
psql "$PSQL_LIVE" -tAc \
  "SELECT 'authors', count(*) FROM authors UNION ALL
   SELECT 'identities', count(*) FROM author_identities UNION ALL
   SELECT 'weak', count(*) FROM author_identities WHERE evidence->>'weak_affiliation' = 'true'
   UNION ALL
   SELECT 'candidates', count(*) FROM author_identities WHERE status = 'candidate'"

echo "== 2. weak rows by method"
psql "$PSQL_LIVE" -tAc \
  "SELECT method, count(*) FROM author_identities
   WHERE evidence->>'weak_affiliation' = 'true' GROUP BY method ORDER BY 2 DESC"

echo "== 3. invariants"
printf -- "-- weak rows NOT confirmed (expect 0): "
psql "$PSQL_LIVE" -tAc \
  "SELECT count(*) FROM author_identities
   WHERE evidence->>'weak_affiliation' = 'true' AND status <> 'confirmed'"
printf -- "-- weak authors with >1 distinct orcid (expect 0 after the\n"
echo "   ambiguity gate lands on live; 4 known rows predate it):"
psql "$PSQL_LIVE" -tAc \
  "SELECT count(*) FROM (
     SELECT i.author_pure_uuid
     FROM author_identities i
     CROSS JOIN LATERAL jsonb_array_elements_text(
       COALESCE(i.evidence->'orcids', '[]'::jsonb)
     ) AS e(value)
     WHERE i.status = 'confirmed' AND i.evidence->>'weak_affiliation' = 'true'
     GROUP BY i.author_pure_uuid
     HAVING count(DISTINCT e.value) > 1
   ) s"
printf -- "-- fragmentation twins riding confirmed primaries: "
psql "$PSQL_LIVE" -tAc \
  "SELECT count(*) FROM author_identities WHERE evidence ? 'twin_of'"

echo "== 4. van Doorn spot check (expect 1 confirmed identity row + authors row)"
# Identities keep OpenAlex source casing (A501...): compare lowercased.
psql "$PSQL_LIVE" -tAc \
  "SELECT 'identity', count(*) FROM author_identities
   WHERE lower(external_id) = 'a5010733081' AND status = 'confirmed'
   UNION ALL
   SELECT 'authors_row', count(*)
   FROM authors a
   JOIN author_identities i ON i.author_pure_uuid = a.pure_uuid
   WHERE lower(i.external_id) = 'a5010733081' AND i.status = 'confirmed'"

echo "== done (all counts labeled; investigate any non-zero in section 3)"
