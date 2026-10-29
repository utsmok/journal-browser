/**
 * Access lockups: single-family SVG badges that replace generic pills.
 *
 * One visual system, borrowed from the old journal browser's integrated
 * text-and-lock icon: a padlock whose shackle opens progressively with
 * access level (closed → ajar → swung → wide), a baseline-aligned
 * Montserrat wordmark, and one color per access type. Rendered bare (no
 * pill container) so rows read as icon lockups, not chips.
 */

const WORDMARK_FONT = "var(--font-montserrat), var(--font-inter), ui-sans-serif, sans-serif";

type LockState = "closed" | "ajar" | "open" | "wide";

/**
 * Shackle transforms: the lock opens progressively from closed to wide.
 * The shackle path is M3 6.6 V4.2 a3 3 0 0 1 6 0 V6.6 — legs on x=3/9,
 * centered on the body (rect x 1..11, center 6). Open states hinge the
 * whole shackle on the LEFT leg base (3 6.6), so that leg stays seated in
 * the body while the right leg lifts; the downward translate re-seats the
 * hinge and keeps the swung shackle inside the 14px icon box.
 */
const SHACKLE_TRANSFORM: Record<LockState, string | undefined> = {
  closed: undefined,
  ajar: "translate(0 0.4) rotate(-12 3 6.6)",
  open: "translate(0 0.7) rotate(-25 3 6.6)",
  wide: "translate(0 1.3) rotate(-42 3 6.6)",
};

/** Animation metadata per state: the shackle pose (as deltas the CSS
 * keyframes cancel and overshoot around) and a stagger offset so the four
 * badge types don't cycle in sync. Negative delays start mid-cycle. */
const SHACKLE_POSE: Record<LockState, { rot: string; ty: string; d: string }> = {
  closed: { rot: "0deg", ty: "0px", d: "0s" },
  ajar: { rot: "-12deg", ty: "0.4px", d: "-1.4s" },
  open: { rot: "-25deg", ty: "0.7px", d: "-2.8s" },
  wide: { rot: "-42deg", ty: "1.3px", d: "-4.2s" },
};

/** Icon-only access-type colors, shared with the facet filters. Lightness
 * and saturation climb with openness: closed (dull slate) → hybrid (muted
 * blue) → generic (muted violet) → gold (bright amber) → diamond (light,
 * saturated cyan). */
export const ACCESS_TEXT = {
  gold: "text-[#f4aa2a] dark:text-amber-400",
  diamond: "text-[#4fe4f8] dark:text-cyan-300",
  generic: "text-[#8f7ae5] dark:text-[#a99af0]",
  hybrid: "text-[#4d84c7] dark:text-[#82b1e4]",
  closed: "text-slate-500 dark:text-slate-400",
  deal: "text-emerald-700 dark:text-emerald-300",
  brand: "text-[var(--primary-text)]",
} as const;

/** Four-point sparkle at (cx,cy), radius r, drawn through the center. */
function sparklePath(cx: number, cy: number, r: number) {
  return (
    `M${cx} ${cy - r} Q${cx} ${cy} ${cx + r} ${cy} Q${cx} ${cy} ${cx} ${cy + r}` +
    ` Q${cx} ${cy} ${cx - r} ${cy} Q${cx} ${cy} ${cx} ${cy - r}Z`
  );
}

/** Sparkle count and size grow with openness. Positions sit right of the
 * shackle swing (it rotates left) and stay inside the 14px icon box. */
const SPARKLES: Record<LockState, [number, number, number][]> = {
  closed: [],
  ajar: [[12.6, 3.4, 1.1]],
  open: [
    [12.8, 2.2, 1.2],
    [11.0, 4.6, 0.8],
  ],
  wide: [
    [12.9, 1.8, 1.4],
    [10.9, 3.4, 0.9],
    [12.9, 5.6, 0.8],
  ],
};

