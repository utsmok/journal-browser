"use client";

import * as React from "react";

/** Selected funder, persisted across visits in localStorage. The label
 * copy keeps the chip renderable without a fetch. */
export type FunderPrefs = { id: number; name: string } | null;

const KEY_ID = "funder_id";
const KEY_LABEL = "funder_label";
const EVENT = "funder-prefs-changed";

function read(): FunderPrefs {
  if (typeof window === "undefined") return null;
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
  const [prefs, setPrefs] = React.useState<FunderPrefs>(read);
  React.useEffect(() => {
    const sync = () => setPrefs(read());
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  return [prefs, write];
}
