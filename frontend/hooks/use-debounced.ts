"use client";

import * as React from "react";

/** Returns `value` only after the input settles, so typing does not fire a
 * request per keystroke. */
export function useDebounced(value: string, delayMs: number) {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
}
