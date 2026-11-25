"use client";

import { Check, ChevronDown } from "lucide-react";
import * as React from "react";
import { useTranslations } from "next-intl";

import {
  ACCESS_TEXT,
  ApcGlyph,
  DealGlyph,
  DoajGlyph,
  LockIcon,
  NoDealGlyph,
  QuartileGlyph,
  WorksGlyph,
} from "@/components/data-icons";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { PUB_TYPE_LABELS } from "@/lib/search-config";

/** Minimal shape of next-intl's `t` used by the facet helpers. */
type Translator = (key: string, values?: Record<string, string | number>) => string;

const OA_TYPE_LABEL_KEYS: Record<string, string> = {
  gold: "facets.oaTypeGold",
  diamond: "facets.oaTypeDiamond",
  generic: "facets.oaTypeGeneric",
  hybrid: "facets.oaTypeHybrid",
  subscription: "facets.oaTypeSubscription",
};

const GREEN_OA_LABEL_KEYS: Record<string, string> = {
  submitted: "facets.greenOaSubmitted",
  accepted: "facets.greenOaAccepted",
  published: "facets.greenOaPublished",
  none: "facets.greenOaNone",
};

export type FacetValue = { value: string; count?: number; label?: string };

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
  greenOa: string | null;
  /** Funder-fit tier; only selectable when a funder is picked. */
  funderFit: string;
  /** Multi-select: values OR together (single-select groups do not). */
  oaTypes: string[];
  /** OpenAlex venue type ("journal", "book series", ...). */
  pubType: string;
  /** Modal journal language (ISO 639-1 code). */
  language: string;
};

export type FacetGroupDef = {
  key: string;
  label: string;
  values: FacetValue[];
  activeValues: string[];
  defaultOpen: boolean;
  searchable?: boolean;
  initialVisible?: number;
};

/** Top N by count, with the active value kept visible even outside the top N. */
function topValues(
  counts: Record<string, number> | undefined,
  active: string,
  limit = 8,
): FacetValue[] {
  const values: FacetValue[] = Object.entries(counts ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([value, count]) => ({ value, count }));
  if (active && !values.some((t) => t.value === active)) values.unshift({ value: active });
  return values;
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
  slate:
    "border-slate-300 bg-slate-100 text-slate-700 dark:border-slate-500/40 dark:bg-slate-500/15 dark:text-slate-200",
  teal: "border-teal-300 bg-teal-100 text-teal-900 dark:border-teal-400/40 dark:bg-teal-400/15 dark:text-teal-200",
  brand: "border-(--brand-tint-border) bg-(--brand-tint-bg) text-(--primary-text)",
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
function facetLook(key: string, value: string): { icon: React.ReactNode; tint: string } {
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
    case "oa_type:generic":
      return { icon: <LockIcon state="ajar" />, tint: TINTS.slate };
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
    case "green_oa:none":
      return { icon: null, tint: TINTS.slate };
    default:
      if (key === "deal") return { icon: <NoDealGlyph />, tint: TINTS.slate };
      if (key === "quartile")
        return {
          icon: <QuartileGlyph />,
          tint: value === "Q1" ? TINTS.brand : TINTS.slate,
        };
      return { icon: null, tint: TINTS.brand };
  }
}

const GROUP_HINT_KEYS: Record<string, string> = {
  pub_type: "facets.hintVenueType",
  oa: "facets.hintOpenAccess",
  oa_type: "facets.hintOaType",
  doaj: "facets.hintDoaj",
  quartile: "facets.hintQuartile",
  has_apc: "facets.hintApc",
  green_oa: "facets.hintGreenOa",
  topic: "facets.hintTopic",
  publisher: "facets.hintPublisher",
};

function groupHint(
  t: Translator,
  key: string,
  name: string,
  windowStart: number | undefined,
): string | undefined {
  if (key === "deal") return t("facets.hintDeal", { name });
  if (key === "has_works") {
    return windowStart === undefined
      ? t("facets.hintInstWorks", { name })
      : t("facets.hintInstWorksSince", { name, windowStart: String(windowStart) });
  }
  const hintKey = GROUP_HINT_KEYS[key];
  return hintKey ? t(hintKey) : undefined;
}

