"use client";

import { useInstitution } from "./use-institution";
import { useFreshness, useInstitutionsDirectory } from "./use-api";
import { useSiteFallback } from "../app/providers";

/**
 * Institution display values: the scoped /meta/freshness is authoritative
 * once loaded; the institutions directory covers the pre-hydration render
 * for non-default institutions, and the stack's JB_* env seeds the default.
 */
export function useSiteMeta() {
  const inst = useInstitution();
  const { data } = useFreshness();
  const dir = useInstitutionsDirectory().data?.find((i) => i.code === inst);
  const seed = useSiteFallback();
  // Resolution order: freshness (authoritative) → directory row (per-inst,
  // fast) → this stack's JB_* env seed (default institution only).
  return {
    name: data?.institution ?? dir?.name ?? seed?.name ?? "Journal Browser",
    short: data?.institution_short ?? dir?.short_name ?? seed?.short ?? "",
    libraryUrl: data?.library_url ?? dir?.library_url ?? seed?.libraryUrl ?? "",
    oaGuideUrl: data?.oa_guide_url ?? dir?.oa_guide_url ?? seed?.oaGuideUrl ?? "",
    supportEmail: data?.support_email ?? dir?.support_email ?? seed?.supportEmail ?? "",
    adminContact: data?.admin_contact || dir?.admin_contact || seed?.adminContact || null,
    researchPortalUrl:
      data?.research_portal_url ?? dir?.research_portal_url ?? seed?.researchPortalUrl ?? "",
    /** First publication year this institution's statistics cover. */
    windowStart: data?.data_window_start ?? dir?.data_window_start ?? 2020,
  };
}
