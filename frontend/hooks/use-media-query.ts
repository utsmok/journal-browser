"use client";

import * as React from "react";

/**
 * SSR-safe media query. Returns null until the client has measured the
 * viewport, so callers can render the server markup unchanged on the first
 * client render (no hydration mismatch, no layout shift) and mount only the
 * matching variant once the query is known.
 */
export function useMediaQuery(query: string): boolean | null {
  const [matches, setMatches] = React.useState<boolean | null>(null);
  React.useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}
