"use client";

import { Search, X } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

import { useInstitution } from "@/hooks/use-institution";
import { useFunders } from "@/hooks/use-api";
import { countryName } from "@/lib/format";
import { useFunderPrefs } from "@/lib/funder-prefs";
import { cn } from "@/lib/utils";

/** Debounced funder picker: search the Jisc OPF canon, click a row to
 * select it (persisted in localStorage), or open its detail page. */
export function FunderPicker({ fullWidth = false }: { fullWidth?: boolean } = {}) {
  const inst = useInstitution();
  const t = useTranslations("common");
  const [funder, setFunder] = useFunderPrefs();
  const [input, setInput] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const [debounced, setDebounced] = React.useState("");
  const rootRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const t = setTimeout(() => setDebounced(input), 250);
    return () => clearTimeout(t);
  }, [input]);

  // Close on outside click; blur alone would swallow result clicks.
  React.useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const funders = useFunders(debounced, open);

  if (funder) {
    return (
      <div
        className={cn(
          "inline-flex h-9 items-center justify-between gap-1.5 rounded-[var(--radius)] border border-[var(--brand-tint-border)] bg-[var(--brand-tint-bg)] px-2.5 text-xs font-medium text-[var(--primary-text)]",
          fullWidth && "flex w-full",
        )}
      >
        <span
          className={cn("truncate", fullWidth ? "min-w-0 flex-1" : "max-w-[220px]")}
          title={t("funder.selectedTitle", { name: funder.name })}
        >
          {t("funder.selectedLabel", { name: funder.name })}
        </span>
        <button
          type="button"
          aria-label={t("funder.clearLabel", { name: funder.name })}
          className="shrink-0 rounded p-0.5 hover:bg-black/5 dark:hover:bg-white/10"
          onClick={() => setFunder(null)}
        >
          <X aria-hidden className="size-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div ref={rootRef} className={cn("relative", fullWidth && "w-full")}>
      <div className="relative">
        <input
          type="search"
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          placeholder={t("funder.placeholder")}
          aria-label={t("funder.inputLabel")}
          className={cn(
            "h-9 rounded-[var(--radius)] border border-[var(--input)] bg-[var(--background)] pl-7 pr-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2",
            fullWidth ? "w-full" : "w-40 min-[560px]:w-56",
          )}
        />
        <Search
          aria-hidden
          className="pointer-events-none absolute left-2 top-2.5 size-3.5 opacity-50"
        />
      </div>
      {open && debounced.trim().length >= 2 && (
        <ul
          role="listbox"
          aria-label={t("funder.resultsLabel")}
          className={cn(
            "absolute z-30 mt-1 max-h-72 overflow-y-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-1 text-sm shadow-lg",
            fullWidth ? "left-0 right-0 min-w-64" : "w-72",
          )}
        >
          {funders.isPending && <li className="px-2 py-1.5 opacity-60">{t("funder.searching")}</li>}
          {funders.data?.items.length === 0 && (
            <li className="px-2 py-1.5 opacity-60">
              {t("funder.noMatches", { query: debounced })}
            </li>
          )}
          {funders.data?.items.map((f) => (
            <li key={f.id} className="flex items-center gap-1 rounded px-1 hover:bg-[var(--muted)]">
              <button
                type="button"
                className="min-w-0 flex-1 py-1.5 text-left"
                onClick={() => {
                  setFunder({ id: f.id, name: f.name ?? t("funder.fallbackName", { id: f.id }) });
                  setOpen(false);
                  setInput("");
                }}
              >
                <span className="block truncate font-medium">{f.name}</span>
                <span className="text-xs opacity-70">
                  {countryName(f.country) || (f.country ?? "").toUpperCase()}
                  {f.policy_structured ? "" : t("funder.textOnlyPolicy")}
                </span>
              </button>
              <span
                className="shrink-0 rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-xs tabular-nums"
                title={t("funder.worksTitle", { count: f.n_ut_works })}
              >
                {f.n_ut_works}
              </span>
              <Link
                href={`/${inst}/funders/${f.id}`}
                className="inline-flex min-h-11 shrink-0 items-center px-1.5 py-1 text-xs font-medium text-[var(--primary-text)] underline-offset-2 hover:underline min-[1024px]:min-h-0"
                title={t("funder.openPageTitle", {
                  name: f.name ?? t("funder.fallbackName", { id: f.id }),
                })}
              >
                {t("funder.view")}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
