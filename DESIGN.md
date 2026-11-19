---
name: Open Journal Browser
description: Find the best home for your next article, built on open data and open code.
colors:
  signal-orange: "#f06e00"
  signal-orange-hover: "#d46200"
  signal-orange-hover-dark: "#ff8a2a"
  ember-text: "#b34f00"
  ember-text-dark: "#ffa25e"
  warm-ink: "#1c0508"
  contract-navy: "#14274c"
  brand-cyan: "#00d7f0"
  ink: "#12110c"
  paper: "#f8f9fc"
  card-white: "#ffffff"
  mist: "#f2f4f7"
  slate-text: "#515c65"
  hairline: "#dee2e6"
  alert-red: "#dc3545"
  night-bg: "#101318"
  night-card: "#171b21"
  night-muted: "#1f252d"
  night-fog: "#9aa4af"
  night-border: "#2a313b"
  alert-rose-dark: "#f08c96"
  oa-closed: "#64748b"
  oa-closed-dark: "#94a3b8"
  oa-hybrid: "#4d84c7"
  oa-hybrid-dark: "#82b1e4"
  oa-generic: "#8f7ae5"
  oa-generic-dark: "#a99af0"
  oa-gold: "#f4aa2a"
  oa-gold-dark: "#fbbf24"
  oa-diamond: "#4fe4f8"
  oa-diamond-dark: "#67e8f9"
  oa-deal: "#047857"
  oa-deal-dark: "#6ee7b7"
typography:
  display:
    fontFamily: "Montserrat, Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 700
    lineHeight: 1.33
    letterSpacing: "-0.025em"
  headline:
    fontFamily: "Montserrat, Inter, ui-sans-serif, system-ui, sans-serif"
    fontWeight: 700
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Montserrat, Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.025em"
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    lineHeight: 1.5
    fontWeight: 400
  label:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.43
  micro:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.33
rounded:
  base: "0.5rem"
  pill: "9999px"
spacing:
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  button-primary:
    backgroundColor: "{colors.signal-orange}"
    textColor: "{colors.warm-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.base}"
    padding: "8px 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.signal-orange-hover}"
    textColor: "{colors.warm-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.base}"
    padding: "8px 16px"
    height: "40px"
  button-secondary:
    backgroundColor: "{colors.contract-navy}"
    textColor: "{colors.card-white}"
    typography: "{typography.label}"
    rounded: "{rounded.base}"
    padding: "8px 16px"
    height: "40px"
  button-outline:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.base}"
    padding: "8px 16px"
    height: "40px"
  button-ghost:
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.base}"
    padding: "8px 16px"
    height: "40px"
  button-link:
    textColor: "{colors.ember-text}"
    typography: "{typography.label}"
    rounded: "{rounded.base}"
  card:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.base}"
  input:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.base}"
    padding: "8px 12px"
    height: "40px"
  badge-pill:
    backgroundColor: "{colors.signal-orange}"
    textColor: "{colors.warm-ink}"
    typography: "{typography.micro}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
  badge-pill-muted:
    backgroundColor: "{colors.mist}"
    textColor: "{colors.slate-text}"
    typography: "{typography.micro}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
  footer-band:
    backgroundColor: "{colors.contract-navy}"
    textColor: "{colors.card-white}"
    padding: "24px 16px"
---

# Design System: Open Journal Browser

## Overview

**Creative North Star: "The Open Signal"**

Open Journal Browser looks like public infrastructure, not a startup page.
The palette comes from openaccess.nl: one saturated signal orange for actions
and highlights, a contract navy for authority panels and the footer, and calm
paper neutrals for everything else. The page is flat and bordered; depth is
rationed to a single soft lift on cards. Both fonts (Inter, Montserrat) are
self-hosted through `next/font`, so the page ships its own lettering.

The signature element is the open access lockup: a bare SVG padlock whose
shackle opens progressively with access level (closed → ajar → open → wide),
paired with a Montserrat wordmark, one color per access type, and sparkle
bursts that grow as the lock opens. The lockups render without pill
containers so result rows read as icon lockups, not chips. Locks occasionally
snap shut and spring open on a slow 7-second cycle; hover replays it. All
badge motion stops under `prefers-reduced-motion`.

The whole theme lives in one token block in `frontend/app/globals.css`,
mapped onto shadcn semantic names. An institution can be re-themed by
replacing that block; components never hardcode theme colors. Dark mode is a
class-based `.dark` override of the same tokens, hand-rolled without
next-themes.

**Key characteristics:**

- One accent (orange) on civic neutrals, navy reserved for panels and footer
- Flat bordered surfaces; exactly one soft card shadow
- Bare SVG access lockups with progressive shackle states and sparkles
- Documented WCAG decisions baked into tokens (dark warm ink on orange,
  darkened ember orange for text)
