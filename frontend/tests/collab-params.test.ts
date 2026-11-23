import { describe, expect, it } from "vitest";

import {
  hasActiveCollabFilters,
  readCollabParams,
  writeCollabParams,
} from "@/components/collaborations/use-collab-params";

describe("collaboration URL params", () => {
  it("round-trips search, multi-select facets, and analytical modes cleanly", () => {
    const original = {
      q: "TU Delft",
      type: ["education", "healthcare"],
      country: ["NL", "DE"],
      oa_status: ["closed"],
      topic: ["Robotics"],
      size: "small" as const,
      rollup: false,
      lead: "home" as const,
      min_works: 5,
      shares_deals: true,
      sort: "oa_share" as const,
      dir: "desc" as const,
    };

    const qs = writeCollabParams(original);
    const parsed = readCollabParams(new URLSearchParams(qs));

    expect(parsed).toEqual(original);
    expect(hasActiveCollabFilters(parsed)).toBe(true);
  });

  it("omits default modes from the URL and treats empty params as unfiltered", () => {
    const qs = writeCollabParams({ size: "standard", rollup: true, lead: "all", min_works: 1 });
    expect(qs).toBe("");
    expect(hasActiveCollabFilters(readCollabParams(new URLSearchParams(qs)))).toBe(false);
  });
});
