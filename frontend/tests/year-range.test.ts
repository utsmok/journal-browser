import { describe, expect, it } from "vitest";

import { effectiveYearRange } from "@/hooks/use-year-filter";

describe("effectiveYearRange", () => {
  const bounds = { start: 2015, end: 2025 };

  it("returns null for no selection or an empty clamp", () => {
    expect(effectiveYearRange(null, bounds)).toBeNull();
    // Window start after window end: nothing is in force.
    expect(effectiveYearRange({ from: 2020, to: 2024 }, { start: 2025, end: 2020 })).toBeNull();
  });

  it("fills open ends with the data window", () => {
    expect(effectiveYearRange({}, bounds)).toEqual({ from: 2015, to: 2025 });
    expect(effectiveYearRange({ from: 2018, to: undefined }, bounds)).toEqual({
      from: 2018,
      to: 2025,
    });
  });

  it("clamps into the data window", () => {
    expect(effectiveYearRange({ from: 2000, to: 2030 }, bounds)).toEqual({
      from: 2015,
      to: 2025,
    });
  });

  it("falls back to the API validation range without bounds", () => {
    expect(effectiveYearRange({ from: 1800, to: 2200 })).toEqual({ from: 1900, to: 2100 });
  });

  it("turns off when the selection clamps to nothing", () => {
    // Both endpoints inside the window but reversed: clamp keeps them
    // ordered apart, so the range is empty.
    expect(effectiveYearRange({ from: 2024, to: 2010 }, bounds)).toBeNull();
  });
});
