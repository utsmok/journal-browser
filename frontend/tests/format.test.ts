import { describe, expect, it } from "vitest";

import { apcAmount, apcStatsText, formatApc, formatEur, journalApcText } from "@/lib/format";

describe("formatEur / formatApc", () => {
  it("rounds and locale-groups euros without decimals", () => {
    expect(formatEur(2200)).toBe("2,200");
    expect(formatEur(1499.6)).toBe("1,500");
  });

  it("rounds displayed APCs to the nearest 10 at realistic prices", () => {
    expect(formatApc(2223)).toBe("2,220");
    expect(formatApc(45)).toBe("45");
  });
});

describe("apcAmount", () => {
  it("prefixes known currency symbols and ISO codes otherwise", () => {
    expect(apcAmount("EUR", 2500)).toBe("€2,500");
    expect(apcAmount("USD", 3000)).toBe("$3,000");
    expect(apcAmount("SEK", 300)).toBe("SEK 300");
    expect(apcAmount(null, 300)).toBe(" 300");
  });
});

describe("journalApcText", () => {
  it("prefers the OpenAlex list price, else the OpenAPC range", () => {
    expect(journalApcText({ apc_source: "openalex", apc_price: 2700 } as never)).toBe("€2,700");
    expect(journalApcText({ apc_source: "openapc", apc_low: 2000, apc_high: 2500 } as never)).toBe(
      "€2,000–2,500",
    );
    expect(journalApcText({ apc_source: "openapc", apc_low: 2000, apc_high: 2000 } as never)).toBe(
      "€2,000",
    );
    expect(journalApcText({ apc_source: null } as never)).toBeNull();
  });
});

describe("apcStatsText", () => {
  it("renders one line per period with count and mean", () => {
    const text = apcStatsText([
      { period: 2024, article_count: 8, euro_min: null, euro_max: 2500, euro_mean: 2200 },
      {
        period: 2023,
        article_count: 1,
        euro_min: 1800,
        euro_max: 2000,
        euro_mean: 1900,
      },
    ] as never);
    expect(text.split("\n")).toEqual([
      "2024: €2,500 · 8 articles · mean €2,200",
      "2023: €1,800–2,000 · 1 article · mean €1,900",
    ]);
  });
});
