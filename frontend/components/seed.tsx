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
  if (data === null) return children;
  const queryClient = new QueryClient();
  queryClient.setQueryData(queryKey, data);
  return <HydrationBoundary state={dehydrate(queryClient)}>{children}</HydrationBoundary>;
}
