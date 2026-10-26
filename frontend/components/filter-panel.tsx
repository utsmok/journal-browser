import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";

import { ACCESS_TEXT, DealGlyph, LockIcon, QuartileGlyph } from "@/components/badges";
import { useSiteMeta } from "@/hooks/use-site-meta";

const OA_TYPE_LABELS: Record<string, string> = {
  gold: "Gold OA",
  diamond: "Diamond OA",
  hybrid: "Hybrid",
  subscription: "Subscription (closed)",
};

type FacetValue = { value: string; count?: number; label?: string };

type FacetsData = Record<string, Record<string, number>>;

type FilterSelection = {
  deal: string;
  oa: string | null;
  doaj: string | null;
  quartile: string;
  topic: string;
  publisher: string;
  hasApc: string | null;
  hasWorks: string | null;
  /** Multi-select: values OR together (single-select groups do not). */
  oaTypes: string[];
};

type FacetGroupDef = {
  key: string;
  label: string;
  values: FacetValue[];
  activeValues: string[];
  defaultOpen: boolean;
};

/** Top 8 by count, with the active value kept visible even outside the top 8. */
function topValues(
  counts: Record<string, number> | undefined,
  active: string,
): FacetValue[] {
  const values: FacetValue[] = Object.entries(counts ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([value, count]) => ({ value, count }));
  if (active && !values.some((t) => t.value === active))
    values.unshift({ value: active });
  return values;
}

/** No deal: the agreement document with a slash through it. */
function NoDealGlyph() {
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
        d="M3.8 4.4 L9.8 13.2"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
        strokeLinecap="round"
      />
    </>
  );
}

/** DOAJ: the directory volume it is registered in. */
function DoajGlyph() {
  return (
    <>
      <rect
        x={2.2}
        y={2.2}
        width={9.6}
        height={11.6}
        rx={1.6}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
      />
      <path d="M5.4 2.2 V13.8" stroke="currentColor" strokeWidth={1.8} />
    </>
  );
}

/** APC: the fee note. */
function ApcGlyph() {
  return (
    <>
      <rect
        x={1.2}
        y={4.6}
        width={13.6}
        height={6.8}
        rx={1.6}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
      />
      <circle cx={8} cy={8} r={1.7} fill="currentColor" />
    </>
  );
}

function WorksGlyph() {
  return (
    <>
      <rect
        x={2.8}
        y={1.6}
        width={10.4}
        height={12.8}
        rx={1.6}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
      />
      <path
        d="M5.6 5.4h4.8M5.6 8h4.8M5.6 10.6h3"
        stroke="currentColor"
        strokeWidth={1.8}
        strokeLinecap="round"
      />
    </>
  );
}

/**
 * Active-state tints reuse the AA-audited hue pairs from the status chips:
 * idle options show a colored icon on neutral ground, selected options fill
 * with the same hue.
 */
const TINTS = {
  emerald:
    "border-emerald-300 bg-emerald-100 text-emerald-900 dark:border-emerald-400/40 dark:bg-emerald-400/15 dark:text-emerald-200",
  amber:
    "border-amber-300 bg-amber-100 text-amber-900 dark:border-amber-400/40 dark:bg-amber-400/15 dark:text-amber-200",
  cyan: "border-cyan-300 bg-cyan-100 text-cyan-900 dark:border-cyan-400/40 dark:bg-cyan-400/15 dark:text-cyan-200",
  blue: "border-blue-300 bg-blue-100 text-blue-900 dark:border-blue-400/40 dark:bg-blue-400/15 dark:text-blue-200",
  slate: "border-slate-300 bg-slate-100 text-slate-700 dark:border-slate-500/40 dark:bg-slate-500/15 dark:text-slate-200",
  teal: "border-teal-300 bg-teal-100 text-teal-900 dark:border-teal-400/40 dark:bg-teal-400/15 dark:text-teal-200",
  brand: "border-[#f06e00]/50 bg-[#f06e00]/10 text-[var(--primary-text)] dark:border-[#f06e00]/40 dark:bg-[#f06e00]/15 dark:text-[#ffa25e]",
};

