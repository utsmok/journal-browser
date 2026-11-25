import { describe, expect, it } from "vitest";

import { daysAgo, harvestUrl, sourceInfo, staleSources } from "@/lib/freshness";
import type { SourceFreshness } from "@/lib/freshness";

function row(
  source: string,
  status: SourceFreshness["status"],
  institution_code: string | null = null,
): SourceFreshness {
  return {
    source,
    institution_code,
    schedule: "nightly",
    status,
    last_success_at: "2026-11-24T02:00:00Z",
    last_run_at: "2026-11-25T02:00:00Z",
    last_run_status: "completed",
    failed_parts: [],
  };
}

describe("daysAgo", () => {
  it("counts calendar days, so a minute after midnight is a new day", () => {
    const now = new Date(2026, 10, 25, 0, 1);
    expect(daysAgo(new Date(2026, 10, 25, 0, 0).toISOString(), now)).toBe(0);
    expect(daysAgo(new Date(2026, 10, 24, 23, 59).toISOString(), now)).toBe(1);
    expect(daysAgo(new Date(2026, 10, 22, 6, 0).toISOString(), now)).toBe(3);
  });

  it("counts a day cut short or lengthened by a clock change as one day", () => {
    expect(daysAgo(new Date(2026, 2, 28, 12, 0).toISOString(), new Date(2026, 2, 29, 12, 0))).toBe(
      1,
    );
    expect(daysAgo(new Date(2026, 9, 24, 12, 0).toISOString(), new Date(2026, 9, 25, 12, 0))).toBe(
      1,
    );
  });

  it("never reports a negative age for a clock that is behind", () => {
    expect(daysAgo(new Date(2026, 10, 26, 9, 0).toISOString(), new Date(2026, 10, 25, 9, 0))).toBe(
      0,
    );
  });
});

describe("staleSources", () => {
  it("keeps the failed and overdue sources, failed first, in a new list", () => {
    const rows = [
      row("doaj", "overdue"),
      row("pure", "ok", "ut"),
      row("crossref", "failed", "rug"),
      row("jct", "overdue"),
    ];
    const stale = staleSources(rows);
    expect(stale.map((r) => r.source)).toEqual(["crossref", "doaj", "jct"]);
    expect(rows.map((r) => r.source)).toEqual(["doaj", "pure", "crossref", "jct"]);
  });
});

describe("source registry", () => {
  it("names every source it knows and falls back to the key", () => {
    expect(sourceInfo("jct").name).toBe("Journal Checker Tool (JCT)");
    expect(sourceInfo("new-source")).toEqual({
      name: "new-source",
      harvest: null,
      url: "",
    });
  });

  it("links a harvest run to the site its source reads", () => {
    expect(harvestUrl("jisc_opf")).toBe("https://openpolicyfinder.jisc.ac.uk");
    expect(harvestUrl("local")).toBe("");
    expect(harvestUrl("unknown")).toBe("");
  });
});
