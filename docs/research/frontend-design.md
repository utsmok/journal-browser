# Research: frontend design and implementation basis

Compiled 2026-10-22 from three sources: the TCRC frontend
(`/home/sam/dev/ea-cli-refactor/frontend`), openaccess.nl's live stylesheet, and the
UT visual identity as encoded in TCRC.

## 1. TCRC (ea-cli-refactor) frontend patterns — what to copy

Stack (all proven in daily use):

- Next.js 16 + React 19, TypeScript strict
- Tailwind CSS v4 (`@tailwindcss/postcss`), class-based dark variant via
  `@custom-variant dark`, theming through CSS variables in `globals.css`
- shadcn/ui-style layer: Radix UI primitives + `class-variance-authority` + `clsx` +
  `tailwind-merge` + `lucide-react` icons + `tw-animate-css`; components live in
  `src/components/ui/*` (button, badge, card, input, select, dialog, tabs, skeleton,
  stat-card, empty-state, error-state, ...)
- **TanStack Query v5** for server state: typed hooks in `src/hooks/use-api.ts`, shared
  filter types feeding both the query-key factory and hook signatures (so every API field
  participates in cache identity), `keepPreviousData` for list pages
- **TanStack Table** behind a custom `src/components/data-table/*` module (column
  customization, bulk toolbar, sticky scrollbar, feature flags)
- **openapi-typescript** generates `src/types/generated` from the FastAPI OpenAPI schema
  (`docs/OPENAPI_TYPES.md`); typed API modules in `src/api/*` per resource
- recharts for charts; Playwright + axe-core for e2e/a11y; vitest for units

Adoption for this project: the shadcn-style component layer, TanStack Query with the
key-factory + `keepPreviousData` pattern, TanStack Table for the results list, and
openapi-typescript against our FastAPI schema. i18n (paraglide) and auth contexts are
not needed for v1.

## 2. openaccess.nl design tokens (extracted from live CSS)

| Token | Value | Use on openaccess.nl |
|---|---|---|
| Accent orange | `#f06e00` | primary actions, links, highlights (59 occurrences) |
| Ink | `#12110c` | headings and body text |
| Surface light | `#f8f9fc`, `#f2f4f7` | page and card backgrounds |
| Muted text | `#515c65`, `#6a7173` | secondary text |
| Dark navy | `#14274c` | dark panels, footer (`data-theme="theme-dark"`) |
| White | `#ffffff` | cards, contrast surface |

Typography: **Inter** (body) + **Montserrat** (headings), both SIL OFL licensed,
self-hostable via `next/font`. Layout idiom: white cards on light grey, generous
radius, dark footer band, orange as the single accent color.

## 3. University of Twente identity (as encoded in TCRC, audited for contrast)

Core palette: darkblue `#002c5f` (primary), teal `#007d9c`, red `#c60c30`,
green `#4a8355`, purple `#4f2d7f`, pink `#cf0072`, grey `#f0f1f2`. TCRC additionally
ships text-safe lifted variants (`--brand-*-text`) that pass 4.5:1 contrast on their
tints, with documented audit dates. The default UT presentation is the darkblue +
teal pair on light grey.

## 4. Decision

- **Theme**: openaccess.nl-inspired for v1, implemented entirely as Tailwind v4 CSS
  variables mapped onto shadcn semantic tokens (`--primary`, `--background`, ...).
  Re-theming to UT house style later means replacing one token block (TCRC's UT
  palette is the ready-made target); no component changes.
- **Fonts**: Inter + Montserrat via `next/font/google` (self-hosted at build time),
  with system fallbacks.
- **Components**: scaffold only what v1 pages need now (button, input, badge, card,
  table, skeleton); add Radix-based components (select, dialog, popover) when those
  interactions land.
- **Data layer**: TanStack Query provider in the root layout; results list on
  TanStack Table; API types generated from FastAPI OpenAPI once endpoints exist.