/** Idle-state icon colors: same hues as the results-list lockups. */
const FACET_ICON_TEXT: Record<string, string> = {
  "deal:covered": ACCESS_TEXT.deal,
  "deal:other": ACCESS_TEXT.closed,
  "oa:true": ACCESS_TEXT.brand,
  "oa:false": ACCESS_TEXT.closed,
  "oa_type:gold": ACCESS_TEXT.gold,
  "oa_type:diamond": ACCESS_TEXT.diamond,
  "oa_type:hybrid": ACCESS_TEXT.hybrid,
  "oa_type:subscription": ACCESS_TEXT.closed,
  "doaj:true": "text-teal-700 dark:text-teal-300",
  "doaj:false": ACCESS_TEXT.closed,
  "has_apc:true": ACCESS_TEXT.brand,
  "has_apc:false": ACCESS_TEXT.closed,
  "has_works:true": ACCESS_TEXT.brand,
  "has_works:false": ACCESS_TEXT.closed,
  "quartile:Q1": ACCESS_TEXT.brand,
  "quartile:Q2": ACCESS_TEXT.closed,
  "quartile:Q3": ACCESS_TEXT.closed,
  "quartile:Q4": ACCESS_TEXT.closed,
};

/** Icon + selected tint per facet option; unlisted options stay neutral. */
function facetLook(key: string, value: string): { icon: ReactNode; tint: string } {
  switch (`${key}:${value}`) {
    case "deal:covered":
      return { icon: <DealGlyph />, tint: TINTS.emerald };
    case "oa:true":
      return { icon: <LockIcon state="open" />, tint: TINTS.brand };
    case "oa:false":
      return { icon: <LockIcon state="closed" />, tint: TINTS.slate };
    case "oa_type:gold":
      return { icon: <LockIcon state="open" />, tint: TINTS.amber };
    case "oa_type:diamond":
      return { icon: <LockIcon state="wide" />, tint: TINTS.cyan };
    case "oa_type:hybrid":
      return { icon: <LockIcon state="ajar" />, tint: TINTS.blue };
    case "oa_type:subscription":
      return { icon: <LockIcon state="closed" />, tint: TINTS.slate };
    case "doaj:true":
    case "doaj:false":
      return { icon: <DoajGlyph />, tint: value === "true" ? TINTS.teal : TINTS.slate };
    case "has_apc:true":
    case "has_apc:false":
      return { icon: <ApcGlyph />, tint: value === "true" ? TINTS.brand : TINTS.slate };
    case "has_works:true":
    case "has_works:false":
      return { icon: <WorksGlyph />, tint: value === "true" ? TINTS.brand : TINTS.slate };
    default:
      // The deal facet's negative value is backend-defined; anything that is
      // not "covered" is a no-deal option.
      if (key === "deal")
        return { icon: <NoDealGlyph />, tint: TINTS.slate };
      if (key === "quartile")
        return {
          icon: <QuartileGlyph />,
          tint: value === "Q1" ? TINTS.brand : TINTS.slate,
        };
      return { icon: null, tint: TINTS.brand };
  }
}

/** How each facet group behaves; shown as hover text on the group header. */
const GROUP_HINTS: Record<string, string> = {
  oa: "Is the journal open access as a whole (any OA type)? One choice; click it again to clear.",
  oa_type: "How the journal makes content open access. You can combine several types; click a selected type to remove it.",
  doaj: "Is the journal listed in DOAJ, the quality-controlled open access directory? One choice; click it again to clear.",
  quartile: "SCImago impact quartile of the journal in its subject category. One choice; click it again to clear.",
  has_apc: "Is any APC known for this journal — a list price (OpenAlex) or costs reported to OpenAPC? One choice; click it again to clear.",
  topic: "OpenAlex topic of the journal's works. One choice; click it again to clear.",
  publisher: "The journal's publisher. One choice; click it again to clear.",
};

/** Definitions per facet option, shown as hover text on the control. */
const FACET_TITLES: Record<string, string> = {
  "oa:true": "The journal is fully or partly open access.",
  "oa:false": "Subscription journal with no open access.",
  "oa_type:gold": "Every article is published open access on the journal's own site.",
  "oa_type:diamond": "Fully open access journal without fees for readers or authors.",
  "oa_type:hybrid": "Subscription journal where individual articles can be made open access.",
  "oa_type:subscription": "No open access; reading the published version requires a subscription.",
  "doaj:true": "Listed in DOAJ, the Directory of Open Access Journals, a quality-controlled registry for open access journals.",
  "doaj:false": "Not listed in DOAJ; hybrid and subscription journals usually are not.",
  "quartile:Q1": "Top 25% of its SCImago subject category by citation metrics.",
  "quartile:Q2": "Second quarter (25-50%) of its SCImago subject category.",
  "quartile:Q3": "Third quarter (50-75%) of its SCImago subject category.",
  "quartile:Q4": "Last quarter (75%) of its SCImago subject category by citation metrics.",
  "has_apc:true": "APCs are known for this journal: a list price (OpenAlex) or costs reported to OpenAPC.",
  "has_apc:false": "No APC is known for this journal from either source.",
};

