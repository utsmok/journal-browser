/**
 * Journal shortlist: the journals a reader saved for later, kept in
 * localStorage per institution (the app has no accounts). Storage holds
 * only the ISSN-L, the title at save time and the save date; the shortlist
 * page fetches every other column fresh from the API.
 */

import * as React from "react";

export type ShortlistEntry = { issnL: string; title: string; addedAt: string };

/** One ISSN-L per entry, oldest save first. */
export type ShortlistJournal = { issnL: string; title: string };

const KEY_PREFIX = "jb_shortlist_";
const EVENT = "shortlist-changed";
const EMPTY: ShortlistEntry[] = [];

const ISSN_RE = /^(\d{4})-?(\d{3}[\dX])$/;

/** Canonical `XXXX-XXXX` form of an ISSN typed bare, hyphenated or in lower
 * case; null when the text is not an ISSN. */
export function normalizeIssnL(value: string): string | null {
  const match = ISSN_RE.exec(value.replaceAll(" ", "").toUpperCase());
  return match ? `${match[1]}-${match[2]}` : null;
}

/** Valid entries out of stored JSON: anything else (a hand-edited or older
 * shape) is dropped instead of breaking the page. */
function fromStored(parsed: unknown): ShortlistEntry[] {
  if (!Array.isArray(parsed)) return EMPTY;
  const entries = new Map<string, ShortlistEntry>();
  for (const raw of parsed) {
    if (typeof raw !== "object" || raw === null) continue;
    const { issnL, title, addedAt } = raw as Partial<ShortlistEntry>;
    const canonical = typeof issnL === "string" ? normalizeIssnL(issnL) : null;
    if (!canonical || entries.has(canonical)) continue;
    entries.set(canonical, {
      issnL: canonical,
      title: typeof title === "string" ? title : canonical,
      addedAt: typeof addedAt === "string" ? addedAt : "",
    });
  }
  // Array.prototype.sort is stable, so entries without a date keep their order.
  return [...entries.values()].sort((a, b) => a.addedAt.localeCompare(b.addedAt));
}

function load(inst: string): ShortlistEntry[] {
  try {
    const raw = window.localStorage.getItem(`${KEY_PREFIX}${inst}`);
    return raw ? fromStored(JSON.parse(raw)) : EMPTY;
  } catch {
    // Blocked storage or corrupted JSON: start empty rather than throw.
    return EMPTY;
  }
}

const cache = new Map<string, ShortlistEntry[]>();

function snapshot(inst: string): ShortlistEntry[] {
  let entries = cache.get(inst);
  if (entries === undefined) {
    entries = load(inst);
    cache.set(inst, entries);
  }
  return entries;
}

function subscribe(listener: () => void): () => void {
  // The storage event fires in the other tabs of this origin only, so it
  // is exactly the cross-tab sync; this tab gets the custom event.
  const onStorage = (event: StorageEvent) => {
    // A null key means the other tab cleared the whole storage.
    if (event.key === null) cache.clear();
    else if (event.key.startsWith(KEY_PREFIX)) {
      cache.delete(event.key.slice(KEY_PREFIX.length));
    } else return;
    listener();
  };
  window.addEventListener(EVENT, listener);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(EVENT, listener);
    window.removeEventListener("storage", onStorage);
  };
}

function commit(inst: string, entries: ShortlistEntry[]): void {
  cache.set(inst, entries);
  try {
    window.localStorage.setItem(`${KEY_PREFIX}${inst}`, JSON.stringify(entries));
  } catch {
    // Storage is blocked or full: the list lives on for this page view.
  }
  window.dispatchEvent(new Event(EVENT));
}

/** The institution's saved journals, oldest save first. Reads an empty list
 * on the server and during hydration, so the first client paint matches. */
export function useShortlist(inst: string): ShortlistEntry[] {
  return React.useSyncExternalStore(
    subscribe,
    () => snapshot(inst),
    () => EMPTY,
  );
}

export function addJournal(inst: string, issnL: string, title: string): void {
  const canonical = normalizeIssnL(issnL);
  const current = snapshot(inst);
  if (canonical === null || current.some((entry) => entry.issnL === canonical)) return;
  commit(inst, [
    ...current,
    { issnL: canonical, title: title.trim() || canonical, addedAt: new Date().toISOString() },
  ]);
}

export function removeJournal(inst: string, issnL: string): void {
  const current = snapshot(inst);
  const next = current.filter((entry) => entry.issnL !== issnL);
  if (next.length !== current.length) commit(inst, next);
}

export function clearShortlist(inst: string): void {
  if (snapshot(inst).length > 0) commit(inst, []);
}

/** Adds the journals of a shared list that are not saved yet; journals
 * already on the shortlist keep their save date. Returns how many were
 * added. */
export function saveJournals(inst: string, journals: ShortlistJournal[]): number {
  const current = snapshot(inst);
  const saved = new Set(current.map((entry) => entry.issnL));
  const addedAt = new Date().toISOString();
  const added: ShortlistEntry[] = [];
  for (const { issnL, title } of journals) {
    const canonical = normalizeIssnL(issnL);
    if (canonical === null || saved.has(canonical)) continue;
    saved.add(canonical);
    added.push({ issnL: canonical, title, addedAt });
  }
  if (added.length > 0) commit(inst, [...current, ...added]);
  return added.length;
}

// ── Share links ────────────────────────────────────────────────────────────

/** Query parameter that carries a shared list: `?j=0034-4257,0376-7388`. */
export const SHARE_PARAM = "j";

/** ISSN-Ls of a share link, canonical and without duplicates; values that
 * are not ISSNs are dropped. */
export function parseShareIssns(raw: string | null | undefined): string[] {
  if (!raw) return [];
  const issnLs: string[] = [];
  for (const part of raw.split(",")) {
    const canonical = normalizeIssnL(part);
    if (canonical && !issnLs.includes(canonical)) issnLs.push(canonical);
  }
  return issnLs;
}

/** Link that opens this list on the institution's shortlist page. ISSN-Ls
 * need no percent-encoding, so the address stays readable. */
export function shareHref(inst: string, issnLs: string[]): string {
  return `/${inst}/shortlist?${SHARE_PARAM}=${issnLs.join(",")}`;
}

// ── CSV export ─────────────────────────────────────────────────────────────

/** Leading characters a spreadsheet evaluates as a formula; the same set
 * as the backend's csv_export.FORMULA_LEADS. */
const FORMULA_LEADS = ["=", "+", "-", "@", "\t", "\r"];

export type CsvValue = string | number | null | undefined;

/** One CSV cell. Text that starts with a formula character gets a leading
 * apostrophe; text with a comma, quote or line break is quoted. Numbers are
 * written as they are. */
export function csvCell(value: CsvValue): string {
  if (value === null || value === undefined) return "";
  const text =
    typeof value === "number"
      ? Number.isFinite(value)
        ? String(value)
        : ""
      : FORMULA_LEADS.some((lead) => value.startsWith(lead))
        ? `'${value}`
        : value;
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

/** CSV text (RFC 4180: comma-separated, CRLF line ends) for a header and rows. */
export function csvText(header: CsvValue[], rows: CsvValue[][]): string {
  return [header, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n");
}

/** Downloads CSV text as a file. The byte-order mark makes Excel read the
 * file as UTF-8. */
export function downloadCsv(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([`\uFEFF${text}`], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/** `shortlist-ut-2026-11-25.csv` */
export function shortlistCsvFilename(inst: string, date = new Date()): string {
  const day = date.toISOString().slice(0, 10);
  return `shortlist-${inst}-${day}.csv`;
}
