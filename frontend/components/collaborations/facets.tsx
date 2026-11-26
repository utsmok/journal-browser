"use client";

import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";

import { orgTypeCssVar, useCollabLabels } from "@/components/collaborations/labels";
import { type UpdateParams } from "@/components/collaborations/collab-params";
import {
  type CollabMultiKey,
  type CollaborationFacets,
  type CollaborationLevel,
  type CollaborationSearchParams,
} from "@/lib/api";

function toggleValue(current: string[] | undefined, value: string): string[] {
  const next = new Set(current ?? []);
  if (!next.delete(value)) next.add(value);
  return [...next];
}

const LEVELS: readonly CollaborationLevel[] = ["faculty", "group", "institute"];
const INITIAL_VISIBLE = 10;

const selectClass =
  "rounded-[var(--radius)] border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-xs text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]";

type Option = {
  value: string;
  label: string;
  sublabel?: string;
  count: number;
  swatch?: string;
};

type GroupDef = {
  key: CollabMultiKey;
  label: string;
  defaultOpen: boolean;
  searchable?: boolean;
  headerExtra?: React.ReactNode;
  activeValues: string[];
  values: Option[];
};

function FacetSection({
  group,
  onToggle,
  variant,
  loading,
  updating,
}: {
  group: GroupDef;
  onToggle: (key: CollabMultiKey, value: string) => void;
  variant: "chips" | "rows";
  loading?: boolean;
  updating?: boolean;
}) {
  const t = useTranslations("collaborations");
  const [filter, setFilter] = React.useState("");
  const [expanded, setExpanded] = React.useState(false);

  const chips = variant === "chips";
  const needle = filter.trim().toLowerCase();
  const filtered = needle
    ? group.values.filter(
        (v) =>
          v.label.toLowerCase().includes(needle) ||
          (v.sublabel?.toLowerCase().includes(needle) ?? false) ||
          v.value.toLowerCase().includes(needle),
      )
    : group.values;

  // Keep active options visible even when collapsed to top N.
  const shown =
    needle || expanded || filtered.length <= INITIAL_VISIBLE
      ? filtered
      : [
          ...filtered.filter((v) => group.activeValues.includes(v.value)),
          ...filtered
            .filter((v) => !group.activeValues.includes(v.value))
            .slice(0, Math.max(0, INITIAL_VISIBLE - group.activeValues.length)),
        ];

  const hiddenCount = filtered.length - shown.length;
  const focus =
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2";
  const layout = chips
    ? "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs transition-[colors,transform] duration-100 active:scale-[0.99]"
    : "flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-xs transition-[colors,transform] duration-100 active:scale-[0.99]";

  return (
    <details open={group.defaultOpen} className="group" role="group" aria-label={group.label}>
      <summary
        className={`${focus} flex cursor-pointer select-none list-none items-center justify-between gap-2 rounded py-1.5 text-xs font-medium text-[var(--muted-foreground)] hover:text-[var(--foreground)] [&::-webkit-details-marker]:hidden`}
      >
        <span>{group.label}</span>
        <span className="flex items-center gap-1.5">
          {group.activeValues.length > 0 && (
            <span className="rounded bg-[var(--brand-tint-bg)] px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-[var(--primary-text)]">
              {group.activeValues.length}
            </span>
          )}
          <ChevronDown
            aria-hidden
            className="size-3.5 shrink-0 transition-transform group-open:rotate-180"
          />
        </span>
      </summary>

      <div className="mt-1.5 space-y-1.5">
        {group.headerExtra}
        {group.searchable && group.values.length > INITIAL_VISIBLE && (
          <input
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t("facets.filterPlaceholder", { label: group.label.toLowerCase() })}
            className="w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-xs text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
          />
        )}
        <div className={chips ? "flex flex-wrap items-center gap-1.5" : "flex flex-col gap-1"}>
          {shown.map((opt) => {
            const active = group.activeValues.includes(opt.value);
            const cls = active
              ? `${layout} border border-[var(--brand-tint-border)] bg-[var(--brand-tint-bg)] font-medium text-[var(--primary-text)] ${focus}`
              : `${layout} border border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)] hover:border-[var(--primary)] hover:text-[var(--foreground)] ${focus}`;
            return (
              <button
                key={opt.value}
                type="button"
                disabled={loading}
                aria-pressed={active}
                title={opt.sublabel ? `${opt.label} — ${opt.sublabel}` : opt.label}
                onClick={() => onToggle(group.key, opt.value)}
                className={cls}
              >
                <span className="flex min-w-0 items-center gap-1.5 text-left">
                  {opt.swatch && (
                    <span
                      aria-hidden
                      className="inline-block size-2.5 shrink-0 rounded-full"
                      style={{ backgroundColor: opt.swatch }}
                    />
                  )}
                  <span className="min-w-0">
                    <span className="block truncate">{opt.label}</span>
                    {!chips && opt.sublabel && (
                      <span className="block truncate text-[10px] opacity-75">{opt.sublabel}</span>
                    )}
                  </span>
                </span>
                <span
                  className={`shrink-0 tabular-nums transition-opacity duration-150 ${
                    updating ? "opacity-45" : "opacity-85"
                  }`}
                >
                  {opt.count.toLocaleString("en")}
                </span>
              </button>
            );
          })}
        </div>
        {!needle && (hiddenCount > 0 || (expanded && filtered.length > INITIAL_VISIBLE)) && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-xs font-medium text-[var(--primary-text)] underline-offset-2 hover:underline"
          >
            {expanded ? t("facets.showLess") : t("facets.showMore", { count: hiddenCount })}
          </button>
        )}
      </div>
    </details>
  );
}

