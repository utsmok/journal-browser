---
name: qa
description: >
  Run QA tests for journal-browser. Analyzes git diff to determine affected areas,
  runs configured test flows with multiple personas, and generates diff-targeted tests.
  Uses droid-control for browser, terminal, and desktop interactions.
  Use when testing PRs, releases, or smoke testing environments.
---

# QA Orchestrator

**SCOPE: This skill performs manual/functional QA only -- verifying that the application actually works by interacting with it as a real user would (browser, API calls). Do NOT run or report on CI checks, linting, ruff, ty, typecheck, pytest, or any static analysis. Those are handled by the separate `CI` workflow.**

## Step 1: Load Configuration

Read `.factory/skills/qa/config.yaml` for environment URLs, credentials, personas, and app definitions.

For every affected interactive app, invoke the `droid-control` skill before interacting with the app. Follow its routing tables:

- Load the target driver selected for the app (agent-browser for the web frontend; the backend is API-only and driven with curl).
- Use the Capture and Verify stages on every run.
- Load Compose only when both `video_evidence: true` and `droid_control.compose: true` in config.
- When `droid_control.compose: false`, never invoke Compose. Keep raw captures and text snapshots as evidence.

Treat `droid_control.compose` and `video_evidence` as runtime toggles. Read them on every run; do not cache install-time answers. Keep branch instructions conditional on the config values so changing the config is sufficient.

## Step 2: Determine Target Environment

Use `default_target` (`local-qa`) unless the user specifies a different environment.

Environment rules for this project:

- `local-qa` is the default: use the `api_url` (backend) and `url` (frontend
  dev server) from `environments.local-qa` in config.yaml, and its
  `database` on the existing local cluster.
- `live-readonly` is for explicit smoke requests only: GET flows against `localhost:3000`/`localhost:8000`. Never POST feedback on live. Never call admin endpoints on live. Never restart the live compose project.
- The compose project `journal-browser` (ports 3000/8000, database `journalbrowser` on 5433) is the LIVE deployment. The QA database is a separate database on the same cluster; tests create throwaway databases there too, which is the established pattern in `backend/tests/conftest.py`.
- The live container mounts `backend/settings.yaml`. The QA backend MUST run with `JB_SETTINGS_YAML` on an isolated path (`/tmp/qa-settings.yaml`) so admin-settings writes never touch the live overlay.
- This project has no Vercel/Netlify preview deployments. If you are ever handed a preview-style URL anyway, treat it as a dev-environment equivalent and use dev flows.

## Step 3: Analyze Git Diff

Run `git diff` (against the merge base for PRs, or `git diff HEAD~1` on demand) to determine what changed. Map changed files to apps using the `path_patterns` in config.yaml:

- `frontend/**` -> the `web` app
- `backend/**`, `openapi.json`, `docker-compose.yml`, `compose.test.yml`, `db/**` -> the `backend` app
- Files matching NO pattern (`.factory/**`, `docs/**`, `droid-wiki/**`, `.github/**`, `plans/**`, `context_notes/**`, `data/**`, `dev/**`) belong to no app. Do NOT run app flows for them.

For each affected app: run only that app's flows from its sub-skill, plus additional targeted tests derived from the specific diff.

For apps NOT affected: do not load their sub-skill, run their flows, or run their pre-flight checks.

If NO app is affected (docs-only, CI-only, skill-only changes), report as INCONCLUSIVE: "No app code changed -- QA not applicable for this diff." Do not run any app flows.

## Step 4: Pre-flight Checks (affected apps only)

Backend (before anything else):

1. Verify the QA database exists and is seeded: `psql postgresql://journal:journal@127.0.0.1:5433/journalbrowser_qa -c 'select count(*) from journals'` must return > 0.
   - Local machine: if missing/empty, seed per `qa-backend/SKILL.md` ("Seeding the QA database") -- full dump restore, or the fixture seeder for a small dataset.
   - CI: the workflow migrates and seeds `journalbrowser_qa` via the fixture seeder before the QA step; if the seed step failed, report backend flows as BLOCKED.
2. Boot the QA backend per `qa-backend/SKILL.md` (the `api_url` from
   config.yaml, isolated `JB_SETTINGS_YAML`, `JB_ADMIN_PASSWORD=$QA_ADMIN_PASSWORD`)
   and poll `/api/v1/healthz`.

