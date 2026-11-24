"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";

import { UsageTracker } from "@/components/usage-tracker";
import { type SiteFallback, SiteMetaContext } from "@/hooks/site-fallback";
import { YearFilterProvider } from "@/hooks/use-year-filter";

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
      <QueryClientProvider client={client}>
        <YearFilterProvider>
          <UsageTracker />
          {children}
        </YearFilterProvider>
      </QueryClientProvider>
    </SiteMetaContext.Provider>
  );
}
