"use client";

import * as React from "react";

export type SiteFallback = {
  name: string;
  short: string;
  libraryUrl: string;
  oaGuideUrl: string;
  supportEmail: string;
  adminContact: string | null;
  researchPortalUrl: string;
};

/**
 * Institution display values seeded by the server layout from the stack's
 * JB_* env, so the first server render already shows the right institution.
 */
export const SiteMetaContext = React.createContext<SiteFallback | null>(null);

export function useSiteFallback(): SiteFallback | null {
  return React.useContext(SiteMetaContext);
}
