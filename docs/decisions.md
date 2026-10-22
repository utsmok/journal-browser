# Decisions made & questions for you

## Decisions taken (flag if wrong)

1. **Deal→journal mapping from the cOAlition S JCT public dump (CC0), not from scraping
   the old browser.** The old browser's DB is proprietary and slow; JCT gives reviewed,
   machine-readable ISSN lists per agreement + ROR institutions. openaccess.nl scraping
   supplies the NL narrative layer (caps, workflow, status, yearly counts).
2. **Backend: FastAPI + SQLAlchemy 2 (async) + asyncpg on Postgres 17.** Boring, matches
   your Python/uv/docker stack; async because the app is I/O-bound on OpenAlex calls.
3. **Ingestion as plain `uv run` jobs in `backend/jobs/`** (no Airflow/Prefect). Scheduled
   via compose service later; MUS-style raw-landing-zone + audit rows from day one.
4. **Metrics: OpenAlex `summary_stats` + scimagojr CSV; no Scopus.** CiteScore/SNIP/JCR
   have no open source; we derive a CiteScore-lookalike and clearly label metrics.
5. **v1 is single-institution** (ours), but institution lives in data (ROR), so serving
   other universities later is configuration.

## Questions for you

1. **Which institution is "our university"?** You linked `utbrowser` (Twente's view) and
   bibliofabric is a Twente address. Plan assumes UT (`ROR 03equx394`... to confirm) —
   correct?
2. **OpenAlex client: build on `bibliofabric` (your family, `stavrophora` as template) or
   use `pyalex`?** Your message said bibliofabric family, so the plan builds a thin
   OpenAlex client on it — but note `pyalex` already does keyset pagination + retry and
   MUS uses it; building on bibliofabric costs ~1-2 days but keeps the family pattern and
   async. Recommendation: bibliofabric (as you said), pyalex as fallback.
3. **OpenAlex API key**: free account required for real pagination/rate limits (mailto no
   longer raises limits). Shall I register one for the project, or do you have one?
4. **Scope of "publication statistics"**: plan covers papers-per-year per journal by our
   authors + OA split + institution trends (parity with the old tool, from OpenAlex).
   Want anything beyond (e.g. per-faculty breakdowns like the old tool's ASG/AFSG/… splits)?
5. **Green OA (Sherpa/Open Policy Finder) display**: out of scope for v1 per scope.md.
   Acceptable, or must-have for launch? (It is the old tool's second-biggest feature.)
6. **Deployment target**: where will this live (university VM, SURF, k8s)? Affects compose
   vs helm and whether a CDN/basic auth layer is needed for "publicly available".
7. **Data licensing for the deal narrative**: openaccess.nl text has no explicit license.
   Plan: store structured facts + quotes with attribution and links, not wholesale text
   mirrors. OK?
