import { ChevronDown } from "lucide-react";

export type FacetValue = { value: string; count?: number; label?: string };

export type FacetsData = Record<string, Record<string, number>>;

export type FilterSelection = {
  deal: string;
  oa: string | null;
  doaj: string | null;
  quartile: string;
  topic: string;
  publisher: string;
  hasApc: string | null;
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

function FacetGroup({
  group,
  onToggle,
  variant,
}: {
  group: FacetGroupDef;
  onToggle: (key: string, value: string) => void;
  variant: "chips" | "rows";
}) {
  const { key, label, values, activeValues, defaultOpen } = group;
  const chips = variant === "chips";
  const focus =
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2";
  // Chips match the historical inline look; rows are the sidebar's
  // Scopus-style full-width options (label left, count right).
  const styles = chips
    ? {
        active: `rounded-full bg-[var(--primary)] px-3 py-1 text-xs font-medium text-[var(--primary-foreground)] ${focus}`,
        idle: `rounded-full border border-[var(--border)] bg-[var(--card)] px-3 py-1 text-xs text-[var(--muted-foreground)] hover:border-[var(--primary)] hover:text-[var(--foreground)] ${focus}`,
        zero:
          "cursor-not-allowed rounded-full border border-[var(--border)] bg-[var(--muted)] px-3 py-1 text-xs text-[var(--muted-foreground)] opacity-60",
      }
    : {
        active: `flex w-full items-center justify-between gap-3 rounded-md bg-[var(--primary)] px-2.5 py-1.5 text-xs font-medium text-[var(--primary-foreground)] ${focus}`,
        idle: `flex w-full items-center justify-between gap-3 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-xs text-[var(--muted-foreground)] hover:border-[var(--primary)] hover:text-[var(--foreground)] ${focus}`,
        zero:
          "flex w-full cursor-not-allowed items-center justify-between gap-3 rounded-md px-2.5 py-1.5 text-xs text-[var(--muted-foreground)] opacity-60",
      };

  return (
    // open never changes value, so React leaves the native toggle alone.
    <details open={defaultOpen} className="group" role="group" aria-label={`Filter by ${label}`}>
      <summary
        className={`${focus} flex cursor-pointer select-none list-none items-center justify-between gap-2 rounded text-xs font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)] [&::-webkit-details-marker]:hidden`}
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
          const className = active
            ? styles.active
            : zero
              ? styles.zero
              : styles.idle;
          const labelNode = chips ? (
            (f.label ?? (
              <span className="inline-block max-w-[14rem] truncate align-middle">
                {f.value}
              </span>
            ))
          ) : (
            <span className="min-w-0 truncate">{f.label ?? f.value}</span>
          );
          const countNode =
            f.count !== undefined ? (
              <span
                className={chips ? "ml-1 tabular-nums" : "shrink-0 tabular-nums"}
              >
                {f.count.toLocaleString("en")}
              </span>
            ) : null;
          return zero ? (
            <span key={f.value} aria-disabled="true" className={className}>
              {labelNode}
              {countNode}
            </span>
          ) : (
            <button
              key={f.value}
              type="button"
              onClick={() => onToggle(key, f.value)}
              aria-pressed={active}
              title={f.value.length > 24 ? f.value : undefined}
              className={className}
            >
              {labelNode}
              {countNode}
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
          label: value === "covered" ? "Deal coverage" : "No deal",
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
