"use client";

import { CircleCheck, CircleHelp, CircleX } from "lucide-react";
import { useTranslations } from "next-intl";

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
          style={
            {
              "--d": pose.d,
              animationDelay: `calc(${pose.d} - ${i * 0.05}s)`,
            } as React.CSSProperties
          }
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
  overlay,
  children,
}: {
  label: string;
  /** ViewBox width; must fit the wordmark (Montserrat Bold 10px, +1.1 tracking). */
  width: number;
  title: string;
  className: string;
  overlay?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <span
      className={`jb-badge relative inline-flex shrink-0 items-center ${className}`}
      title={title}
    >
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
      {overlay}
    </span>
  );
}

type OaType = "gold" | "diamond" | "generic" | "hybrid" | "subscription";

/** Access-type lockups: progressive shackle + integrated wordmark. The
 * SVG wordmark labels stay fixed (they set the viewBox width); the hover
 * text and aria-label come from the messages. */
const OA_TYPE_META: Record<
  OaType,
  { label: string; titleKey: string; lock: LockState; className: string; width: number }
> = {
  gold: {
    label: "OPEN",
    titleKey: "badges.oaTypeGoldTitle",
    lock: "open",
    className: ACCESS_TEXT.gold,
    width: 50,
  },
  diamond: {
    label: "DIAMOND",
    titleKey: "badges.oaTypeDiamondTitle",
    lock: "wide",
    className: ACCESS_TEXT.diamond,
    width: 76,
  },
  generic: {
    label: "OA",
    titleKey: "badges.oaTypeGenericTitle",
    lock: "wide",
    className: ACCESS_TEXT.generic,
    width: 34,
  },
  hybrid: {
    label: "HYBRID",
    titleKey: "badges.oaTypeHybridTitle",
    lock: "ajar",
    className: ACCESS_TEXT.hybrid,
    width: 68,
  },
  subscription: {
    label: "CLOSED",
    titleKey: "badges.oaTypeSubscriptionTitle",
    lock: "closed",
    className: ACCESS_TEXT.closed,
    width: 68,
  },
};

/**
 * OA-type badge (gold / diamond / generic / hybrid / subscription). The
 * backend models oa_type as a plain string; unknown values render nothing
 * rather than guessing.
 */
export function OaTypeBadge({ oaType, isOa }: { oaType?: string | null; isOa?: boolean | null }) {
  const t = useTranslations("common");
  const type: string | null = oaType ?? (isOa === false ? "subscription" : null);
  if (!type || !(type in OA_TYPE_META)) return null;
  const meta = OA_TYPE_META[type as OaType];
  return (
    <Lockup
      label={meta.label}
      width={meta.width}
      title={t(meta.titleKey)}
      className={meta.className}
    >
      <LockIcon state={meta.lock} />
    </Lockup>
  );
}

/** Work-level OA statuses; one color map shared by chips and the trend chart. */
export const OA_STATUS_ORDER = ["gold", "hybrid", "green", "bronze", "diamond", "closed"] as const;

/** Work-level OA statuses; one color map shared by chips and the trend
 * chart. Display names live in the messages (trend.status*). */
export const OA_STATUS_META: Record<string, { bar: string }> = {
  gold: { bar: "bg-amber-400 dark:bg-amber-500" },
  hybrid: { bar: "bg-blue-400 dark:bg-blue-500" },
  green: { bar: "bg-green-600 dark:bg-green-500" },
  bronze: { bar: "bg-orange-400 dark:bg-orange-500/80" },
  diamond: { bar: "bg-[#4fe4f8] dark:bg-cyan-300" },
  closed: { bar: "bg-slate-300 dark:bg-slate-600" },
};

/** Work-level status lockup; reuses the journal lock icons where they map. */
const OA_STATUS_LOCKUP: Record<
  string,
  { label: string; titleKey: string; className: string; width: number; glyph: React.ReactNode }
> = {
  gold: { ...OA_TYPE_META.gold, glyph: <LockIcon state="open" /> },
  hybrid: { ...OA_TYPE_META.hybrid, glyph: <LockIcon state="ajar" /> },
  diamond: { ...OA_TYPE_META.diamond, glyph: <LockIcon state="wide" /> },
  closed: {
    label: "CLOSED",
    titleKey: "badges.statusClosedTitle",
    className: OA_TYPE_META.subscription.className,
    width: OA_TYPE_META.subscription.width,
    glyph: <LockIcon state="closed" />,
  },
  green: {
    label: "GREEN",
    titleKey: "badges.statusGreenTitle",
    className: "text-emerald-700 dark:text-emerald-300",
    width: 59,
    glyph: <GreenGlyph />,
  },
  bronze: {
    label: "BRONZE",
    titleKey: "badges.statusBronzeTitle",
    className: "text-orange-700 dark:text-orange-300",
    width: 68,
    glyph: <BronzeGlyph />,
  },
};

