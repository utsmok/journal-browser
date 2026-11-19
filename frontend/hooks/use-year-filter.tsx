"use client";

import { usePathname } from "next/navigation";
import * as React from "react";

import { useInstitutionsDirectory } from "./use-api";
import { useInstitution } from "./use-institution";
import { useSiteMeta } from "./use-site-meta";

/**
 * Global publication-year lens. One selected {from, to} span per
 * institution, persisted in localStorage and shared through context so
 * every data fetch (and the header control) reads the same value. When the
 * span is unset, {year_from, year_to} are undefined and fetches run over
 * the institution's full data window, exactly as before.
 */

/** Selected publication-year span for one institution; either side may be open. */
export type YearRange = { from?: number; to?: number };

type StoredRanges = Record<string, YearRange>;

const STORAGE_KEY = "jb-year-range";

const YearRangeContext = React.createContext<{
  inst: string;
  range: YearRange | null;
  setRange: (range: YearRange | null) => void;
}>({ inst: "", range: null, setRange: () => {} });

/** Institution scope for stored ranges, resolved like useSiteMeta so the
 * root-level provider and the [inst] pages agree on the storage slot. */
function useYearInst(): string {
  const ctxInst = useInstitution();
  const seg = (usePathname() ?? "/").split("/")[1] ?? "";
  return ctxInst || (seg && seg !== "admin" ? seg : "");
}

export function YearFilterProvider({ children }: { children: React.ReactNode }) {
  const inst = useYearInst();
  const [stored, setStored] = React.useState<StoredRanges>({});

  // Hydrate after mount: server render and the first client render must
  // both show the default ("All years") or the control would flash.
  React.useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const parsed: unknown = JSON.parse(raw);
      if (parsed && typeof parsed === "object") setStored(parsed as StoredRanges);
    } catch {
      // corrupted storage: keep the default (all years)
    }
  }, []);

  const setRange = React.useCallback(
    (range: YearRange | null) => {
      setStored((prev) => {
        const next = { ...prev };
        if (range && (range.from !== undefined || range.to !== undefined)) next[inst] = range;
        else delete next[inst];
        try {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
        } catch {
          // storage unavailable (private mode): the choice lives for the session only
        }
        return next;
      });
    },
    [inst],
  );

  const value = React.useMemo(
    () => ({ inst, range: stored[inst] ?? null, setRange }),
    [inst, stored, setRange],
  );
  return <YearRangeContext.Provider value={value}>{children}</YearRangeContext.Provider>;
}

/** Bounds of the institution's data: window start (freshness → directory)
 * and window end (directory row, else the current year). */
export function useYearBounds(): { start?: number; end?: number } {
  const inst = useYearInst();
  const site = useSiteMeta();
  const row = useInstitutionsDirectory().data?.find((i) => i.code === inst);
  return {
    start: site.windowStart,
    end: row?.data_window_end ?? new Date().getFullYear(),
  };
}

/**
 * The span actually in force: the stored selection clamped into the data
 * window (and the API's 1900–2100 validation range). An empty selection or
 * one that clamps to nothing counts as off. The backend clamps the same
 * way; doing it here too keeps the client-side per-year sums consistent
 * with what the server returns.
 */
export function effectiveYearRange(
  range: YearRange | null,
  bounds?: { start?: number; end?: number },
): { from: number; to: number } | null {
  if (!range) return null;
  const lo = Math.max(1900, bounds?.start ?? 1900);
  const hi = Math.min(2100, bounds?.end ?? 2100);
  if (lo > hi) return null;
  const from = range.from === undefined ? lo : Math.min(Math.max(range.from, lo), hi);
  const to = range.to === undefined ? hi : Math.min(Math.max(range.to, lo), hi);
  if (from > to) return null;
  return { from, to };
}

/** Per-institution year lens: the institution scope the range belongs to,
 * query params for fetches (both undefined when off), the raw stored
 * selection, and its setter. */
export function useYearRange(): {
  inst: string;
  year_from: number | undefined;
  year_to: number | undefined;
  range: YearRange | null;
  setRange: (range: YearRange | null) => void;
} {
  const { inst, range, setRange } = React.useContext(YearRangeContext);
  const bounds = useYearBounds();
  const active = effectiveYearRange(range, bounds);
  return {
    inst,
    year_from: active?.from,
    year_to: active?.to,
    range,
    setRange,
  };
}

/** Query-string fragment for the active range ("?year_from=…" or, to
 * append to an existing query, "&year_from=…"); "" when the lens is off. */
export function yearQuery(
  joiner: string,
  year_from: number | undefined,
  year_to: number | undefined,
): string {
  const params = new URLSearchParams();
  if (year_from !== undefined) params.set("year_from", String(year_from));
  if (year_to !== undefined) params.set("year_to", String(year_to));
  const qs = params.toString();
  return qs ? `${joiner}${qs}` : "";
}
