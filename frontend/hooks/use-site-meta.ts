"use client";

import { useFreshness } from "./use-api";

/**
 * Institution display values from /meta/freshness, with the Twente defaults
 * as fallback so pre-hydration and offline renders stay coherent.
 */
export function useSiteMeta() {
  const { data } = useFreshness();
  return {
    name: data?.institution ?? "University of Twente",
    short: data?.institution_short ?? "Twente",
    libraryUrl:
      data?.library_url ?? "https://www.utwente.nl/library",
    oaGuideUrl:
      data?.oa_guide_url ??
      "https://www.utwente.nl/en/service-portal/university-library/publication-archiving/open-access",
    supportEmail: data?.support_email ?? "open-access@utwente.nl",
    adminContact: data?.admin_contact || null,
    researchPortalUrl: data?.research_portal_url ?? "https://research.utwente.nl",
  };
}
