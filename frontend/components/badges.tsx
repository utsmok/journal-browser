"use client";

import { CircleCheck, CircleHelp, CircleX } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  ACCESS_TEXT,
  BronzeGlyph,
  DealGlyph,
  DoajGlyph,
  GreenGlyph,
  LockIcon,
  type LockState,
  QuartileGlyph,
} from "@/components/data-icons";
import type { WorkParent } from "@/lib/api";

export { ACCESS_TEXT, DealGlyph, DoajGlyph, LockIcon, QuartileGlyph };

const WORDMARK_FONT = "var(--font-montserrat), var(--font-inter), ui-sans-serif, sans-serif";

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
  gold: { bar: "bg-(--oa-gold)" },
  hybrid: { bar: "bg-blue-400 dark:bg-blue-500" },
  green: { bar: "bg-green-600 dark:bg-green-500" },
  bronze: { bar: "bg-(--oa-bronze)" },
  diamond: { bar: "bg-(--oa-diamond)" },
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
    className: "text-rose-700 dark:text-rose-300",
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

/** Pure-registration state of a grouped gap entry's parent work: green
 * check when the main work is registered in Pure, red cross when it is
 * missing, gray question mark while the backfill has not fetched it.
 * Colors follow the FunderFit tiers; labels live under
 * common.workParts.groupBadge. */
const PURE_REGISTERED_SPEC = {
  yes: {
    Icon: CircleCheck,
    color: "text-emerald-700 dark:text-emerald-400",
    labelKey: "workParts.groupBadge.inPure",
  },
  no: {
    Icon: CircleX,
    color: "text-red-700 dark:text-red-400",
    labelKey: "workParts.groupBadge.notInPure",
  },
  unchecked: {
    Icon: CircleHelp,
    color: "text-[var(--muted-foreground)]",
    labelKey: "workParts.groupBadge.notChecked",
  },
} as const;

export function PureRegisteredBadge({
  registered,
  className,
}: {
  registered: boolean | null;
  className?: string;
}) {
  const t = useTranslations("common");
  const spec =
    registered == null
      ? PURE_REGISTERED_SPEC.unchecked
      : registered
        ? PURE_REGISTERED_SPEC.yes
        : PURE_REGISTERED_SPEC.no;
  const label = t(spec.labelKey);
  const { Icon, color } = spec;
  return (
    <span
      className={`jb-badge inline-flex shrink-0 items-center gap-0.5 text-xs font-normal ${color}${className ? ` ${className}` : ""}`}
      title={label}
    >
      <Icon aria-hidden className="size-3.5" />
      {label}
    </span>
  );
}

/** "Chapter of <book>" / "Part of <work>" chip for OpenAlex-side work
 * rows: a rel=volume parent names the row a chapter, any other parent a
 * part. The parent's name is shown; without any usable name the chip
 * degrades to a bare "Part". Nothing renders for standalone rows. */
export function PartChip({ isPart, parents }: { isPart: boolean; parents: WorkParent[] }) {
  const t = useTranslations("common");
  if (!isPart) return null;
  const volume = parents.find((p) => p.rel === "volume");
  const named = volume?.name ? volume : parents.find((p) => p.name);
  const label = named?.name
    ? t(volume ? "workParts.chapterOf" : "workParts.partOf", { name: named.name })
    : t("workParts.part");
  return (
    <span className="inline-flex shrink-0 items-center rounded-[var(--radius)] border border-[var(--border)] px-2 py-0.5 text-xs font-normal text-[var(--muted-foreground)]">
      {label}
    </span>
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
