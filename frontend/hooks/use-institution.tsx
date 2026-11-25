"use client";

import * as React from "react";

/**
 * Institution path scope for /{code}/... pages. Provided by app/[inst]/layout;
 * empty string for global surfaces (landing chooser, admin).
 */
const InstitutionContext = React.createContext<string>("");
/** First statistics year of the scoped institution, read by the server
 * layout, so server and client render the same window-dependent text. */
const WindowStartContext = React.createContext<number | undefined>(undefined);

export function InstitutionProvider({
  code,
  windowStart,
  children,
}: {
  code: string;
  windowStart?: number;
  children: React.ReactNode;
}) {
  return (
    <InstitutionContext.Provider value={code}>
      <WindowStartContext.Provider value={windowStart}>{children}</WindowStartContext.Provider>
    </InstitutionContext.Provider>
  );
}

export function useInstitution(): string {
  return React.useContext(InstitutionContext);
}

export function useInstitutionWindowStart(): number | undefined {
  return React.useContext(WindowStartContext);
}
