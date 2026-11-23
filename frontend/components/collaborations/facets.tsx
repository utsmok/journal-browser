"use client";

import { useTranslations } from "next-intl";

import { useCollabLabels } from "@/components/collaborations/labels";
import { type UpdateParams } from "@/components/collaborations/use-collab-params";
import { FacetGroupList, type FacetGroupDef } from "@/components/filter-panel";
import {
  type CollabMultiKey,
  type CollaborationFacets,
  type CollaborationLevel,
  type CollaborationSearchParams,
} from "@/lib/api";

/** Adds `value` to a multi-select filter, or removes it when it is selected already. */
function toggleValue(current: string[] | undefined, value: string): string[] {
  const next = new Set(current ?? []);
  if (!next.delete(value)) next.add(value);
  return [...next];
}

const LEVELS: readonly CollaborationLevel[] = ["faculty", "group", "institute"];

const selectClass =
  "rounded-[var(--radius)] border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-xs text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]";

/** The facet groups of the partner list, drawn from the counts the API
 * returns for the current filter set. A new facet needs its line in
 * `groups` here and its label under `facets` in the messages. */
export function CollaborationFacets({
  params,
  facets,
  onChange,
  variant,
  loading,
}: {
  params: CollaborationSearchParams;
  facets: CollaborationFacets | null | undefined;
  onChange: UpdateParams;
  variant: "chips" | "rows";
  loading?: boolean;
}) {
  const t = useTranslations("collaborations");
  const labels = useCollabLabels();
  // The unit facet only exists for institutions whose units are in the data.
  const hasUnits = (facets?.orgunit.length ?? 0) > 0;
  const level = params.level ?? "faculty";

  const groups: FacetGroupDef[] = [
    {
      key: "type",
      label: t("facets.type"),
      defaultOpen: true,
      activeValues: params.type ?? [],
      values: (facets?.org_type ?? []).map((f) => ({
        value: f.value,
        count: f.count,
        label: labels.orgType(f.value),
      })),
    },
    {
      key: "country",
      label: t("facets.country"),
      defaultOpen: true,
      activeValues: params.country ?? [],
      values: (facets?.country ?? []).map((f) => ({
        value: f.value,
        count: f.count,
        label: labels.region(f.value),
      })),
    },
    {
      key: "faculty",
      label: t(`facets.level_${level}`),
      defaultOpen: false,
      activeValues: params.faculty ?? [],
      values: (facets?.orgunit ?? []).map((f) => ({
        value: f.value,
        count: f.count,
        label: f.label ?? f.value,
      })),
    },
    {
      key: "funder",
      label: t("facets.funder"),
      defaultOpen: false,
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
      activeValues: params.project ?? [],
      values: (facets?.project ?? []).map((p) => ({
        value: p.key,
        count: p.works,
        label: p.acronym || p.code || p.key,
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
  const visible = groups.filter((group) => group.key !== "faculty" || hasUnits);

  return (
    <div>
      {hasUnits && (
        <p className="mb-2.5 flex flex-wrap items-center gap-2 text-xs text-[var(--muted-foreground)]">
          <label htmlFor={`collab-level-${variant}`}>{t("facets.level")}</label>
          <select
            id={`collab-level-${variant}`}
            value={level}
            onChange={(event) =>
              // Unit names differ per level, so a selected unit no longer applies.
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
        </p>
      )}
      <FacetGroupList
        groups={visible}
        onToggle={(key, value) =>
          onChange({ [key]: toggleValue(params[key as CollabMultiKey], value) })
        }
        variant={variant}
        loading={loading}
      />
    </div>
  );
}
