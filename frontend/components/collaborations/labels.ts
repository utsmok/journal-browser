"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

export const ORG_TYPE_COLORS = new Set([
  "education",
  "facility",
  "healthcare",
  "company",
  "government",
  "nonprofit",
  "funder",
  "archive",
  "other",
]);

export function orgTypeCssVar(value: string | null | undefined): string {
  const key = (value ?? "").toLowerCase();
  return ORG_TYPE_COLORS.has(key) ? `var(--org-${key})` : "var(--org-other)";
}

/** Display names for the raw codes the API returns: ROR organisation types,
 * ISO country codes, OA statuses and link payloads. */
export function useCollabLabels() {
  const t = useTranslations("collaborations");
  const regions = React.useMemo(() => new Intl.DisplayNames(["en"], { type: "region" }), []);
  return React.useMemo(() => {
    const types: Record<string, string> = {
      education: t("types.education"),
      nonprofit: t("types.nonprofit"),
      government: t("types.government"),
      company: t("types.company"),
      healthcare: t("types.healthcare"),
      facility: t("types.facility"),
      archive: t("types.archive"),
      funder: t("types.funder"),
      other: t("types.other"),
      unknown: t("types.unknown"),
    };
    const oaStatuses: Record<string, string> = {
      diamond: t("oaStatuses.diamond"),
      gold: t("oaStatuses.gold"),
      hybrid: t("oaStatuses.hybrid"),
      green: t("oaStatuses.green"),
      bronze: t("oaStatuses.bronze"),
      closed: t("oaStatuses.closed"),
    };
    const sources: Record<string, string> = {
      openalex: t("sources.openalex"),
      openaire: t("sources.openaire"),
    };
    const source = (value: string) => sources[value] ?? value;
    return {
      orgType: (value: string) => types[value.toLowerCase()] ?? value,
      oaStatus: (value: string) => oaStatuses[value.toLowerCase()] ?? value,
      region: (code: string) => {
        try {
          return regions.of(code.toUpperCase()) ?? code;
        } catch {
          return code;
        }
      },
      source,
      sources: (values: string[]) => values.map(source).join(" · "),
    };
  }, [regions, t]);
}
