import { cleanup, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";

import { AdminGate } from "@/components/admin/admin-gate";
import admin from "@/messages/en/admin.json";

// jsdom has no app-router context, and AdminShell's isActive dereferences the
// pathname, so the router seam must produce one.
vi.mock("next/navigation", () => ({ usePathname: () => "/admin" }));

// The gate's chrome (login form, shell nav) reads the admin messages.
function renderGate(children: React.ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={{ admin }}>
      <AdminGate>{children}</AdminGate>
    </NextIntlClientProvider>,
  );
}

describe("<AdminGate>", () => {
  beforeEach(() => {
    cleanup();
    sessionStorage.clear();
  });

  it("renders the login form and does not mount children without a token", () => {
    renderGate(<p>authenticated children</p>);

    expect(screen.getByPlaceholderText("Admin password")).toBeInTheDocument();
    expect(screen.queryByText("authenticated children")).not.toBeInTheDocument();
  });

  it("mounts children once a token exists in sessionStorage", async () => {
    sessionStorage.setItem("jb-admin-token", "test-token");

    renderGate(<p>authenticated children</p>);

    expect(await screen.findByText("authenticated children")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Admin password")).not.toBeInTheDocument();
  });
});