const FACET_TITLE_KEYS: Record<string, string> = {
  "pub_type:journal": "facets.titleVenueTypeJournal",
  "pub_type:book series": "facets.titleVenueTypeBookSeries",
  "pub_type:conference": "facets.titleVenueTypeConference",
  "pub_type:ebook platform": "facets.titleVenueTypeEbookPlatform",
  "pub_type:repository": "facets.titleVenueTypeRepository",
  "oa:true": "facets.titleOaYes",
  "oa:false": "facets.titleOaNo",
  "oa_type:gold": "facets.titleOaTypeGold",
  "oa_type:diamond": "facets.titleOaTypeDiamond",
  "oa_type:hybrid": "facets.titleOaTypeHybrid",
  "oa_type:generic": "facets.titleOaTypeGeneric",
  "oa_type:subscription": "facets.titleOaTypeSubscription",
  "doaj:true": "facets.titleDoajYes",
  "doaj:false": "facets.titleDoajNo",
  "quartile:Q1": "facets.titleQuartileQ1",
  "quartile:Q2": "facets.titleQuartileQ2",
  "quartile:Q3": "facets.titleQuartileQ3",
  "quartile:Q4": "facets.titleQuartileQ4",
  "has_apc:true": "facets.titleApcKnown",
  "has_apc:false": "facets.titleApcUnknown",
  "green_oa:submitted": "facets.titleGreenOaSubmitted",
  "green_oa:accepted": "facets.titleGreenOaAccepted",
  "green_oa:published": "facets.titleGreenOaPublished",
  "green_oa:none": "facets.titleGreenOaNone",
};

function facetTitle(
  t: Translator,
  key: string,
  value: string,
  name: string,
  short: string,
  windowStart: number | undefined,
): string | undefined {
  const k = `${key}:${value}`;
  if (k === "deal:covered") return t("facets.titleDealCovered", { short });
  if (k === "has_works:true") {
    return windowStart === undefined
      ? t("facets.titleInstWorksYes", { name })
      : t("facets.titleInstWorksYesSince", { name, windowStart: String(windowStart) });
  }
  if (k === "has_works:false") {
    return windowStart === undefined
      ? t("facets.titleInstWorksNo", { name })
      : t("facets.titleInstWorksNoSince", { name, windowStart: String(windowStart) });
  }
  const titleKey = FACET_TITLE_KEYS[k];
  return titleKey ? t(titleKey) : undefined;
}

