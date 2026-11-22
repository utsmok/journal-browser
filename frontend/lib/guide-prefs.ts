"use client";

import * as React from "react";

import type { BudgetMode } from "./api";
import { useFunderPrefs, type FunderPrefs } from "./funder-prefs";

/** Persisted answers for the Guided Journal Finder wizard. Funder choice
 * delegates to `useFunderPrefs()` so search, journal pages, and the wizard
 * stay automatically in sync across tabs. */
export type GuidePrefs = {
  title: string;
  abstract: string;
  hasFunder: boolean;
  budgetMode: BudgetMode;
  maxApcEur: number;
  preferInstitutionHistory: boolean;
  preferEstablished: boolean;
  includeNonJournals: boolean;
};

export const DEFAULT_GUIDE_PREFS: GuidePrefs = {
  title: "",
  abstract: "",
  hasFunder: false,
  budgetMode: "none",
  maxApcEur: 2000,
  preferInstitutionHistory: true,
  preferEstablished: false,
  includeNonJournals: false,
};

const STORAGE_KEY = "ojb_guide_prefs_v1";
const EVENT = "guide-prefs-changed";

const VALID_BUDGET_MODES = new Set<BudgetMode>(["none", "capped", "funder_pays", "any"]);

function parseStored(raw: string | null): GuidePrefs | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<GuidePrefs>;
    if (!parsed || typeof parsed !== "object") return null;
    const budgetMode =
      typeof parsed.budgetMode === "string" &&
      VALID_BUDGET_MODES.has(parsed.budgetMode as BudgetMode)
        ? (parsed.budgetMode as BudgetMode)
        : DEFAULT_GUIDE_PREFS.budgetMode;
    const maxApc =
      typeof parsed.maxApcEur === "number" &&
      Number.isFinite(parsed.maxApcEur) &&
      parsed.maxApcEur >= 0 &&
      parsed.maxApcEur <= 50000
        ? Math.round(parsed.maxApcEur)
        : DEFAULT_GUIDE_PREFS.maxApcEur;
    return {
      title: typeof parsed.title === "string" ? parsed.title : DEFAULT_GUIDE_PREFS.title,
      abstract:
        typeof parsed.abstract === "string" ? parsed.abstract : DEFAULT_GUIDE_PREFS.abstract,
      hasFunder:
        typeof parsed.hasFunder === "boolean" ? parsed.hasFunder : DEFAULT_GUIDE_PREFS.hasFunder,
      budgetMode,
      maxApcEur: maxApc,
      preferInstitutionHistory:
        typeof parsed.preferInstitutionHistory === "boolean"
          ? parsed.preferInstitutionHistory
          : DEFAULT_GUIDE_PREFS.preferInstitutionHistory,
      preferEstablished:
        typeof parsed.preferEstablished === "boolean"
          ? parsed.preferEstablished
          : DEFAULT_GUIDE_PREFS.preferEstablished,
      includeNonJournals:
        typeof parsed.includeNonJournals === "boolean"
          ? parsed.includeNonJournals
          : DEFAULT_GUIDE_PREFS.includeNonJournals,
    };
  } catch {
    return null;
  }
}

function readPrefs(): GuidePrefs | null {
  if (typeof window === "undefined") return null;
  try {
    return parseStored(window.localStorage?.getItem?.(STORAGE_KEY) ?? null);
  } catch {
    return null;
  }
}

function writePrefs(next: GuidePrefs) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    window.dispatchEvent(new Event(EVENT));
  } catch {
    // Private-browsing / storage quota failures stay silent.
  }
}

function clearPrefs() {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
    window.dispatchEvent(new Event(EVENT));
  } catch {
    // Ignore storage errors.
  }
}

export function hasCustomGuidePrefs(prefs: GuidePrefs, funder: FunderPrefs): boolean {
  return (
    prefs.title.trim().length > 0 ||
    prefs.abstract.trim().length > 0 ||
    prefs.hasFunder ||
    funder !== null ||
    prefs.budgetMode !== DEFAULT_GUIDE_PREFS.budgetMode ||
    prefs.maxApcEur !== DEFAULT_GUIDE_PREFS.maxApcEur ||
    prefs.preferInstitutionHistory !== DEFAULT_GUIDE_PREFS.preferInstitutionHistory ||
    prefs.preferEstablished !== DEFAULT_GUIDE_PREFS.preferEstablished ||
    prefs.includeNonJournals !== DEFAULT_GUIDE_PREFS.includeNonJournals
  );
}

/** React state synced with localStorage and the shared funder preference.
 * Hydrates in useEffect so SSR and initial client markup never diverge. */
export function useGuidePrefs() {
  const [funder, setFunderRaw] = useFunderPrefs();
  const [prefs, setPrefs] = React.useState<GuidePrefs>(DEFAULT_GUIDE_PREFS);
  const [hydrated, setHydrated] = React.useState(false);

  React.useEffect(() => {
    const sync = () => {
      const stored = readPrefs();
      if (stored) {
        setPrefs(stored);
      } else {
        setPrefs(DEFAULT_GUIDE_PREFS);
      }
      setHydrated(true);
    };
    sync();
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  // If a funder is already chosen elsewhere in OJB, reflect it in the wizard.
  React.useEffect(() => {
    if (!hydrated || !funder) return;
    setPrefs((prev) => {
      if (prev.hasFunder) return prev;
      const next = { ...prev, hasFunder: true };
      writePrefs(next);
      return next;
    });
  }, [funder, hydrated]);

  const updatePrefs = React.useCallback((patch: Partial<GuidePrefs>) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch };
      writePrefs(next);
      return next;
    });
  }, []);

  const setFunder = React.useCallback(
    (next: FunderPrefs) => {
      setFunderRaw(next);
      if (next) {
        setPrefs((prev) => {
          const updated = { ...prev, hasFunder: true };
          writePrefs(updated);
          return updated;
        });
      }
    },
    [setFunderRaw],
  );

  const resetPrefs = React.useCallback(() => {
    clearPrefs();
    setPrefs(DEFAULT_GUIDE_PREFS);
    setFunderRaw(null);
  }, [setFunderRaw]);

  return {
    prefs,
    hydrated,
    funder,
    setFunder,
    updatePrefs,
    resetPrefs,
    hasSavedData: hydrated && hasCustomGuidePrefs(prefs, funder),
  };
}
