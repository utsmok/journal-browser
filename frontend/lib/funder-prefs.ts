"use client";

import * as React from "react";

/** Selected funder, persisted across visits in localStorage. The label
 * copy keeps the chip renderable without a fetch. */
export type FunderPrefs = { id: number; name: string } | null;

const KEY_ID = "funder_id";
const KEY_LABEL = "funder_label";
const EVENT = "funder-prefs-changed";

function read(): FunderPrefs {
  const rawId = window.localStorage.getItem(KEY_ID);
  if (!rawId) return null;
  const id = Number(rawId);
  if (!Number.isFinite(id)) return null;
  return { id, name: window.localStorage.getItem(KEY_LABEL) ?? `Funder ${id}` };
}

function write(prefs: FunderPrefs) {
  if (prefs) {
    window.localStorage.setItem(KEY_ID, String(prefs.id));
    window.localStorage.setItem(KEY_LABEL, prefs.name);
  } else {
    window.localStorage.removeItem(KEY_ID);
    window.localStorage.removeItem(KEY_LABEL);
  }
  window.dispatchEvent(new Event(EVENT));
}

/** React binding over the localStorage prefs; every mounted consumer
 * re-renders on any change (event + storage, so other tabs sync too). */
export function useFunderPrefs(): [FunderPrefs, (p: FunderPrefs) => void] {
  // Hydrate after mount: the server render and the first client render must
  // agree. A stored funder applies once the page is mounted, and the scoped
  // query then loads over the unscoped content the server rendered.
  const [prefs, setPrefs] = React.useState<FunderPrefs>(null);
  React.useEffect(() => {
    const sync = () => setPrefs(read());
    sync();
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  return [prefs, write];
}