export function LockIcon({ state }: { state: LockState }) {
  const pose = SHACKLE_POSE[state];
  return (
    <>
      <rect x={1} y={7} width={10} height={7} rx={1.8} fill="currentColor" />
      <g
        className={`jb-shackle${state === "closed" ? " jb-shackle-locked" : ""}`}
        style={{ "--rot": pose.rot, "--ty": pose.ty, "--d": pose.d } as React.CSSProperties}
      >
        <path
          d="M3 6.6 V4.2 a3 3 0 0 1 6 0 V6.6"
          transform={SHACKLE_TRANSFORM[state]}
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
        />
      </g>
      {SPARKLES[state].map(([cx, cy, r], i) => (
        <path
          key={`${cx},${cy}`}
          className="jb-sparkle"
          style={{ "--d": pose.d, animationDelay: `calc(${pose.d} - ${i * 0.05}s)` } as React.CSSProperties}
          d={sparklePath(cx, cy, r)}
          fill="currentColor"
        />
      ))}
    </>
  );
}

/** Author copy in a repository: document tray with an arrow dropping in. */
function GreenGlyph() {
  return (
    <>
      <path
        d="M2 10.5 V12.6 a1.4 1.4 0 0 0 1.4 1.4 h7.2 a1.4 1.4 0 0 0 1.4 -1.4 V10.5"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M7 3 V9.5 M4.5 7 L7 9.5 L9.5 7"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  );
}

/** Free to read at the publisher: an eye. */
function BronzeGlyph() {
  return (
    <>
      <path
        d="M1 8 C3 4.5 5 3 7 3 C9 3 11 4.5 13 8 C11 11.5 9 13 7 13 C5 13 3 11.5 1 8 Z"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
        strokeLinejoin="round"
      />
      <circle cx={7} cy={8} r={2} fill="currentColor" />
    </>
  );
}

/** UT open access deal: signed agreement with a check. */
export function DealGlyph() {
  return (
    <>
      <rect
        x={1.6}
        y={2.6}
        width={9.4}
        height={11}
        rx={1.6}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
      />
      <path
        d="M4.2 8.2 L6.1 10.1 L9.4 5.9"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </>
  );
}

/** Journal rank podium: ascending bars; color carries the Q1 emphasis. */
export function QuartileGlyph() {
  return (
    <>
      <rect x={1.2} y={9.8} width={2.8} height={4.2} rx={1} fill="currentColor" />
      <rect x={5.1} y={7.4} width={2.8} height={6.6} rx={1} fill="currentColor" />
      <rect x={9} y={4.6} width={2.8} height={9.4} rx={1} fill="currentColor" />
    </>
  );
}

function Lockup({
  label,
  width,
  title,
  className,
  children,
}: {
  label: string;
  /** ViewBox width; must fit the wordmark (Montserrat Bold 10px, +1.1 tracking). */
  width: number;
  title: string;
  className: string;
  children: React.ReactNode;
}) {
  return (
    <span className={`jb-badge inline-flex shrink-0 items-center ${className}`} title={title}>
      <svg
        viewBox={`0 0 ${width} 16`}
        className="h-4 w-auto overflow-visible"
        role="img"
        aria-label={title}
        focusable="false"
      >
        {children}
        <text
          x={15}
          y={14}
          fontSize={10}
          fontWeight={700}
          letterSpacing={1.1}
          fill="currentColor"
          fontFamily={WORDMARK_FONT}
        >
          {label}
        </text>
      </svg>
    </span>
  );
}

type OaType = "gold" | "diamond" | "generic" | "hybrid" | "subscription";

/** Access-type lockups: progressive shackle + integrated wordmark. */
const OA_TYPE_META: Record<OaType, { label: string; title: string; lock: LockState; className: string; width: number }> = {
  gold: {
    label: "OPEN",
    title: "Gold open access — every article is published open access on the journal's own site.",
    lock: "open",
    className: ACCESS_TEXT.gold,
    width: 50,
  },
  diamond: {
    label: "DIAMOND",
    title: "Diamond open access — fully open access journal without fees for readers or authors.",
    lock: "wide",
    className: ACCESS_TEXT.diamond,
    width: 76,
  },
  generic: {
    label: "OA",
    title: "Open access journal — the exact OA model (gold or diamond) could not be determined from the sources.",
    lock: "wide",
    className: ACCESS_TEXT.generic,
    width: 34,
  },
  hybrid: {
    label: "HYBRID",
    title: "Hybrid journal — subscription journal where individual articles can be made open access, often via an open access deal.",
    lock: "ajar",
    className: ACCESS_TEXT.hybrid,
    width: 68,
  },
  subscription: {
    label: "CLOSED",
    title: "Subscription journal — reading the published version requires a subscription.",
    lock: "closed",
    className: ACCESS_TEXT.closed,
    width: 68,
  },
};

/**
 * OA-type badge (gold / diamond / hybrid / subscription). The backend
 * computes oa_type; when it is absent (old backend) we fall back to
 * Subscription only for journals known not to be OA, and omit otherwise
 * rather than guess.
 */
export function OaTypeBadge({
  oaType,
  isOa,
}: {
  oaType?: OaType | null;
  isOa?: boolean | null;
}) {
  const type: OaType | null = oaType ?? (isOa === false ? "subscription" : null);
  if (!type) return null;
  const meta = OA_TYPE_META[type];
  return (
    <Lockup label={meta.label} width={meta.width} title={meta.title} className={meta.className}>
      <LockIcon state={meta.lock} />
    </Lockup>
  );
}

/** Work-level OA statuses; one color map shared by chips and the trend chart. */
export const OA_STATUS_ORDER = [
  "gold",
  "hybrid",
  "green",
  "bronze",
  "diamond",
  "closed",
] as const;

export const OA_STATUS_META: Record<
  string,
  { label: string; bar: string }
> = {
  gold: { label: "Gold", bar: "bg-amber-400 dark:bg-amber-500" },
  hybrid: { label: "Hybrid", bar: "bg-blue-400 dark:bg-blue-500" },
  green: { label: "Green", bar: "bg-emerald-400 dark:bg-emerald-500" },
  bronze: { label: "Bronze", bar: "bg-orange-400 dark:bg-orange-500/80" },
  diamond: { label: "Diamond", bar: "bg-teal-400 dark:bg-teal-500" },
  closed: { label: "Closed", bar: "bg-slate-300 dark:bg-slate-600" },
};

/** Work-level status lockup; reuses the journal lock icons where they map. */
const OA_STATUS_LOCKUP: Record<string, { label: string; title: string; className: string; width: number; glyph: React.ReactNode }> = {
  gold: { ...OA_TYPE_META.gold, glyph: <LockIcon state="open" /> },
  hybrid: { ...OA_TYPE_META.hybrid, glyph: <LockIcon state="ajar" /> },
  diamond: { ...OA_TYPE_META.diamond, glyph: <LockIcon state="wide" /> },
  closed: {
    label: "CLOSED",
    title: "Closed — no openly accessible version of this publication was found.",
    className: OA_TYPE_META.subscription.className,
    width: OA_TYPE_META.subscription.width,
    glyph: <LockIcon state="closed" />,
  },
  green: {
    label: "GREEN",
    title: "Green open access — an author copy of this publication is freely available in a repository.",
    className: "text-emerald-700 dark:text-emerald-300",
    width: 59,
    glyph: <GreenGlyph />,
  },
  bronze: {
    label: "BRONZE",
    title: "Bronze open access — free to read on the publisher's site, without an explicit open license.",
    className: "text-orange-700 dark:text-orange-300",
    width: 68,
    glyph: <BronzeGlyph />,
  },
};

/** Small OA-status lockup for a single work; legend/chart reuse the same colors. */
export function OaStatusChip({ status }: { status?: string | null }) {
  if (!status) return null;
  const meta = OA_STATUS_LOCKUP[status];
  if (!meta) return null;
  return (
    <Lockup label={meta.label} width={meta.width} title={meta.title} className={meta.className}>
      {meta.glyph}
    </Lockup>
  );
}

export function DealBadge({ covered }: { covered: boolean }) {
  if (!covered) return null;
  return (
    <Lockup
      label="DEAL"
      width={50}
      title="Open access deal — APCs for corresponding authors are covered (fully or partly) by an institutional agreement."
      className={ACCESS_TEXT.deal}
    >
      <DealGlyph />
    </Lockup>
  );
}

export function QuartileBadge({ quartile }: { quartile: string | null }) {
  if (!quartile) return null;
  const isTop = quartile === "Q1";
  return (
    <Lockup
      label={quartile.toUpperCase()}
      width={30}
      title={`Journal impact quartile in its subject category — Q1 means top 25%. This journal: ${quartile}.`}
      className={isTop ? "text-[var(--primary-text)]" : "text-[var(--muted-foreground)]"}
    >
      <QuartileGlyph />
    </Lockup>
  );
}