function FacetGroup({
  group,
  onToggle,
  loading,
}: {
  group: FacetGroupDef;
  onToggle: (key: string, value: string) => void;
  /** Facets request in flight or failed: every option renders inert. */
  loading?: boolean;
}) {
  const site = useSiteMeta();
  const t = useTranslations("common");
  const { key, label, values, activeValues, defaultOpen, searchable, initialVisible } = group;
  const [filter, setFilter] = React.useState("");
  const [expanded, setExpanded] = React.useState(false);
  const initialLimit = initialVisible ?? 8;
  const needle = filter.trim().toLowerCase();
  const filteredValues = needle
    ? values.filter(
        (v) =>
          (v.label ?? v.value).toLowerCase().includes(needle) ||
          v.value.toLowerCase().includes(needle),
      )
    : values;
  const visibleValues =
    needle || expanded || filteredValues.length <= initialLimit
      ? filteredValues
      : [
          ...filteredValues.filter((v) => activeValues.includes(v.value)),
          ...filteredValues
            .filter((v) => !activeValues.includes(v.value))
            .slice(0, Math.max(0, initialLimit - activeValues.length)),
        ];
  const hiddenCount = filteredValues.length - visibleValues.length;
  const focus =
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2";
  // A squared control (not the old pill) that turns into the value's own hue
  // when selected: a full-width row with the count on the right. Rows are
  // 44px targets in the phone sheet and compact in the sidebar.
  const layout =
    "flex min-h-11 w-full items-center justify-between gap-3 rounded-lg px-2.5 py-2 text-sm min-[960px]:min-h-0 min-[960px]:py-1.5 min-[960px]:text-xs";
  const idleClasses = `${layout} border border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)] hover:border-[var(--primary)] hover:text-[var(--foreground)] ${focus}`;
  const zeroClasses = `${layout} cursor-not-allowed border border-transparent opacity-60`;

  // The group's own number is an option count, not a journal count; it only
  // shows while options are selected (n/N), and the total lives in the hover
  // text where it cannot be misread as data.
  const hintParts = [groupHint(t, key, site.name, site.windowStart)];
  if (!loading && values.length > 0)
    hintParts.push(t("facets.optionCountTitle", { count: values.length }));
  const summaryTitle = hintParts.filter(Boolean).join(" · ") || undefined;

  return (
    // open never changes value, so React leaves the native toggle alone.
    <details
      open={defaultOpen}
      className="group"
      role="group"
      aria-label={t("facets.filterBy", { label })}
    >
      <summary
        title={summaryTitle}
        className={`${focus} flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 rounded py-2 text-sm font-semibold text-[var(--foreground)] hover:text-[var(--primary-text)] [&::-webkit-details-marker]:hidden min-[960px]:min-h-0 min-[960px]:py-1 min-[960px]:text-xs`}
      >
        <span>{label}</span>
        <span className="flex items-center gap-1.5">
          {activeValues.length > 0 && (
            <span className="rounded-full bg-[var(--brand-tint-bg)] px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-[var(--primary-text)]">
              {activeValues.length}
            </span>
          )}
          <ChevronDown
            aria-hidden
            className="size-3.5 shrink-0 text-[var(--muted-foreground)] transition-transform group-open:rotate-180"
          />
        </span>
      </summary>
      <div className="mt-2 space-y-1.5">
        {searchable && values.length > initialLimit && (
          <input
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t("facets.filterPlaceholder", { label: label.toLowerCase() })}
            className="w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-xs text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
          />
        )}
        <div className="flex flex-col gap-1">
          {visibleValues.map((f) => {
            const active = activeValues.includes(f.value);
            // Facets with zero results must not invite a click that empties the
            // list, so they render inert.
            const zero = !active && f.count === 0;
            const look = facetLook(key, f.value);
            const className = `jb-chip-row ${
              active
                ? `${layout} ${look.tint} border font-medium ${focus}`
                : zero
                  ? zeroClasses
                  : idleClasses
            }`;
            const iconNode = look.icon ? (
              // The glyphs are bare SVG shapes; they need an svg context here
              // (inside badges they live inside the lockup's own svg).
              <svg
                aria-hidden
                viewBox="0 0 16 16"
                className={`h-4 w-auto shrink-0 overflow-visible ${
                  active ? "" : (FACET_ICON_TEXT[`${key}:${f.value}`] ?? "")
                }`}
              >
                {look.icon}
              </svg>
            ) : (
              <span
                aria-hidden
                className={`inline-flex size-3.5 shrink-0 items-center justify-center rounded-[3px] border ${
                  active
                    ? "border-current bg-current/15"
                    : "border-[var(--border)] bg-[var(--background)]"
                }`}
              >
                {active && <Check className="size-2.5 stroke-[2.5]" />}
              </span>
            );
            const labelText = f.label ?? f.value;
            // An unknown count is never a zero: render the em dash so a slow
            // facets request or an uncounted active value cannot read as
            // "no journals".
            const countNode =
              f.count === undefined ? (
                <span className="shrink-0 tabular-nums opacity-70" title={t("facets.countPending")}>
                  —
                </span>
              ) : (
                <span className="shrink-0 tabular-nums">{f.count.toLocaleString("en")}</span>
              );
            const inner = (
              <>
                <span className="flex min-w-0 items-center gap-1.5">
                  {iconNode}
                  <span className="truncate">{labelText}</span>
                </span>
                {countNode}
              </>
            );
            const optionTitle =
              facetTitle(t, key, f.value, site.name, site.short, site.windowStart) ??
              (f.value.length > 24 ? f.value : undefined);
            return zero ? (
              <span key={f.value} aria-disabled="true" title={optionTitle} className={className}>
                {inner}
              </span>
            ) : (
              <button
                key={f.value}
                type="button"
                disabled={loading}
                aria-disabled={loading || undefined}
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
        {!needle && (hiddenCount > 0 || (expanded && filteredValues.length > initialLimit)) && (
          <button
            type="button"
            onClick={() => setExpanded((prev) => !prev)}
            className="inline-flex min-h-11 items-center rounded-[var(--radius)] px-2 text-sm font-medium text-[var(--primary-text)] underline-offset-2 hover:underline min-[960px]:min-h-0 min-[960px]:px-0 min-[960px]:text-xs"
          >
            {expanded ? t("facets.showLess") : t("facets.showMore", { count: hiddenCount })}
          </button>
        )}
      </div>
    </details>
  );
}

/** A group is worth showing when it has an active selection, or when two or
 * more of its options have a non-zero count: fewer cannot narrow anything. */
function groupIsVisible(group: FacetGroupDef): boolean {
  return group.activeValues.length > 0 || group.values.filter((v) => (v.count ?? 0) > 0).length > 1;
}

/**
 * True when at least one facet group can render usefully. Pages use it to
 * drop the whole filter card when every group fails the test (e.g. all
 * options but one sit at zero), instead of showing an empty card.
 */
export function hasVisibleGroups(groups: FacetGroupDef[], loading?: boolean): boolean {
  return loading || groups.some(groupIsVisible);
}

/** Render caller-built facet groups; FilterPanel supplies the journal's own. */
export function FacetGroupList({
  groups,
  onToggle,
  loading,
}: {
  groups: FacetGroupDef[];
  onToggle: (key: string, value: string) => void;
  loading?: boolean;
}) {
  // Groups that cannot discriminate (fewer than two non-zero options) only
  // add noise; hide them until the data distinguishes two options. A group
  // with an active selection stays visible so the selection can be cleared.
  const visibleGroups = loading ? groups : groups.filter(groupIsVisible);
  return (
    <div
      className="divide-y divide-[var(--border)] [&>*:not(:first-child)]:pt-3 [&>*:not(:last-child)]:pb-3"
      aria-busy={loading || undefined}
    >
      {visibleGroups.map((group) => (
        <FacetGroup key={group.key} group={group} onToggle={onToggle} loading={loading} />
      ))}
    </div>
  );
}

/**
 * Eligibility toggles for the journal browse: both default on server-side,
 * so a toggle only writes state when switched off. Clicking clears the
 * toggle (back to the default).
 */
export function QualityToggles({
  active,
  vouched,
  onToggle,
}: {
  active: boolean;
  vouched: boolean;
  onToggle: (key: "active" | "vouched") => void;
}) {
  const t = useTranslations("common");
  const year = new Date().getFullYear() - 1;
  const focus =
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2";
  const items = [
    {
      key: "active" as const,
      on: active,
      label: t("facets.qualityActive", { year: String(year) }),
    },
    { key: "vouched" as const, on: vouched, label: t("facets.qualityVouched") },
  ];
  return (
    <div className="space-y-1.5" role="group" aria-label={t("facets.qualityGroup")}>
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          onClick={() => onToggle(item.key)}
          aria-pressed={item.on}
          title={item.label}
          className={`flex w-full items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs ${focus} ${
            item.on
              ? "border border-[var(--border)] font-medium text-[var(--foreground)]"
              : "border border-dashed border-[var(--border)] text-[var(--muted-foreground)] hover:border-[var(--primary)] hover:text-[var(--foreground)]"
          }`}
        >
          <span
            aria-hidden
            className={`inline-flex size-3.5 shrink-0 items-center justify-center rounded-[3px] border ${
              item.on
                ? "border-current bg-current/15"
                : "border-[var(--border)] bg-[var(--background)]"
            }`}
          >
            {item.on && <Check className="size-2.5 stroke-[2.5]" />}
          </span>
          <span className="min-w-0 flex-1 text-left leading-snug">{item.label}</span>
        </button>
      ))}
    </div>
  );
}

