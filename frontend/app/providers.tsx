"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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
const SiteMetaContext = React.createContext<SiteFallback | null>(null);

export function useSiteFallback(): SiteFallback | null {
  return React.useContext(SiteMetaContext);
}

export function Providers({
  children,
  siteFallback,
}: {
  children: React.ReactNode;
  siteFallback: SiteFallback;
}) {
  const [client] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60_000,
            retry: 1,
            placeholderData: (data: unknown) => data, // keepPreviousData for lists
          },
        },
      }),
  );
  return (
    <SiteMetaContext.Provider value={siteFallback}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </SiteMetaContext.Provider>
  );
}