- Theme switching by replacing one CSS token block; class-based dark mode
- Native browser surfaces themed: selection, scrollbar, focus rings, print

## Colors

Civic and warm at once: a signal orange that stays legible because every
orange-on-background pairing uses a darker ember variant.

### Primary

- **Signal Orange** (`#f06e00`, dark-mode hover `#ff8a2a`): primary buttons,
  focus rings, highlights. Always carries **Warm Ink** (`#1c0508`) as its
  text color, never white: white on this orange is 3.03:1, warm ink is
  6.45:1.
- **Signal Orange Hover** (`#d46200` light, `#ff8a2a` dark): hover state of
  primary buttons.
- **Ember Text** (`#b34f00` light, `#ffa25e` dark): the text-safe orange for
  links and icon accents on page backgrounds. Raw signal orange fails WCAG AA
  as text on white; use this instead.

### Secondary

- **Contract Navy** (`#14274c`): secondary buttons, dark footer band, accent
  surfaces. White text on navy.
- **Brand Cyan** (`#00d7f0`): fixed color of the OJB lockups only (the
  cyan "Open" and monogram "O"). It is a brand asset color, not a UI token;
  do not use it for interface elements. The lockup orange is the same
  signal orange as primary actions.

### Neutral

- **Paper** (`#f8f9fc`, dark `#101318`): page background.
- **Card White** (`#ffffff`, dark `#171b21`): card and input surfaces.
- **Ink** (`#12110c`, dark `#e6e8eb`): headings and body text.
- **Mist** (`#f2f4f7`, dark `#1f252d`): muted backgrounds, ghost hover.
- **Slate Text** (`#515c65`, dark `#9aa4af`): secondary text, placeholders.
- **Hairline** (`#dee2e6`, dark `#2a313b`): borders and input strokes.
- **Alert Red** (`#dc3545`, dark `#f08c96` on warm ink): destructive actions.

### Access spectrum (icon-only, shared with facet filters)

Lightness and saturation climb with openness; each entry lists its dark-mode
pair.

- **Closed** (`#64748b` / `#94a3b8`): dull slate, the locked end.
- **Hybrid** (`#4d84c7` / `#82b1e4`): muted blue.
- **Generic** (`#8f7ae5` / `#a99af0`): muted violet.
- **Gold** (`#f4aa2a` / `#fbbf24`): bright amber.
- **Diamond** (`#4fe4f8` / `#67e8f9`): light saturated cyan, the open end.
- **Deal** (`#047857` / `#6ee7b7`): emerald for transformative-deal coverage.

## Typography

Inter carries all body and UI text; Montserrat carries headings, the wordmark,
and lockup wordmarks. Both load via `next/font/google` (self-hosted at build
time) with system fallbacks. Headings use `tracking-tight` (-0.025em).

- **Display** (`{typography.display}`): page h1s and the nav wordmark,
  Montserrat 700 at 1.5rem on the landing chooser.
- **Headline** (`{typography.headline}`): section h2s, Montserrat 700.
- **Title** (`{typography.title}`): card titles, Montserrat 600 at 1.125rem.
- **Body** (`{typography.body}`): Inter 400 at 1rem; tables and dense lists
  drop to 0.875rem.
- **Label** (`{typography.label}`): buttons and controls, Inter 500 at
  0.875rem.
- **Micro** (`{typography.micro}`): pill badges, Inter 600 at 0.75rem; the
  footer attribution line runs at 0.75rem in white/70.

## Layout

- App shell: sticky-less top header with brand link, nav, theme toggle;
  content column; navy footer band. Content containers are `max-w-screen-2xl`
  with 16px side padding; the landing chooser and docs column narrow to
  `max-w-2xl`.
- Nav wraps below `sm`: the link row becomes full-width and horizontally
  scrollable with the scrollbar hidden. The brand wordmark is
  `whitespace-nowrap` and never wraps.
- Inputs render at 1rem below 560px and 0.875rem above, because iOS Safari
  zooms any focused input smaller than 16px.
- Spacing rhythm uses Tailwind steps: 8px inside controls, 16px gaps and
  padding, 24px card padding.
- Print (docs pages): an A4 stylesheet forces the paper palette by
  overriding token values inside `@media print` (so dark mode cannot print
  near-black panels), hides site chrome and floating widgets, and keeps
  tables, code blocks, and list items unbroken.

## Elevation & Depth

