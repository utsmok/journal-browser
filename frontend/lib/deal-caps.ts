import type { components } from "@/lib/api-types";

export type CapUsageEntry = components["schemas"]["CapUsageEntry"];

/** Entries of the latest contract year in the usage list, pool-less first,
 * then alphabetical by pool (OUP reports hybrid and full OA pools). */
export function latestYearUsage(usage: CapUsageEntry[] | null | undefined): CapUsageEntry[] {
  if (!usage || usage.length === 0) return [];
  const maxYear = Math.max(...usage.map((entry) => entry.year));
  return usage
    .filter((entry) => entry.year === maxYear)
    .sort(
      (a, b) => (a.pool ? 1 : 0) - (b.pool ? 1 : 0) || (a.pool ?? "").localeCompare(b.pool ?? ""),
    );
}

/** Status is derived, never stored: the publisher cap is reached when the
 * reported used count meets the total, so free OA publishing is no longer
 * guaranteed for the rest of the contract year. */
export function capReached(entry: CapUsageEntry): boolean {
  return entry.used != null && entry.used >= entry.total;
}
