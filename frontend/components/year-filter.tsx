"use client";

import { Calendar } from "lucide-react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { effectiveYearRange, useYearBounds, useYearRange } from "@/hooks/use-year-filter";
import { cn } from "@/lib/utils";

const LAST5_SPAN = 5;

/**
 * Compact publication-year control for the site header: preset menu
 * (all years / last 5 years / custom range) with two year selects for the
 * custom case. Hidden on global pages (no institution scope) and before
 * mount, so server and client render the same thing.
 */
export function YearFilterControl() {
  const t = useTranslations("common");
  const pathname = usePathname() ?? "/";
  const { inst, range, setRange } = useYearRange();
  const { start, end } = useYearBounds();
  const [mounted, setMounted] = React.useState(false);
  const [customOpen, setCustomOpen] = React.useState(false);
  React.useEffect(() => setMounted(true), []);
  if (!inst || !mounted) return null;

  const yearScoped =
    !pathname.startsWith(`/${inst}/deals`) &&
    !pathname.startsWith(`/${inst}/about`) &&
    !pathname.startsWith(`/${inst}/guide`);

  const active = effectiveYearRange(range, { start, end });
  const last5From = Math.max(start ?? 1900, (end ?? new Date().getFullYear()) - (LAST5_SPAN - 1));
  const preset = customOpen
    ? "custom"
    : !active
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
    "rounded bg-transparent px-1 py-0.5 text-xs font-medium text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70 [&>option]:bg-[var(--card)] [&>option]:text-[var(--foreground)]";

  const setCustom = (from: number, to: number) => {
    if (from > to) [from, to] = [to, from];
    if (start !== undefined && end !== undefined && from <= start && to >= end) {
      setRange(null);
      return;
    }
    setRange({ from, to });
  };

  const displayFrom = active?.from ?? fromYear;
  const displayTo = active?.to ?? toYear;

  return (
    <div
      className={cn(
        "flex items-center gap-1 rounded-[var(--radius)] border px-2 py-1 transition-colors",
        active && yearScoped
          ? "border-[var(--primary)]/80 bg-white/15"
          : "border-white/25 bg-white/10",
        !yearScoped && "opacity-55",
      )}
      aria-label={t("yearFilter.groupLabel")}
      role="group"
      title={yearScoped ? t("yearFilter.presetHint") : t("yearFilter.inactivePageHint")}
    >
      <Calendar aria-hidden className="size-3.5 shrink-0 text-white/80" />
      <span className="hidden text-xs text-white/75 xl:inline">{t("yearFilter.shortLabel")}</span>
      <select
        aria-label={t("yearFilter.presetLabel")}
        title={t("yearFilter.presetHint")}
        className={selectClass}
        value={preset}
        onChange={(event) => {
          const v = event.target.value;
          if (v === "all") {
            setCustomOpen(false);
            setRange(null);
          } else if (v === "last5") {
            setCustomOpen(false);
            setRange({ from: last5From, to: end });
          } else {
            // Open custom year selectors without writing a redundant full-window
            // query to storage until the user actually narrows a bound.
            setCustomOpen(true);
          }
        }}
      >
        <option value="all">{t("yearFilter.allYears")}</option>
        <option value="last5">{t("yearFilter.last5Years")}</option>
        <option value="custom">{t("yearFilter.customRange")}</option>
      </select>
      {preset === "custom" && (
        <>
          <select
            aria-label={t("yearFilter.fromYear")}
            className={selectClass}
            value={displayFrom}
            onChange={(event) => setCustom(Number(event.target.value), displayTo)}
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
            value={displayTo}
            onChange={(event) => setCustom(displayFrom, Number(event.target.value))}
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