Flat by default, bordered by **Hairline**. Elevation is rationed: cards carry
a single `shadow-sm`, nothing else lifts. No zero-offset colored halos; depth
comes from surface color steps (paper → card → mist) rather than shadow
stacks. Hover feedback is color shifts, not lifts (the one exception: access
lockups translate up 1px on hover). Native surfaces belong to the theme:
text selection is a 28% orange tint mix, scrollbars use a foreground-mix
color, focus is a 2px orange ring with offset.

## Shapes

- **Base radius 8px** (`{rounded.base}`): buttons, cards, inputs, panels.
  One radius everywhere; components read as one family.
- **Pill radius** (`{rounded.pill}`): status badges only.
- Access lockups are bare SVG lock-and-wordmark combinations with no
  container. The 14px lock icon keeps a fixed shackle geometry (hinge on the
  left leg base at `3 6.6`) across its four open states so the pose reads as
  one object at every access level.

## Components

- **Button** (cva variants): `default` (signal orange / warm ink, hover to
  signal-orange-hover), `secondary` (navy / white, hover dims opacity),
  `outline` (card surface, hairline border, mist hover), `ghost` (ink text,
  mist hover), `link` (ember text, underline on hover). Sizes: 40px default,
  32px sm, 48px lg, 40px square icon. All variants get a 2px orange
  focus-visible ring with 2px offset and dim to 50% opacity when disabled.
  Component philosophy: **tactile and confident** — hover and pressed states
  should feel physical and immediate; evolve hovers toward clearer state
  feedback rather than decoration.
- **Card**: card-white surface, hairline border, base radius, one
  `shadow-sm`; 24px padding, Montserrat 600 titles at 1.125rem.
- **Input**: card-white surface, hairline border, base radius, 40px height;
  placeholder in slate-text; orange focus ring. Keeps the 16px phone font
  rule above.
- **Badge pills**: rounded-full 2px/10px pills in five variants (orange,
  navy, outline, mist, destructive) at Inter 600 0.75rem. Reserved for
  statuses; access levels never use pills.
- **Access lockups** (the signature): bare SVG padlock + Montserrat
  wordmark. Shackle state encodes access level (closed/ajar/open/wide,
  hinged at the left leg); sparkle count and size grow with openness; one
  color per access type from the access spectrum. A 7-second kinetic cycle
  periodically slams the shackle shut and springs it open, staggered per
  state via negative delays; hover restarts the cycle by swapping to
  duplicated `-go` keyframes (an animation-name change restarts a CSS
  animation). Static poses survive with animations off because keyframes
  animate deltas around the static pose. Everything stops under
  `prefers-reduced-motion`.
- **Brand lockups** (`components/logo.tsx`): the OJB wordmark (stacked
  cyan/neutral/orange) and monogram (O-J-B ligature), generated from
  `public/ojb-*.svg`. Brand letters keep fixed cyan and signal orange;
  neutral letters use `currentColor`, so the marks adapt to both themes.
  Usage: the stacked wordmark is the nav identity (h-11 in the 64px header
  bar, link carries `aria-label`) and the landing chooser hero (h-36,
  centered above the tagline); the monogram is the favicon
  (`app/icon.svg`, ink letters). Sizing keeps each mark's aspect ratio.
- **Header and nav**: brand link in Montserrat 700 tracking-tight, scoped to
  the institution prefix; nav links text-sm with hidden-overflow horizontal
  scroll on phones.
- **Footer band**: contract navy, white text; institution links plus the
  GitHub source link, and a 0.75rem white/70 attribution line naming every
  upstream data source (OpenAlex, cOAlition S JCT, openaccess.nl, OpenAPC,
  Scimago, Jisc Open Policy Finder). "Links on every page lead to the
  upstream source" is a brand commitment, keep the line.

## Do's and Don'ts

- **Do** route every theme color through the token block in
  `frontend/app/globals.css`; re-theming an institution means replacing that
  one block. **Don't** hardcode theme colors in components.
- **Exception:** the access spectrum constants in `components/badges.tsx` are
  sanctioned fixed colors, always shipped with their `dark:` pairs.
- **Do** set text on signal orange to Warm Ink (`#1c0508`), and use Ember
  Text (`#b34f00` / `#ffa25e`) for orange text on page backgrounds. **Don't**
  use white on orange or raw orange as text on white; both fail contrast.
- **Don't** put access lockups inside pill containers; they are bare
  lockups.
- **Do** keep every badge animation survivable as a static pose and fully
  disabled under `prefers-reduced-motion`.
- **Do** keep focus-visible rings on all interactive elements and the 16px
  minimum input font on phones.
- **Don't** stack shadows or add zero-offset glows; depth is one card
  shadow plus surface color steps.
- **Do** keep the docs print stylesheet overriding token values (not
  individual rules), so dark mode prints on paper.