/** Hints that name the institution or window, resolved per render. */
function groupHint(key: string, name: string, windowStart: number) {
  if (key === "deal")
    return `Does a ${name} open access deal cover APCs in this journal? One choice; click it again to clear.`;
  if (key === "has_works")
    return `Has ${name} published in this journal (${windowStart} onwards)? One choice; click it again to clear.`;
  return GROUP_HINTS[key];
}

function facetTitle(
  key: string,
  value: string,
  name: string,
  short: string,
  windowStart: number,
) {
  const k = `${key}:${value}`;
  if (k === "deal:covered")
    return `APCs for corresponding ${short} authors are covered, fully or partly, by a deal.`;
  if (k === "has_works:true")
    return `${name} has at least one publication in this journal since ${windowStart}.`;
  if (k === "has_works:false")
    return `No known ${name} publications in this journal since ${windowStart}.`;
  return FACET_TITLES[k];
}

function FacetGroup({
  group,
  onToggle,
  variant,
}: {
  group: FacetGroupDef;
  onToggle: (key: string, value: string) => void;
  variant: "chips" | "rows";
}) {
  const site = useSiteMeta();
  const { key, label, values, activeValues, defaultOpen } = group;
  const chips = variant === "chips";
  const focus =
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2";
  // One look for both variants: a squared control (not the old pill) that
  // turns into the value's own hue when selected. Chips lay out inline,
  // rows span the sidebar with the count on the right.
  const layout = chips
    ? "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs"
    : "flex w-full items-center justify-between gap-3 rounded-lg px-2.5 py-1.5 text-xs";
  const idleClasses = `${layout} border border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)] hover:border-[var(--primary)] hover:text-[var(--foreground)] ${focus}`;
  const zeroClasses = `${layout} cursor-not-allowed border border-transparent opacity-60`;

  return (
    // open never changes value, so React leaves the native toggle alone.
    <details open={defaultOpen} className="group" role="group" aria-label={`Filter by ${label}`}>
      <summary
        title={groupHint(key, site.name, site.windowStart)}
        className={`${focus} flex cursor-pointer select-none list-none items-center justify-between gap-2 rounded py-1.5 text-xs font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)] [&::-webkit-details-marker]:hidden`}
      >
        <span>{label}</span>
        <span className="flex items-center gap-1.5">
          <span className="tabular-nums">
            {activeValues.length > 0
              ? `${activeValues.length}/${values.length}`
              : values.length}
          </span>
          <ChevronDown
            aria-hidden
            className="size-3.5 shrink-0 transition-transform group-open:rotate-180"
          />
        </span>
      </summary>
      <div
        className={
          chips
            ? "mt-2 flex flex-wrap items-center gap-1.5"
            : "mt-1.5 flex flex-col gap-1"
        }
      >
        {values.map((f) => {
          const active = activeValues.includes(f.value);
          // Facets with zero results must not invite a click that empties the
          // list, so they render inert.
          const zero = !active && f.count === 0;
          const look = facetLook(key, f.value);
          const className = active
            ? `${layout} ${look.tint} border font-medium ${focus}`
            : zero
              ? zeroClasses
              : idleClasses;
          const iconNode = look.icon ? (
            // The glyphs are bare SVG shapes; they need an svg context here
            // (inside badges they live inside the lockup's own svg).
            <svg
              aria-hidden
              viewBox="0 0 16 16"
              className={`h-4 w-auto shrink-0 overflow-visible ${
                active ? "" : FACET_ICON_TEXT[`${key}:${f.value}`] ?? ""
              }`}
            >
              {look.icon}
            </svg>
          ) : null;
          const labelText = f.label ?? f.value;
          const countNode =
            f.count !== undefined ? (
              <span
                className={`shrink-0 tabular-nums ${
                  chips ? "ml-0.5 opacity-80" : ""
                }`}
              >
                {f.count.toLocaleString("en")}
              </span>
            ) : null;
          const inner = chips ? (
            <>
              {iconNode}
              <span className="max-w-[14rem] truncate">{labelText}</span>
              {countNode}
            </>
          ) : (
            <>
              <span className="flex min-w-0 items-center gap-1.5">
                {iconNode}
                <span className="truncate">{labelText}</span>
              </span>
              {countNode}
            </>
          );
          const optionTitle =
            facetTitle(key, f.value, site.name, site.short, site.windowStart) ??
            (f.value.length > 24 ? f.value : undefined);
          return zero ? (
            <span key={f.value} aria-disabled="true" title={optionTitle} className={className}>
              {inner}
            </span>
          ) : (
            <button
              key={f.value}
              type="button"
              onClick={() => onToggle(key, f.value)}
              aria-pressed={active}
              title={optionTitle}
              className={className}
            >
              {inner}
            </button>
          );
        })}
      </div>
    </details>
  );
}

