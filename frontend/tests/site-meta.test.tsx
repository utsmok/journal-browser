import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InstitutionProvider } from "@/hooks/use-institution";
import { useSiteMeta } from "@/hooks/use-site-meta";

vi.mock("next/navigation", () => ({ usePathname: () => "/rug" }));

function Probe() {
  const site = useSiteMeta();
  return <p>{`${site.short}|${site.windowStart ?? "none"}`}</p>;
}

// No request ever answers here, as in a server render and in the browser's
// first render: whatever the page shows has to come from the layout.
function renderProbe(node: ReactNode) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise<Response>(() => {})),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe("useSiteMeta", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows the directory row app/[inst]/layout provided before any query answers", () => {
    renderProbe(
      <InstitutionProvider
        code="rug"
        row={{
          code: "rug",
          name: "Rijksuniversiteit Groningen",
          short_name: "RUG",
          library_url: "https://www.rug.nl/library",
          oa_guide_url: null,
          support_email: "openaccess@rug.nl",
          admin_contact: null,
          research_portal_url: null,
          data_window_start: 2025,
          data_window_end: 2025,
        }}
      >
        <Probe />
      </InstitutionProvider>,
    );
    expect(screen.getByText("RUG|2025")).toBeTruthy();
  });
});