/** Facet sidebar with inline search, colour swatches matching the map, and
 * the unit-level selector placed right inside the org-unit facet group. */
export function CollaborationFacets({
  params,
  facets,
  onChange,
  variant,
  loading,
  updating,
}: {
  params: CollaborationSearchParams;
  facets: CollaborationFacets | null | undefined;
  onChange: UpdateParams;
  variant: "chips" | "rows";
  loading?: boolean;
  updating?: boolean;
}) {
  const t = useTranslations("collaborations");
  const labels = useCollabLabels();
  const hasUnits = (facets?.orgunit.length ?? 0) > 0;
  const level = params.level ?? "faculty";

  const unitLevelPicker = (
    <div className="mb-1 flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
      <label htmlFor={`collab-level-${variant}`}>{t("facets.level")}</label>
      <select
        id={`collab-level-${variant}`}
        value={level}
        onChange={(event) =>
          onChange({ level: event.target.value as CollaborationLevel, faculty: undefined })
        }
        className={selectClass}
      >
        {LEVELS.map((value) => (
          <option key={value} value={value}>
            {t(`facets.level_${value}`)}
          </option>
        ))}
      </select>
    </div>
  );

  const groups: GroupDef[] = [
    {
      key: "type",
      label: t("facets.type"),
      defaultOpen: true,
      activeValues: params.type ?? [],
      values: (facets?.org_type ?? []).map((f) => ({
        value: f.value,
        count: f.count,
        label: labels.orgType(f.value),
        swatch: orgTypeCssVar(f.value),
      })),
    },
    {
      key: "country",
      label: t("facets.country"),
      defaultOpen: true,
      searchable: true,
      activeValues: params.country ?? [],
      values: (facets?.country ?? []).map((f) => ({
        value: f.value,
        count: f.count,
        label: labels.region(f.value),
      })),
    },
    ...(hasUnits
      ? [
          {
            key: "faculty" as const,
            label: t(`facets.level_${level}`),
            defaultOpen: true,
            searchable: level === "group",
            headerExtra: unitLevelPicker,
            activeValues: params.faculty ?? [],
            values: (facets?.orgunit ?? []).map((f) => ({
              value: f.value,
              count: f.count,
              label: f.label ?? f.value,
            })),
          },
        ]
      : []),
    {
      key: "oa_status",
      label: t("facets.oaStatus"),
      defaultOpen: false,
      activeValues: params.oa_status ?? [],
      values: (facets?.oa_status ?? []).map((f) => ({
        value: f.value,
        count: f.count,
        label: labels.oaStatus(f.value),
      })),
    },
    {
      key: "topic",
      label: t("facets.topic"),
      defaultOpen: false,
      searchable: true,
      activeValues: params.topic ?? [],
      values: (facets?.topic ?? []).map((f) => ({
        value: f.value,
        count: f.count,
        label: f.value,
      })),
    },
    {
      key: "funder",
      label: t("facets.funder"),
      defaultOpen: false,
      searchable: true,
      activeValues: params.funder ?? [],
      values: (facets?.funder ?? []).map((f) => ({
        value: f.key,
        count: f.works,
        label: f.name,
      })),
    },
    {
      key: "project",
      label: t("facets.project"),
      defaultOpen: false,
      searchable: true,
      activeValues: params.project ?? [],
      values: (facets?.project ?? []).map((p) => ({
        value: p.key,
        count: p.works,
        label: p.acronym ? `${p.acronym}${p.code ? ` (${p.code})` : ""}` : p.code || p.key,
        sublabel: p.funder ?? undefined,
      })),
    },
    {
      key: "source",
      label: t("facets.source"),
      defaultOpen: false,
      activeValues: params.source ?? [],
      values: (facets?.source ?? []).map((f) => ({
        value: f.value,
        count: f.count,
        label: labels.source(f.value),
      })),
    },
  ];

  return (
    <div className="space-y-3" aria-busy={loading || updating || undefined}>
      {groups.map((group) => (
        <FacetSection
          key={group.key}
          group={group}
          onToggle={(key, value) => onChange({ [key]: toggleValue(params[key], value) })}
          variant={variant}
          loading={loading}
          updating={updating}
        />
      ))}
    </div>
  );
}
