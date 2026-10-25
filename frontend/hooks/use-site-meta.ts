"use client";

import { useFreshness } from "./use-api";
import { useSiteFallback } from "../app/providers";

/**
 * Institution display values: /meta/freshness is authoritative once loaded;
 * the server layout seeds the same values from the stack's JB_* env, so the
 * first render (and a backend outage) already shows this deployment's
 * institution instead of the Twente defaults.
 */
export function useSiteMeta() {
  const { data } = useFreshness();
  const seed = useSiteFallback();
  return {
    name: data?.institution ?? seed?.name ?? "University of Twente",
    short: data?.institution_short ?? seed?.short ?? "Twente",
    libraryUrl: data?.library_url ?? seed?.libraryUrl ?? "https://www.utwente.nl/library",
    oaGuideUrl:
      data?.oa_guide_url ??
      seed?.oaGuideUrl ??
      "https://www.utwente.nl/en/service-portal/university-library/publication-archiving/open-access",
    supportEmail: data?.support_email ?? seed?.supportEmail ?? "open-access@utwente.nl",
    adminContact: data?.admin_contact || seed?.adminContact || null,
    researchPortalUrl:
      data?.research_portal_url ?? seed?.researchPortalUrl ?? "https://research.utwente.nl",
    /** First publication year the deployment's statistics cover. */
    windowStart: data?.data_window_start ?? 2020,
  };
}