/** Small OA-status lockup for a single work; legend/chart reuse the same colors. */
export function OaStatusChip({
  status,
  source,
}: {
  status?: string | null;
  /** Provenance of the status (api oa_status_source); 'pure' on green
   * DOI-less rows means the repository copy, not the venue's OA model. */
  source?: string | null;
}) {
  const t = useTranslations("common");
  if (!status) return null;
  // The OpenAlex oa_status sync only overwrites DOI-matched rows, so a
  // green status on a DOI-less Pure record is Pure's own access flag:
  // it only means Pure holds a freely readable file.
  const meta =
    status === "green" && source === "pure"
      ? {
          label: "OPEN (PURE)",
          titleKey: "badges.statusPureTitle",
          className: "text-emerald-700 dark:text-emerald-300",
          width: 122,
          glyph: <GreenGlyph />,
        }
      : OA_STATUS_LOCKUP[status];
  if (!meta) return null;
  return (
    <Lockup
      label={meta.label}
      width={meta.width}
      title={t(meta.titleKey)}
      className={meta.className}
    >
      {meta.glyph}
    </Lockup>
  );
}

/** Why a "missing from Pure" row is in fact held by Pure, when a record
 * was identified. Linked to that record's public page when known. */
const PURE_MATCH_META: Record<string, { labelKey: string; titleKey: string }> = {
  doi_in_pure: {
    labelKey: "badges.pureMatchOtherRecordLabel",
    titleKey: "badges.pureMatchOtherRecordTitle",
  },
  parent_book_in_pure: {
    labelKey: "badges.pureMatchParentBookLabel",
    titleKey: "badges.pureMatchParentBookTitle",
  },
  same_title_in_pure: {
    labelKey: "badges.pureMatchSameTitleLabel",
    titleKey: "badges.pureMatchSameTitleTitle",
  },
};

export function PureMatchBadge({ match, url }: { match?: string | null; url?: string | null }) {
  const t = useTranslations("common");
  if (!match) return null;
  const meta = PURE_MATCH_META[match];
  if (!meta) return null;
  const badge = (
    <span
      className="inline-flex shrink-0 items-center rounded-[var(--radius)] border border-[var(--border)] px-2 py-0.5 text-[11px] font-normal text-[var(--muted-foreground)]"
      title={t(meta.titleKey)}
    >
      {t(meta.labelKey)}
    </span>
  );
  if (!url) return badge;
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="underline-offset-2 hover:text-[var(--primary-text)] hover:underline"
      title={t(meta.titleKey)}
    >
      {badge}
    </a>
  );
}

export function DealBadge({ covered, capped = false }: { covered: boolean; capped?: boolean }) {
  const t = useTranslations("common");
  if (!covered) return null;
  return (
    <Lockup
      label="DEAL"
      width={50}
      title={capped ? t("badges.dealCappedTitle") : t("badges.dealCoveredTitle")}
      className={capped ? `${ACCESS_TEXT.deal} grayscale opacity-60` : ACCESS_TEXT.deal}
      overlay={
        capped ? (
          <span
            aria-hidden
            className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center text-[var(--primary-text)]"
          >
            <span
              className="-rotate-6 rounded-[2px] border-[1.5px] border-current bg-[var(--card)]/85 px-[3px] py-px text-[8px] font-black leading-none tracking-[0.04em]"
              style={{ fontFamily: WORDMARK_FONT }}
            >
              CAPPED
            </span>
          </span>
        ) : undefined
      }
    >
      <DealGlyph />
    </Lockup>
  );
}

export function QuartileBadge({ quartile }: { quartile: string | null }) {
  const t = useTranslations("common");
  if (!quartile) return null;
  const isTop = quartile === "Q1";
  return (
    <Lockup
      label={quartile.toUpperCase()}
      width={30}
      title={t("badges.quartileTitle", { quartile })}
      className={isTop ? "text-[var(--primary-text)]" : "text-[var(--muted-foreground)]"}
    >
      <QuartileGlyph />
    </Lockup>
  );
}

/** Funder-fit tier for the selected funder: green check = compliant,
 * amber question = check, red cross = no. Reasons ride in the tooltip.
 * status null (text-only funder policy) renders nothing here — the detail
 * page carries that message instead. */
const FIT_SPEC = {
  compliant: {
    Icon: CircleCheck,
    color: "text-emerald-700 dark:text-emerald-400",
  },
  check: { Icon: CircleHelp, color: "text-amber-600 dark:text-amber-400" },
  no: { Icon: CircleX, color: "text-red-700 dark:text-red-400" },
} as const;

const FIT_LABEL_KEYS = {
  compliant: "badges.funderFitCompliant",
  check: "badges.funderFitCheck",
  no: "badges.funderFitNo",
} as const;

export function FunderFitBadge({
  status,
  reasons,
}: {
  status: "compliant" | "check" | "no" | null | undefined;
  reasons: string[];
}) {
  const t = useTranslations("common");
  if (!status) return null;
  const { Icon, color } = FIT_SPEC[status];
  const label = t(FIT_LABEL_KEYS[status]);
  return (
    <span
      className={`jb-badge inline-flex shrink-0 items-center gap-0.5 ${color}`}
      title={reasons.length > 0 ? `${label}. ${reasons.join(" ")}` : label}
    >
      <Icon aria-label={t("badges.funderFitTooltip", { label })} className="size-4" role="img" />
    </span>
  );
}
