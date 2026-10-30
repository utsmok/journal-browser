# journal-browser frontend

Next.js 15 app. `lib/api-types.ts` is generated from the committed OpenAPI
schema (`../openapi.json`). After any backend API change:

```bash
cd backend && uv run python scripts/dump_openapi.py   # refresh openapi.json
cd ../frontend && npm run generate                    # refresh lib/api-types.ts
```

then commit the regenerated files together with the backend change.

## Commands

| Purpose           | Command                |
| ----------------- | ---------------------- |
| Lint (ESLint)     | `npm run lint`         |
| Format (Biome)    | `npm run format`       |
| Format check (CI) | `npm run format:check` |
| Production build  | `npm run build`        |