/**
 * Facet groups shared by the stacked filter card (chips) and the wide-screen
 * sidebar (rows). Single-select per group: the caller clears on re-click.
 */
export function FilterPanel({
  facets,
  selection,
  onToggle,
  variant,
}: {
  facets: FacetsData;
  selection: FilterSelection;
  onToggle: (key: string, value: string) => void;
  variant: "chips" | "rows";
}) {
  const site = useSiteMeta();
  const topicValues = topValues(facets.topic, selection.topic);
  const publisherValues = topValues(facets.publisher, selection.publisher);

  const groups: FacetGroupDef[] = [
    {
      key: "deal",
      label: "Deal",
      defaultOpen: true,
      values: Object.entries(facets.deal_coverage ?? {}).map(
        ([value, count]) => ({
          value,
          count,
          label: value === "covered" ? "Covered by a deal" : "No deal",
        }),
      ),
      activeValues: selection.deal ? [selection.deal] : [],
    },
    {
      key: "oa",
      label: "Open access",
      defaultOpen: true,
      values: Object.entries(facets.oa ?? {}).map(([value, count]) => ({
        value,
        count,
        label: value === "true" ? "OA journal" : "Not OA",
      })),
      activeValues: selection.oa !== null ? [selection.oa] : [],
    },
    {
      key: "oa_type",
      label: "OA type",
      defaultOpen: true,
      values: ["gold", "diamond", "hybrid", "subscription"].map((v) => ({
        value: v,
        count: facets.oa_type?.[v] ?? 0,
        label: OA_TYPE_LABELS[v] ?? v,
      })),
      // Multi-select: this group ORs its values; the caller keeps every
      // active value instead of clearing the group on re-click.
      activeValues: selection.oaTypes,
    },
    {
      key: "doaj",
      label: "DOAJ",
      defaultOpen: true,
      values: Object.entries(facets.doaj ?? {}).map(([value, count]) => ({
        value,
        count,
        label: value === "true" ? "In DOAJ" : "Not in DOAJ",
      })),
      activeValues: selection.doaj !== null ? [selection.doaj] : [],
    },
    {
      key: "quartile",
      label: "Quartile",
      defaultOpen: true,
      values: ["Q1", "Q2", "Q3", "Q4"].map((q) => ({
        value: q,
        count: facets.quartile?.[q] ?? 0,
      })),
      activeValues: selection.quartile ? [selection.quartile] : [],
    },
    {
      key: "has_apc",
      label: "APC",
      defaultOpen: true,
      values: Object.entries(facets.apc ?? {}).map(([value, count]) => ({
        value,
        count,
        label: value === "true" ? "APC data known" : "No APC data",
      })),
      activeValues: selection.hasApc !== null ? [selection.hasApc] : [],
    },
    {
      key: "has_works",
      label: `${site.short} works`,
      defaultOpen: true,
      values: Object.entries(facets.works ?? {}).map(([value, count]) => ({
        value,
        count,
        label: value === "true" ? `Has ${site.short} works` : `No ${site.short} works`,
      })),
      activeValues: selection.hasWorks !== null ? [selection.hasWorks] : [],
    },
    ...(topicValues.length > 0
      ? [
          {
            key: "topic",
            label: "Topic",
            defaultOpen: false,
            values: topicValues,
            activeValues: selection.topic ? [selection.topic] : [],
          },
        ]
      : []),
    ...(publisherValues.length > 0
      ? [
          {
            key: "publisher",
            label: "Publisher",
            defaultOpen: false,
            values: publisherValues,
            activeValues: selection.publisher ? [selection.publisher] : [],
          },
        ]
      : []),
  ];

  return (
    <div className="space-y-2.5">
      {groups.map((group) => (
        <FacetGroup
          key={group.key}
          group={group}
          onToggle={onToggle}
          variant={variant}
        />
      ))}
    </div>
  );
}
