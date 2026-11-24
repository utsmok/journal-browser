import { describe, expect, it } from "vitest";

import {
  apcAmount,
  apcRowGap,
  apcStatsText,
  apcSummary,
  countryName,
  formatApc,
  formatEur,
} from "@/lib/format";

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

describe("apcSummary", () => {
  const noPaid = { apc_low: null, apc_high: null, apc_stats: [] };
  const stats24 = [
    {
      period: 2024,
      article_count: 22,
      paid_count: 22,
      zero_count: 0,
      euro_min: 1800,
      euro_max: 2500,
      euro_mean: 2193,
    },
  ];

  it("shows the publisher list price, and the amount as published when it was converted", () => {
    expect(
      apcSummary({
        apc_source: "openalex",
        apc_currency: "EUR",
        apc_price: 4460,
        apc_year: 2026,
        apc_original_currency: "USD",
        apc_original_price: 4890,
        ...noPaid,
      } as never),
    ).toEqual({
      kind: "list",
      source: "OpenAlex",
      year: 2026,
      currency: "EUR",
      amount: "€4,460",
      original: "$4,890",
      paid: null,
    });
  });

  it("keeps a list price in its own currency when no euro exchange rate exists", () => {
    expect(
      apcSummary({
        apc_source: "doaj",
        apc_currency: "UAH",
        apc_price: 120000,
        apc_year: 2025,
        apc_original_currency: "UAH",
        apc_original_price: 120000,
        ...noPaid,
      } as never),
    ).toMatchObject({ kind: "list", source: "DOAJ", currency: "UAH", amount: "UAH 120,000" });
  });

  it("shows the range of amounts paid only for a journal without a list price", () => {
    expect(
      apcSummary({
        apc_source: "openapc",
        apc_currency: "EUR",
        apc_price: 2193,
        apc_year: 2024,
        apc_low: 1800,
        apc_high: 2500,
        apc_stats: stats24,
      } as never),
    ).toEqual({
      kind: "paid",
      source: null,
      year: 2024,
      currency: "EUR",
      amount: "€1,800 to 2,500",
      original: null,
      paid: { amount: "€2,190", period: 2024, count: 22 },
    });
  });

  it("keeps the mean amount paid for a journal that also has a list price", () => {
    const summary = apcSummary({
      apc_source: "openalex",
      apc_currency: "EUR",
      apc_price: 4450,
      apc_year: 2026,
      apc_low: 1800,
      apc_high: 2500,
      apc_stats: stats24,
    } as never);
    expect(summary.kind).toBe("list");
    expect(summary.paid).toEqual({ amount: "€2,190", period: 2024, count: 22 });
  });

  it("counts only the paid articles behind the mean", () => {
    const stats = {
      period: 2024,
      article_count: 17,
      paid_count: 12,
      zero_count: 5,
      euro_min: 1800,
      euro_max: 2500,
      euro_mean: 2193,
    };
    const apc = {
      apc_source: "openapc",
      apc_currency: "EUR",
      apc_price: 2193,
      apc_year: 2024,
      apc_low: 1800,
      apc_high: 2500,
    };
    expect(apcSummary({ ...apc, apc_stats: [stats] } as never).paid?.count).toBe(12);
    expect(
      apcSummary({ ...apc, apc_stats: [{ ...stats, paid_count: null }] } as never).paid?.count,
    ).toBeNull();
  });

  it("has nothing to show for a journal without any price", () => {
    expect(apcSummary({ apc_source: null, apc_price: null, ...noPaid } as never).kind).toBe("none");
  });
});

describe("apcRowGap", () => {
  const unpriced = {
    period: 2025,
    article_count: 17,
    paid_count: 0,
    zero_count: 17,
    euro_min: null,
    euro_max: null,
    euro_mean: null,
  };

  it("names why a period has no mean", () => {
    expect(apcRowGap(unpriced as never)).toBe("allDealPaid");
    expect(apcRowGap({ ...unpriced, zero_count: 12 } as never)).toBe("partDealPaid");
    expect(apcRowGap({ ...unpriced, zero_count: 0 } as never)).toBe("noAmount");
    expect(apcRowGap({ ...unpriced, zero_count: null } as never)).toBe("noneAboveZero");
  });

  it("stays silent on exact figures and flags a mean that still counts €0 articles", () => {
    const paid = {
      period: 2024,
      article_count: 5,
      paid_count: 5,
      zero_count: 0,
      euro_min: 1800,
      euro_max: 2500,
      euro_mean: 2100,
    };
    expect(apcRowGap(paid as never)).toBeNull();
    expect(apcRowGap({ ...paid, paid_count: null, euro_min: null } as never)).toBe("legacyMean");
    // A response from before the counts existed has nothing to explain them.
    expect(
      apcRowGap({
        period: 2025,
        article_count: 1,
        euro_min: null,
        euro_max: null,
        euro_mean: null,
      } as never),
    ).toBeNull();
  });
});

describe("apcStatsText", () => {
  it("renders one line per period with the paid count and the mean", () => {
    const text = apcStatsText([
      {
        period: 2024,
        article_count: 3,
        paid_count: 1,
        zero_count: 2,
        euro_min: 1900,
        euro_max: 1900,
        euro_mean: 1900,
      },
      { period: 2023, article_count: 1, euro_min: 1800, euro_max: 2000, euro_mean: 1900 },
    ] as never);
    expect(text.split("\n")).toEqual([
      "2024: €1,900 · 1 paid · mean €1,900",
      "2023: €1,800–2,000 · paid count not stored · approx. mean €1,900",
    ]);
  });
});

describe("countryName", () => {
  it("resolves ISO-2 country codes and falls back cleanly", () => {
    expect(countryName("nl")).toBe("Netherlands");
    expect(countryName("GB")).toBe("United Kingdom");
    expect(countryName("")).toBe("—");
    expect(countryName(null)).toBe("—");
  });
});
