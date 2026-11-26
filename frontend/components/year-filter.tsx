"use client";

import { Calendar } from "lucide-react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import { effectiveYearRange, useYearBounds, useYearRange } from "@/hooks/use-year-filter";
import { cn } from "@/lib/utils";

const LAST5_SPAN = 5;

/** State the header control and its phone chip share. Hidden before mount
 * and on pages without a year scope, so server and client render the same
 * thing. */
function useYearScope() {
  const t = useTranslations("common");
  const pathname = usePathname() ?? "/";
  const { inst, range } = useYearRange();
  const { start, end } = useYearBounds();
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);

  const yearScoped =
    !pathname.startsWith(`/${inst}/deals`) &&
    !pathname.startsWith(`/${inst}/about`) &&
    !pathname.startsWith(`/${inst}/guide`) &&
    !pathname.startsWith(`/${inst}/docs`) &&
    !pathname.startsWith(`/${inst}/admin`);
  const active = effectiveYearRange(range, { start, end });
  const last5From = Math.max(start ?? 1900, (end ?? new Date().getFullYear()) - (LAST5_SPAN - 1));
  const isLast5 = active?.to === end && active?.from === last5From;

  return { t, inst, mounted, yearScoped, active, last5From, isLast5 };
}

/**
 * Publication-year control of the site header: preset menu (all years / last
 * 5 years / custom range) with two year selects for the custom case. From
 * the `lg` breakpoint it sits in the header bar; below that it is a full-width
 * row of the menu drawer, and the bar shows `YearFilterChip` instead.
 */
export function YearFilterControl() {
  const { t, inst, mounted, yearScoped, active, last5From, isLast5 } = useYearScope();
  const { setRange } = useYearRange();
  const { start, end } = useYearBounds();
  const [customOpen, setCustomOpen] = React.useState(false);
  if (!inst || !mounted) return null;

  const preset = customOpen ? "custom" : !active ? "all" : isLast5 ? "last5" : "custom";

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
        "flex w-full flex-wrap items-center gap-1 rounded-[var(--radius)] border px-2 py-1 transition-colors lg:w-auto",
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
      <span className="text-xs text-white/75 lg:hidden xl:inline">
        {t("yearFilter.shortLabel")}
      </span>
      <select
        aria-label={t("yearFilter.presetLabel")}
        title={t("yearFilter.presetHint")}
        className={cn(selectClass, "min-w-0 flex-1 lg:flex-none")}
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

/**
 * Phone counterpart of `YearFilterControl`: shows the publication years in
 * force, so a filter that lives in the menu drawer is still visible on the
 * page, and opens that drawer to change it.
 */
export function YearFilterChip({
  onClick,
}: {
  onClick: (event: React.MouseEvent<HTMLElement>) => void;
}) {
  const { t, inst, mounted, yearScoped, active, isLast5 } = useYearScope();
  if (!inst || !mounted || !yearScoped || !active) return null;
  const label = isLast5 ? t("yearFilter.last5Years") : `${active.from}–${active.to}`;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-haspopup="dialog"
      aria-label={`${t("yearFilter.groupLabel")}: ${label}`}
      title={t("yearFilter.presetHint")}
      className="inline-flex h-11 max-w-44 items-center gap-1.5 rounded-[var(--radius)] border border-[var(--primary)]/80 bg-white/15 px-2.5 text-sm font-medium text-white hover:bg-white/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70 lg:hidden"
    >
      <Calendar aria-hidden className="size-4 shrink-0 text-white/80" />
      <span className="truncate">{label}</span>
    </button>
  );
}
