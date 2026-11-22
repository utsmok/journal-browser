import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";

import { GuideWizard } from "@/components/guide/guide-wizard";
import { InstitutionProvider } from "@/hooks/use-institution";
import * as api from "@/lib/api";
import type { RecommendResponse } from "@/lib/api";
import common from "@/messages/en/common.json";
import guide from "@/messages/en/guide.json";

vi.mock("@/hooks/use-site-meta", () => ({
  useSiteMeta: () => ({
    name: "University of Twente",
    short: "UT",
    libraryUrl: "",
    oaGuideUrl: "",
    supportEmail: "",
    adminContact: null,
    researchPortalUrl: "",
    windowStart: 2020,
  }),
}));

function mockRecommendResponse(overrides: Partial<RecommendResponse> = {}): RecommendResponse {
  return {
    recommendations: [
      {
        rank: 1,
        issn_l: "1000-0001",
        title: "Open Microfluidics",
        publisher: "Diamond Press",
        oa_type: "diamond",
        deal_covered: false,
        deal_summary: null,
        similarity: 0.89,
        match_score: 1.01,
        estimated_cost_label: "€0 (Diamond OA)",
        estimated_cost_eur: 0,
        apc_display: null,
        funder_fit: null,
        green_oa: null,
        quartile: "Q2",
        twoyr_mean_citedness: 3.4,
        h_index: 42,
        works: 5,
        topics: ["Microfluidics", "Droplet Dynamics"],
        summary: "Strong topical fit (89% similarity) with €0 Diamond Open Access publishing.",
        reasons: [
          {
            kind: "topic",
            tone: "positive",
            label: "Strong topical match (89%)",
            detail: "Covers Microfluidics, Droplet Dynamics.",
          },
          {
            kind: "oa",
            tone: "positive",
            label: "Diamond Open Access (€0)",
            detail: "Free to read and free to publish — no APC charged to authors.",
          },
        ],
        relaxed_note: null,
      },
      {
        rank: 2,
        issn_l: "1000-0002",
        title: "Journal of Fluid Membranes",
        publisher: "Elsevier",
        oa_type: "hybrid",
        deal_covered: true,
        deal_summary: {
          publisher_name: "Elsevier",
          duration_text: "2024–2026",
          is_capped: false,
          cap_reached: false,
          cap_text: null,
          is_discount_only: false,
          summary: "100% OA covered.",
          openaccess_nl_url: "https://openaccess.nl/deals/elsevier",
        },
        similarity: 0.85,
        match_score: 0.96,
        estimated_cost_label: "€0 (Covered by UT deal)",
        estimated_cost_eur: 0,
        apc_display: null,
        funder_fit: null,
        green_oa: null,
        quartile: "Q1",
        twoyr_mean_citedness: 6.2,
        h_index: 88,
        works: 18,
        topics: ["Membrane Technology"],
        summary: "Strong topical fit (85% similarity) with €0 open access covered by a UT deal.",
        reasons: [],
        relaxed_note: null,
      },
    ],
    alternatives: [
      {
        rank: 1,
        issn_l: "1000-0006",
        title: "Green Route Fluids",
        publisher: "Classic Press",
        oa_type: "subscription",
        deal_covered: false,
        deal_summary: null,
        similarity: 0.83,
        match_score: 0.83,
        estimated_cost_label: "Subscription (Green OA route)",
        estimated_cost_eur: null,
        apc_display: null,
        funder_fit: null,
        green_oa: "accepted",
        quartile: null,
        twoyr_mean_citedness: null,
        h_index: null,
        works: 1,
        topics: [],
        summary: "Relevant topical match with a Green OA route.",
        reasons: [],
        relaxed_note: "Green OA / Taverne self-archiving route only",
      },
    ],
    candidate_pool_size: 42,
    strict_match_count: 2,
    relaxed: true,
    funder_name: null,
    funder_policy_structured: false,
    ranking_factors: [
      "Local bge-small-en-v1.5 semantic similarity",
      "Budget filter: €0 APC (Diamond OA or active institutional deal)",
    ],
    ...overrides,
  };
}

function renderWizard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale="en" messages={{ common, guide }}>
        <InstitutionProvider code="ut">
          <GuideWizard />
        </InstitutionProvider>
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

