import { cleanup, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it } from "vitest";
import "@testing-library/jest-dom/vitest";

import { ApcText } from "@/components/apc-text";
import common from "@/messages/en/common.json";

afterEach(cleanup);

function renderApc(apc: Record<string, unknown>) {
  return render(
    <NextIntlClientProvider locale="en" messages={{ common }}>
      <ApcText apc={apc as never} />
    </NextIntlClientProvider>,
  );
}

const noPaid = { apc_low: null, apc_high: null, apc_stats: [] };

describe("ApcText", () => {
  it("labels a list price with its source, year and amount as published", () => {
    renderApc({
      apc_source: "openalex",
      apc_currency: "EUR",
      apc_price: 4460,
      apc_year: 2026,
      apc_original_currency: "USD",
      apc_original_price: 4890,
      ...noPaid,
    });
    expect(screen.getByText("€4,460")).toHaveAttribute(
      "title",
      "List price: €4,460 from OpenAlex (2026), converted from $4,890 at the 1 January exchange rate of the European Central Bank.",
    );
    expect(screen.queryByText("paid")).toBeNull();
  });

  it("marks amounts paid as paid, so they never pass for a list price", () => {
    renderApc({
      apc_source: "openapc",
      apc_currency: "EUR",
      apc_price: 2193,
      apc_year: 2024,
      apc_low: 1800,
      apc_high: 2500,
      apc_stats: [
        {
          period: 2024,
          article_count: 22,
          paid_count: 22,
          zero_count: 0,
          euro_min: 1800,
          euro_max: 2500,
          euro_mean: 2193,
        },
      ],
    });
    expect(screen.getByText("€1,800 to 2,500")).toBeInTheDocument();
    expect(screen.getByText("paid")).toHaveAttribute(
      "title",
      "No list price is known. Institutions reported paying €1,800 to 2,500 per article for this journal (OpenAPC). In 2024 the mean was €2,190 over 22 paid articles.",
    );
  });

  it("shows a dash for a journal without any price", () => {
    renderApc({ apc_source: null, apc_price: null, ...noPaid });
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
