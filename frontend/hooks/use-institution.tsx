"use client";

import * as React from "react";

import type { InstitutionDirectoryEntry } from "@/lib/admin";

/**
 * Institution path scope for /{code}/... pages. Provided by app/[inst]/layout;
 * empty string for global surfaces (landing chooser, admin).
 */
const InstitutionContext = React.createContext<string>("");
/** First statistics year of the scoped institution, read by the server
 * layout, so server and client render the same window-dependent text. */
const WindowStartContext = React.createContext<number | undefined>(undefined);
/** Directory row of the scoped institution, fetched by the server layout,
 * so the first server render and the hydrating client resolve the display
 * values (name, short_name, urls) from the same source. */
const DirectoryContext = React.createContext<InstitutionDirectoryEntry | undefined>(undefined);

export function InstitutionProvider({
  code,
  windowStart,
  directory,
  children,
}: {
  code: string;
  windowStart?: number;
  directory?: InstitutionDirectoryEntry;
  children: React.ReactNode;
}) {
  return (
    <InstitutionContext.Provider value={code}>
      <WindowStartContext.Provider value={windowStart}>
        <DirectoryContext.Provider value={directory}>{children}</DirectoryContext.Provider>
      </WindowStartContext.Provider>
    </InstitutionContext.Provider>
  );
}

export function useInstitution(): string {
  return React.useContext(InstitutionContext);
}

export function useInstitutionWindowStart(): number | undefined {
  return React.useContext(WindowStartContext);
}

export function useInstitutionDirectoryRow(): InstitutionDirectoryEntry | undefined {
  return React.useContext(DirectoryContext);
}
