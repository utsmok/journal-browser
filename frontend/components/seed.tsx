import { dehydrate, HydrationBoundary, QueryClient, type QueryKey } from "@tanstack/react-query";
import type { ReactNode } from "react";

/**
 * Puts a document fetched on the server into the React Query cache, under the
 * key the page's useQuery reads, before the page renders. The page then
 * renders its real content on the server, and the browser finds the data
 * instead of fetching the document a second time. A null document (the
 * backend failed) renders the page unseeded, so the browser fetches it as
 * before.
 */
export function Seed<T>({
  queryKey,
  data,
  children,
}: {
  queryKey: QueryKey;
  data: T | null;
  children: ReactNode;
}) {
  return <Seeds entries={[{ queryKey, data }]}>{children}</Seeds>;
}

/** One cache entry for Seeds: the key a page's useQuery reads and its document. */
export type SeedEntry = { queryKey: QueryKey; data: unknown };

/**
 * Seed for a page that reads several documents on first paint (a result list
 * and its facets, say). Null documents are skipped, as in Seed.
 */
export function Seeds({ entries, children }: { entries: SeedEntry[]; children: ReactNode }) {
  const present = entries.filter((entry) => entry.data !== null && entry.data !== undefined);
  if (present.length === 0) return children;
  const queryClient = new QueryClient();
  for (const entry of present) queryClient.setQueryData(entry.queryKey, entry.data);
  return <HydrationBoundary state={dehydrate(queryClient)}>{children}</HydrationBoundary>;
}