/**
 * The journal browse facets, as full-width rows. Single-select per group: the
 * caller clears on re-click.
 */
export function FilterPanel({
  facets,
  selection,
  onToggle,
  error,
  onRetry,
}: {
  /** Undefined while the facets request is in flight: groups render with
   * their known options and em-dash counts, all inert. */
  facets: FacetsData | undefined;
  selection: FilterSelection;
  onToggle: (key: string, value: string) => void;
  /** The facets request failed; a retry note renders above the groups. */
  error?: boolean;
  onRetry?: () => void;
}) {
  const site = useSiteMeta();
  const t = useTranslations("common");
  const ts = useTranslations("search");
  const loading = facets === undefined;
  const topicValues = topValues(facets?.topic, selection.topic, 30);
  const publisherValues = topValues(facets?.publisher, selection.publisher, 30);

  // Options with a fixed value list render even before the facets request
  // returns, so the panel keeps its shape and shows — instead of 0.
  const boolSeed = (): FacetValue[] => ["true", "false"].map((value) => ({ value }));

  const groups: FacetGroupDef[] = [
    {
      key: "pub_type",
      label: t("facets.groupVenueType"),
      defaultOpen: true,
      values: loading
        ? Object.keys(PUB_TYPE_LABELS).map((value) => ({
            value,
            label: ts(PUB_TYPE_LABELS[value]),
          }))
        : topValues(facets?.pub_type, selection.pubType).map((v) => ({
            ...v,
            label: PUB_TYPE_LABELS[v.value] ? ts(PUB_TYPE_LABELS[v.value]) : v.value,
          })),
      activeValues: selection.pubType ? [selection.pubType] : [],
    },
    {
      key: "deal",
      label: t("facets.groupDeal"),
      defaultOpen: true,
      values: loading
        ? ["covered", "not_covered"].map((value) => ({
            value,
            label: value === "covered" ? t("facets.dealCovered") : t("facets.dealNone"),
          }))
        : Object.entries(facets?.deal_coverage ?? {}).map(([value, count]) => ({
            value,
            count,
            label: value === "covered" ? t("facets.dealCovered") : t("facets.dealNone"),
          })),
      activeValues: selection.deal ? [selection.deal] : [],
    },
    {
      key: "oa",
      label: t("facets.groupOpenAccess"),
      defaultOpen: true,
      values: loading
        ? boolSeed().map((v) => ({
            ...v,
            label: v.value === "true" ? t("facets.oaYes") : t("facets.oaNo"),
          }))
        : Object.entries(facets?.oa ?? {}).map(([value, count]) => ({
            value,
            count,
            label: value === "true" ? t("facets.oaYes") : t("facets.oaNo"),
          })),
      activeValues: selection.oa !== null ? [selection.oa] : [],
    },
    {
      key: "oa_type",
      label: t("facets.groupOaType"),
      defaultOpen: true,
      values: ["diamond", "gold", "hybrid", "generic", "subscription"].map((v) => ({
        value: v,
        count: facets?.oa_type?.[v],
        label: OA_TYPE_LABEL_KEYS[v] ? t(OA_TYPE_LABEL_KEYS[v]) : v,
      })),
      // Multi-select: this group ORs values; the caller keeps every
      // active value instead of clearing the group on re-click.
      activeValues: selection.oaTypes,
    },
    {
      key: "language",
      label: t("facets.groupLanguage"),
      defaultOpen: true,
      searchable: true,
      initialVisible: 8,
      values: topValues(facets?.language, selection.language, 30).map((v) => ({
        ...v,
        label: ts.has(`languages.${v.value}`) ? ts(`languages.${v.value}`) : v.value,
      })),
      activeValues: selection.language ? [selection.language] : [],
    },
    {
      key: "doaj",
      label: t("facets.groupDoaj"),
      defaultOpen: true,
      values: loading
        ? boolSeed().map((v) => ({
            ...v,
            label: v.value === "true" ? t("facets.doajYes") : t("facets.doajNo"),
          }))
        : Object.entries(facets?.doaj ?? {}).map(([value, count]) => ({
            value,
            count,
            label: value === "true" ? t("facets.doajYes") : t("facets.doajNo"),
          })),
      activeValues: selection.doaj !== null ? [selection.doaj] : [],
    },
    {
      key: "has_apc",
      label: t("facets.groupApc"),
      defaultOpen: true,
      values: loading
        ? boolSeed().map((v) => ({
            ...v,
            label: v.value === "true" ? t("facets.apcKnown") : t("facets.apcUnknown"),
          }))
        : Object.entries(facets?.apc ?? {}).map(([value, count]) => ({
            value,
            count,
            label: value === "true" ? t("facets.apcKnown") : t("facets.apcUnknown"),
          })),
      activeValues: selection.hasApc !== null ? [selection.hasApc] : [],
    },
    {
      key: "green_oa",
      label: t("facets.groupGreenOa"),
      defaultOpen: true,
      values: ["submitted", "accepted", "published", "none"].map((v) => ({
        value: v,
        count: facets?.green_oa?.[v],
        label: GREEN_OA_LABEL_KEYS[v] ? t(GREEN_OA_LABEL_KEYS[v]) : v,
      })),
      activeValues: selection.greenOa ? [selection.greenOa] : [],
    },
    {
      key: "has_works",
      label: t("facets.groupInstWorks", { short: site.short }),
      defaultOpen: true,
      values: loading
        ? boolSeed().map((v) => ({
            ...v,
            label:
              v.value === "true"
                ? t("facets.instWorksYes", { short: site.short })
                : t("facets.instWorksNo", { short: site.short }),
          }))
        : Object.entries(facets?.works ?? {}).map(([value, count]) => ({
            value,
            count,
            label:
              value === "true"
                ? t("facets.instWorksYes", { short: site.short })
                : t("facets.instWorksNo", { short: site.short }),
          })),
      activeValues: selection.hasWorks !== null ? [selection.hasWorks] : [],
    },
    // Only rendered when a funder is selected and its policy is structured
    // (the backend omits the facet otherwise).
    ...(facets?.funder_fit
      ? [
          {
            key: "funder_fit",
            label: t("facets.groupFunderFit"),
            defaultOpen: true,
            values: ["compliant", "check", "no"].map((v) => ({
              value: v,
              count: facets.funder_fit?.[v],
              label:
                v === "compliant"
                  ? t("facets.funderFitCompliant")
                  : v === "check"
                    ? t("facets.funderFitCheck")
                    : t("facets.funderFitNo"),
            })),
            activeValues: selection.funderFit ? [selection.funderFit] : [],
          },
        ]
      : []),
    ...(topicValues.length > 0
      ? [
          {
            key: "topic",
            label: t("facets.groupTopic"),
            defaultOpen: false,
            searchable: true,
            initialVisible: 8,
            values: topicValues,
            activeValues: selection.topic ? [selection.topic] : [],
          },
        ]
      : []),
    ...(publisherValues.length > 0
      ? [
          {
            key: "publisher",
            label: t("facets.groupPublisher"),
            defaultOpen: false,
            searchable: true,
            initialVisible: 8,
            values: publisherValues,
            activeValues: selection.publisher ? [selection.publisher] : [],
          },
        ]
      : []),
    // Quartile sits last: it is the least decision-relevant facet and the
    // list reads better with it at the bottom of the panel.
    {
      key: "quartile",
      label: t("facets.groupQuartile"),
      defaultOpen: true,
      values: ["Q1", "Q2", "Q3", "Q4"].map((q) => ({
        value: q,
        count: facets?.quartile?.[q],
      })),
      activeValues: selection.quartile ? [selection.quartile] : [],
    },
  ];

  return (
    <div className="space-y-3">
      {error && (
        <div
          role="status"
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--border)] bg-[var(--muted)] px-3 py-2 text-xs text-[var(--muted-foreground)]"
        >
          <span>{t("facets.loadError")}</span>
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="rounded font-medium text-[var(--primary-text)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2"
            >
              {t("facets.retry")}
            </button>
          )}
        </div>
      )}
      <FacetGroupList groups={groups} onToggle={onToggle} loading={loading} />
    </div>
  );
}
