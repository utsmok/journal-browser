"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

/** Display names for the raw codes the API returns: ROR organisation types,
 * ISO country codes and the payloads that supply partner links. */
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
    const sources: Record<string, string> = {
      openalex: t("sources.openalex"),
      openaire: t("sources.openaire"),
    };
    const source = (value: string) => sources[value] ?? value;
    return {
      orgType: (value: string) => types[value.toLowerCase()] ?? value,
      region: (code: string) => {
        try {
          return regions.of(code.toUpperCase());
        } catch {
          return code;
        }
      },
      source,
      sources: (values: string[]) => values.map(source).join(" · "),
    };
  }, [regions, t]);
}
