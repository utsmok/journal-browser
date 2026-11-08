import { cleanup, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";

import { AdminGate } from "@/components/admin/admin-gate";

// jsdom has no app-router context, and AdminShell's isActive dereferences the
// pathname, so the router seam must produce one.
vi.mock("next/navigation", () => ({ usePathname: () => "/admin" }));

describe("<AdminGate>", () => {
  beforeEach(() => {
    cleanup();
    sessionStorage.clear();
  });

  it("renders the login form and does not mount children without a token", () => {
    render(
      <AdminGate>
        <p>authenticated children</p>
      </AdminGate>,
    );

    expect(screen.getByPlaceholderText("Admin password")).toBeInTheDocument();
    expect(screen.queryByText("authenticated children")).not.toBeInTheDocument();
  });

  it("mounts children once a token exists in sessionStorage", async () => {
    sessionStorage.setItem("jb-admin-token", "test-token");

    render(
      <AdminGate>
        <p>authenticated children</p>
      </AdminGate>,
    );

    expect(await screen.findByText("authenticated children")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Admin password")).not.toBeInTheDocument();
  });
});