function makeMemoryStorage(): Storage {
  const store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key: string) => store.get(key) ?? null,
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    removeItem: (key: string) => {
      store.delete(key);
    },
    setItem: (key: string, value: string) => {
      store.set(key, String(value));
    },
  };
}

beforeEach(() => {
  Object.defineProperty(window, "localStorage", {
    value: makeMemoryStorage(),
    configurable: true,
    writable: true,
  });
  vi.restoreAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("<GuideWizard>", () => {
  it("gates step 1 until >= 15 characters and populates demo manuscript examples", () => {
    renderWizard();
    const nextBtn = screen.getByRole("button", { name: "Continue" });
    expect(nextBtn).toBeDisabled();

    // Privacy shield note is visible on step 1
    expect(
      screen.getByText(/Embedded locally on this server — your manuscript text is never sent/),
    ).toBeInTheDocument();

    // Clicking a demo example fills title + abstract and enables Continue
    fireEvent.click(screen.getByRole("button", { name: "Microfluidic droplet dynamics" }));
    expect(nextBtn).toBeEnabled();
    expect(screen.getByLabelText("Working title")).toHaveValue(
      guide.manuscript.examples.microfluidics.title,
    );
  });

  it("walks all 4 steps, submits recommendJournals, and renders podium + alternatives + transparency", async () => {
    const recommendSpy = vi
      .spyOn(api, "recommendJournals")
      .mockResolvedValue(mockRecommendResponse());

    renderWizard();

    // Step 1: pick example -> Continue
    fireEvent.click(screen.getByRole("button", { name: "Membrane water purification" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    // Step 2: default "No specific funder" -> Continue
    expect(
      screen.getByText("Do you have a research funder with open-access rules?"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    // Step 3: switch to Capped APC budget and pick €3,500 preset -> Continue
    fireEvent.click(screen.getByRole("radio", { name: /Capped APC budget/ }));
    fireEvent.click(screen.getByRole("button", { name: "€3,500" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    // Step 4: toggle Q1-Q2 nudge ON and submit
    const establishedSwitch = screen.getByRole("switch", {
      name: /Boost Q1–Q2 \/ established venues/,
    });
    expect(establishedSwitch).toHaveAttribute("aria-checked", "false");
    fireEvent.click(establishedSwitch);
    expect(establishedSwitch).toHaveAttribute("aria-checked", "true");

    fireEvent.click(screen.getByRole("button", { name: "Find recommended journals" }));

    await waitFor(() => {
      expect(screen.getByText("Open Microfluidics")).toBeInTheDocument();
    });

    expect(recommendSpy).toHaveBeenCalledWith(
      "ut",
      expect.objectContaining({
        budget_mode: "capped",
        max_apc_eur: 3500,
        prefer_institution_history: true,
        prefer_established: true,
        include_non_journals: false,
      }),
    );

    // Podium #1 + #2 + relaxed alternative + transparency card + semantic handoff
    expect(screen.getByText("#1 Top match")).toBeInTheDocument();
    expect(screen.getByText("Journal of Fluid Membranes")).toBeInTheDocument();
    expect(screen.getByText("Green Route Fluids")).toBeInTheDocument();
    expect(screen.getByText(/Green OA \/ Taverne self-archiving route only/)).toBeInTheDocument();
    expect(screen.getByText("How these recommendations were built")).toBeInTheDocument();
    const handoffHref = screen
      .getByRole("link", { name: /Explore broader semantic matches in Search/ })
      .getAttribute("href");
    expect(handoffHref).toMatch(/^\/ut\/?\?q=/);
    expect(handoffHref).toContain("&mode=semantic");
  });

  it("persists answers to localStorage and clears them on Reset", () => {
    renderWizard();
    fireEvent.click(screen.getByRole("button", { name: "Responsible AI governance" }));
    expect(window.localStorage.getItem("ojb_guide_prefs_v1")).toContain(
      "Auditing algorithmic fairness",
    );

    fireEvent.click(screen.getByRole("button", { name: "Reset saved wizard answers" }));
    expect(window.localStorage.getItem("ojb_guide_prefs_v1")).toBeNull();
    expect(screen.getByLabelText("Working title")).toHaveValue("");
  });
});
