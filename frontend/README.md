# journal-browser frontend

Next.js 15 app. `lib/api-types.ts` is generated from the backend OpenAPI
schema. After any backend API change, run `npm run generate` with the backend
reachable at `$JB_API` (default `http://localhost:8000`), then commit the
regenerated file together with the backend change.
