#!/usr/bin/env bash
# Weak-affiliation rung validation (owner decision 2026-11-02).
# Run ONCE Docker is back: preview first, then live.
# Every step is fail-fast; each prints its evidence line.
set -euo pipefail
cd "$(dirname "$0")/.."

LIVE_URL="postgresql+asyncpg://journal:journal@localhost:5433/journalbrowser"
PREVIEW_URL="postgresql+asyncpg://journal:journal@localhost:5433/jb_author_preview"

echo "== 0. docker/db up check"
pg_isready -h localhost -p 5433 -U journal >/dev/null || { echo "postgres down"; exit 1; }

echo "== 1. PREVIEW: pre-run author/identity snapshot"
psql "${PREVIEW_URL/postgresql+asyncpg:/postgresql:}" -tAc \
  "SELECT 'authors', count(*) FROM authors UNION ALL
   SELECT 'identities', count(*) FROM author_identities UNION ALL
   SELECT 'weak', count(*) FROM author_identities WHERE evidence->>'weak_affiliation' = 'true'"

echo "== 2. PREVIEW: resolve with the rung (--no-sweeps)"
JB_DATABASE_URL="$PREVIEW_URL" uv run python jobs/resolve_author_ids.py --institution ut --no-sweeps \
  | python3 -c "import json,sys; d=json.load(sys.stdin)['ut']; print('weak:', d['weak_affiliation']); print('matched:', d['matched']); print('authors_seen:', d['authors_walked'])"

echo "== 3. PREVIEW: post-run counts + van Doorn check"
psql "${PREVIEW_URL/postgresql+asyncpg:/postgresql:}" -tAc \
  "SELECT 'weak_rows', count(*) FROM author_identities WHERE evidence->>'weak_affiliation' = 'true'"
psql "${PREVIEW_URL/postgresql+asyncpg:/postgresql:}" -tAc \
  "SELECT author_pure_uuid, external_id, method, status, evidence->'orcids'
   FROM author_identities WHERE evidence->>'weak_affiliation' = 'true' LIMIT 60" | head -50
psql "${PREVIEW_URL/postgresql+asyncpg:/postgresql:}" -tAc \
  "SELECT count(*) FROM author_identities WHERE external_id = 'a5010733081' AND status = 'confirmed'"

echo "== 4. LIVE: pre-run snapshot"
psql "${LIVE_URL/postgresql+asyncpg:/postgresql:}" -tAc \
  "SELECT 'authors', count(*) FROM authors UNION ALL
   SELECT 'identities', count(*) FROM author_identities"

echo "== 5. LIVE: resolve with the rung (--no-sweeps)"
JB_DATABASE_URL="$LIVE_URL" uv run python jobs/resolve_author_ids.py --institution ut --no-sweeps \
  | python3 -c "import json,sys; d=json.load(sys.stdin)['ut']; print('weak:', d['weak_affiliation'])"

echo "== 6. LIVE: ingest authors (roster now admits identity-confirmed)"
uv run python jobs/ingest_authors.py --institution ut

echo "== 7. LIVE: post-run diff"
psql "${LIVE_URL/postgresql+asyncpg:/postgresql:}" -tAc \
  "SELECT 'authors', count(*) FROM authors UNION ALL
   SELECT 'weak_rows', count(*) FROM author_identities WHERE evidence->>'weak_affiliation' = 'true'
   UNION ALL
   SELECT 'van_doorn', count(*) FROM authors WHERE openalex_author_id = 'a5010733081'"
echo "== done — now verify the frontend: /ut/authors count and van Doorn's page"
