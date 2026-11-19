"use client";

import * as React from "react";
import { useTranslations } from "next-intl";

import { effectiveYearRange, useYearBounds, useYearRange } from "@/hooks/use-year-filter";

const LAST5_SPAN = 5;

/**
 * Compact publication-year control for the site header: preset menu
 * (all years / last 5 years / custom range) with two year selects for the
 * custom case. Hidden on global pages (no institution scope) and before
 * mount, so server and client render the same thing.
 */
export function YearFilterControl() {
  const t = useTranslations("common");
  const { inst, range, setRange } = useYearRange();
  const { start, end } = useYearBounds();
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);
  if (!inst || !mounted) return null;

  const active = effectiveYearRange(range, { start, end });
  const last5From = Math.max(start ?? 1900, (end ?? new Date().getFullYear()) - (LAST5_SPAN - 1));
  const preset = !active
    ? "all"
    : active.to === end && active.from === last5From
      ? "last5"
      : "custom";

  // Selectable years span the data window; before it resolves, fall back to
  // a wide list so the control still works.
  const fromYear = start ?? 1900;
  const toYear = end ?? new Date().getFullYear();
  const years: number[] = [];
  for (let y = toYear; y >= fromYear; y--) years.push(y);

  const selectClass =
    "rounded-[var(--radius)] border border-white/25 bg-white/10 px-1.5 py-1 text-xs text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70 [&>option]:bg-[var(--card)] [&>option]:text-[var(--foreground)]";

  const setCustom = (from: number, to: number) => {
    if (from > to) [from, to] = [to, from];
    setRange({ from, to });
  };

  return (
    <div className="flex items-center gap-1" aria-label={t("yearFilter.groupLabel")} role="group">
      <select
        aria-label={t("yearFilter.presetLabel")}
        title={t("yearFilter.presetHint")}
        className={selectClass}
        value={preset}
        onChange={(event) => {
          const v = event.target.value;
          if (v === "all") setRange(null);
          else if (v === "last5") setRange({ from: last5From, to: end });
          // Seed the custom selects with the full window; picking a
          // narrower span keeps the menu on "Custom range…".
          else setRange({ from: fromYear, to: toYear });
        }}
      >
        <option value="all">{t("yearFilter.allYears")}</option>
        <option value="last5">{t("yearFilter.last5Years")}</option>
        <option value="custom">{t("yearFilter.customRange")}</option>
      </select>
      {preset === "custom" && active && (
        <>
          <select
            aria-label={t("yearFilter.fromYear")}
            className={selectClass}
            value={active.from}
            onChange={(event) => setCustom(Number(event.target.value), active.to)}
          >
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
          <span aria-hidden className="text-xs text-white/70">
            –
          </span>
          <select
            aria-label={t("yearFilter.toYear")}
            className={selectClass}
            value={active.to}
            onChange={(event) => setCustom(active.from, Number(event.target.value))}
          >
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </>
      )}
    </div>
  );
}
