"use client";

import * as React from "react";

import type { InstitutionDirectoryEntry } from "@/lib/admin";

/**
 * Institution path scope for /{code}/... pages. Provided by app/[inst]/layout;
 * empty string for global surfaces (landing chooser, admin).
 */
const InstitutionContext = React.createContext<string>("");

/**
 * The institution's directory row as app/[inst]/layout fetched it on the
 * server. React may hydrate a page only after the site header's effects have
 * sent its own requests, so a page that waits for the browser's directory
 * request can render values its server HTML never had. The row comes with the
 * page instead, and both renders resolve the same values.
 */
const InstitutionRowContext = React.createContext<InstitutionDirectoryEntry | null>(null);

export function InstitutionProvider({
  code,
  row = null,
  children,
}: {
  code: string;
  row?: InstitutionDirectoryEntry | null;
  children: React.ReactNode;
}) {
  return (
    <InstitutionContext.Provider value={code}>
      <InstitutionRowContext.Provider value={row}>{children}</InstitutionRowContext.Provider>
    </InstitutionContext.Provider>
  );
}

export function useInstitution(): string {
  return React.useContext(InstitutionContext);
}

/** The server-fetched directory row for `inst`, or null when there is none. */
export function useInstitutionRow(inst: string): InstitutionDirectoryEntry | null {
  const row = React.useContext(InstitutionRowContext);
  return row?.code === inst ? row : null;
}
