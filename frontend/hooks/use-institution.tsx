"use client";

import * as React from "react";

/**
 * Institution path scope for /{code}/... pages. Provided by app/[inst]/layout;
 * empty string for global surfaces (landing chooser, admin).
 */
const InstitutionContext = React.createContext<string>("");

export function InstitutionProvider({
  code,
  children,
}: {
  code: string;
  children: React.ReactNode;
}) {
  return (
    <InstitutionContext.Provider value={code}>
      {children}
    </InstitutionContext.Provider>
  );
}

export function useInstitution(): string {
  return React.useContext(InstitutionContext);
}

/** Prefix an internal path with the current institution segment. */
export function instHref(path: string): string {
  const inst = React.useContext(InstitutionContext);
  return `/${inst}${path}`;
}
