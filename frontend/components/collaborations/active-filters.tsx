"use client";

import { X } from "lucide-react";
import { useTranslations } from "next-intl";

import { useCollabLabels } from "@/components/collaborations/labels";
import {
  EMPTY_COLLAB_FILTERS,
  hasActiveCollabFilters,
  type UpdateParams,
} from "@/components/collaborations/collab-params";
import { Button } from "@/components/ui/button";
import { useSiteMeta } from "@/hooks/use-site-meta";
import type { CollabMultiKey, CollaborationFacets, CollaborationSearchParams } from "@/lib/api";

type Chip = { id: string; label: string; onRemove: () => void };

/** Dismissible bar of every active filter. Shared between the partners
 * overview and the partner detail page so carried-over filters are always
 * visible and 1-click removable. */
export function ActiveFiltersBar({
  params,
  facets,
  onChange,
  variant = "inline",
  onResetAll,
}: {
  params: CollaborationSearchParams;
  facets?: CollaborationFacets | null;
  onChange: UpdateParams;
  /** "banner" renders a highlighted notice on partner detail pages. */
  variant?: "inline" | "banner";
  onResetAll?: () => void;
}) {
  const t = useTranslations("collaborations");
  const labels = useCollabLabels();
  const site = useSiteMeta();

  if (!hasActiveCollabFilters(params)) return null;

  const funderNames = new Map((facets?.funder ?? []).map((f) => [f.key, f.name]));
  const projectNames = new Map(
    (facets?.project ?? []).map((p) => [p.key, p.acronym || p.code || p.key]),
  );

  const removeMulti = (key: CollabMultiKey, value: string) => {
    const next = (params[key] ?? []).filter((v) => v !== value);
    onChange({ [key]: next.length ? next : undefined });
  };

  const chips: Chip[] = [];

  if (params.q) {
    chips.push({
      id: "q",
      label: t("activeFilters.search", { value: params.q }),
      onRemove: () => onChange({ q: undefined }),
    });
  }
  if (params.size && params.size !== "standard") {
    chips.push({
      id: "size",
      label: t("activeFilters.size", {
        value: params.size === "small" ? t("modes.sizeSmall") : t("modes.sizeAll"),
      }),
      onRemove: () => onChange({ size: undefined }),
    });
  }
  if (params.rollup === false) {
    chips.push({
      id: "rollup",
      label: t("activeFilters.rollupRaw"),
      onRemove: () => onChange({ rollup: undefined }),
    });
  }
  if (params.lead && params.lead !== "all") {
    chips.push({
      id: "lead",
      label: t("activeFilters.lead", {
        value:
          params.lead === "home"
            ? t("modes.leadHome", { inst: site.short })
            : t("modes.leadPartner"),
      }),
      onRemove: () => onChange({ lead: undefined }),
    });
  }
  if (params.min_works && params.min_works > 1) {
    chips.push({
      id: "min_works",
      label: t("activeFilters.minWorks", { count: params.min_works }),
      onRemove: () => onChange({ min_works: undefined }),
    });
  }
  if (params.shares_deals) {
    chips.push({
      id: "shares_deals",
      label: t("activeFilters.sharesDeals"),
      onRemove: () => onChange({ shares_deals: undefined }),
    });
  }

  for (const v of params.type ?? []) {
    chips.push({
      id: `type:${v}`,
      label: `${t("facets.type")}: ${labels.orgType(v)}`,
      onRemove: () => removeMulti("type", v),
    });
  }
  for (const v of params.country ?? []) {
    chips.push({
      id: `country:${v}`,
      label: `${t("facets.country")}: ${labels.region(v)}`,
      onRemove: () => removeMulti("country", v),
    });
  }
  for (const v of params.faculty ?? []) {
    chips.push({
      id: `faculty:${v}`,
      label: `${t(`facets.level_${params.level ?? "faculty"}`)}: ${v}`,
      onRemove: () => removeMulti("faculty", v),
    });
  }
  for (const v of params.oa_status ?? []) {
    chips.push({
      id: `oa:${v}`,
      label: `${t("facets.oaStatus")}: ${labels.oaStatus(v)}`,
      onRemove: () => removeMulti("oa_status", v),
    });
  }
  for (const v of params.topic ?? []) {
    chips.push({
      id: `topic:${v}`,
      label: `${t("facets.topic")}: ${v}`,
      onRemove: () => removeMulti("topic", v),
    });
  }
  for (const v of params.funder ?? []) {
    const clean = funderNames.get(v) ?? v.replace(/^(openalex|openaire):/, "");
    chips.push({
      id: `funder:${v}`,
      label: `${t("facets.funder")}: ${clean}`,
      onRemove: () => removeMulti("funder", v),
    });
  }
  for (const v of params.project ?? []) {
    const clean = projectNames.get(v) ?? v.replace(/^(openalex|openaire):/, "");
    chips.push({
      id: `project:${v}`,
      label: `${t("facets.project")}: ${clean}`,
      onRemove: () => removeMulti("project", v),
    });
  }
  for (const v of params.source ?? []) {
    chips.push({
      id: `source:${v}`,
      label: `${t("facets.source")}: ${labels.source(v)}`,
      onRemove: () => removeMulti("source", v),
    });
  }

  if (chips.length === 0) return null;

  const clear = () => {
    if (onResetAll) onResetAll();
    else onChange(EMPTY_COLLAB_FILTERS);
  };

  if (variant === "banner") {
    return (
      <div
        role="status"
        className="mt-4 rounded-[var(--radius)] border border-[var(--brand-tint-border)] bg-[var(--brand-tint-bg)] px-4 py-3 text-sm"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-medium text-[var(--foreground)]">{t("activeFilters.detailNotice")}</p>
          <Button variant="outline" size="sm" onClick={clear}>
            {t("activeFilters.showAll", { inst: site.short })}
          </Button>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {chips.map((chip) => (
            <button
              key={chip.id}
              type="button"
              onClick={chip.onRemove}
              aria-label={t("activeFilters.remove", { label: chip.label })}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-0.5 text-xs text-[var(--foreground)] hover:border-[var(--primary)]"
            >
              <span className="max-w-[18rem] truncate">{chip.label}</span>
              <X aria-hidden className="size-3 shrink-0 opacity-70" />
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div
      aria-label={t("activeFilters.label")}
      className="flex flex-wrap items-center gap-1.5 text-xs"
    >
      {chips.map((chip) => (
        <button
          key={chip.id}
          type="button"
          onClick={chip.onRemove}
          aria-label={t("activeFilters.remove", { label: chip.label })}
          className="inline-flex items-center gap-1 rounded-md border border-[var(--brand-tint-border)] bg-[var(--brand-tint-bg)] px-2 py-1 text-[var(--primary-text)] hover:border-[var(--primary)]"
        >
          <span className="max-w-[16rem] truncate">{chip.label}</span>
          <X aria-hidden className="size-3 shrink-0" />
        </button>
      ))}
      <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={clear}>
        {t("search.clearAll")}
      </Button>
    </div>
  );
}