Web:

1. Requires the QA backend to be up (the dev-server proxy points at it).
2. Start the frontend dev server per `qa-web/SKILL.md` (the `url` from
   config.yaml, with `API_PROXY_URL` set to the backend `api_url`) and poll
   that URL.
3. `QA_ADMIN_PASSWORD` must be set for admin-persona flows.

Never boot anything on ports 3000 or 8000 -- those are the live deployment. If a pre-flight check fails for an affected app, report that app's flows as BLOCKED with the error and remediation, then continue with other affected apps.

## Step 5: Execute Diff-Relevant Flows Only

For each affected app, read `.factory/skills/qa-<app-name>/SKILL.md`. It contains a MENU of flows. You must:

1. Identify which flows are relevant to the change.
2. Run those flows plus adjacent integration checks (e.g., a new journals filter should also be verified in the frontend filter panel, and its facet cache invalidation).
3. Do NOT run unrelated flows (e.g., a docs-router change does not re-test deal curation).
4. If no existing flow covers the change, write an ad-hoc test that directly verifies the changed behavior.
5. Do NOT run pytest, ruff, ty, eslint, biome, or next build. This is functional QA by interaction only.

## Step 6: Evidence Capture

Text snapshots are primary evidence. Screenshots go to `./qa-results/$RUN_ID/` for the artifact upload.

For the web app:

- Use the droid-control web route; let its agent-browser atom own browser mechanics and its Capture atom own the recording lifecycle.
- Capture the page's accessibility tree as text evidence through the routed driver.
- Save screenshots to `./qa-results/$RUN_ID/`.
- Media embedding follows the platform and the `video_evidence` value read
  from config at run time. On GitHub: reference screenshot/video filenames
  in the report and note they are in the downloadable artifacts; never
  embed `![image](url)` markdown or links that did not come from an upload
  API response.

For the backend app:

- Capture curl requests and responses as fenced code blocks with labels. Show status codes. Trim large JSON bodies to the relevant fields.

Video evidence (only when `video_evidence: true` at run time): follow the droid-control Capture atom per flow, keep the raw WebM when `droid_control.compose: false`, or hand it to the Compose atom with the literal `"preset": "factory"` when `droid_control.compose: true` (single layout, 60 seconds or less, verified output). Upload per the platform rules that apply then, and never embed a link that did not come back from an upload API response.

Evidence quality rules: focus on the relevant content; label every snapshot with what it shows; never embed broken links; the workflow uploads everything under `./qa-results/` as a downloadable artifact.

## Step 7: Test Quality Gate

1. CHANGE-SPECIFIC FIRST: at least half the tests verify the behavioral change itself.
2. Integration checks are valid (new endpoint appears in openapi.json; new facet renders in the filter panel).
3. NO unrelated flows.
4. NO automated test suites.
5. At least one negative test per affected app (bad cursor -> 400, admin route without token -> 401, unknown institution -> 404).
6. Interact as a real user.
7. INCONCLUSIVE if you cannot articulate what the diff changes.

## Step 8: Handle Failures

**Never silently skip a flow.** If a flow cannot complete, report it as BLOCKED with what was tried and how the user can fix it. Then continue to the next flow -- never abort the entire run for a single failure.

## Step 9: Generate Report

Write `./qa-results/report.md` using `.factory/skills/qa/REPORT-TEMPLATE.md`. The report starts with `## QA Report`, uses the emoji result vocabulary, keeps the table plus a short "Action Required" section, and puts ALL evidence in one collapsed details block. Do not report setup steps (seeding, booting) as test rows.

## Step 10: Suggest Skill Updates (Failure Learning)

`failure_learning: suggest_in_report` -- after the report, check whether any BLOCKED or FAIL revealed a new testing-environment insight (not a selector bug, not an expected diff change). If so, append a "Suggested Skill Updates" section to the report: a table with severity (`🔴 Breaking`, `🟡 Degraded`, `🔵 Info`), the target sub-skill file, a short issue description, and a collapsible fix prompt that is a self-contained instruction. Known failure modes already documented in a sub-skill do not count as new insights. If nothing new surfaced, omit the section.
