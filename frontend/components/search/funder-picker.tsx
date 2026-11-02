"use client";

import { Search, X } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { useInstitution } from "@/hooks/use-institution";
import { useFunders } from "@/hooks/use-api";
import { useFunderPrefs } from "@/lib/funder-prefs";

/** Debounced funder picker: search the Jisc OPF canon, click a row to
 * select it (persisted in localStorage), or open its detail page. */
export function FunderPicker() {
  const inst = useInstitution();
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
      <span className="inline-flex h-10 items-center gap-1.5 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] px-2.5 text-sm">
        <span className="max-w-[220px] truncate" title={`Funder fit shown for ${funder.name}`}>
          Funder: {funder.name}
        </span>
        <button
          type="button"
          aria-label={`Clear funder ${funder.name}`}
          className="rounded p-0.5 hover:bg-[var(--muted)]"
          onClick={() => setFunder(null)}
        >
          <X aria-hidden className="size-4" />
        </button>
      </span>
    );
  }

  return (
    <div ref={rootRef} className="relative">
      <div className="relative">
        <input
          type="search"
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          placeholder="Funder…"
          aria-label="Select your funder to see policy fit"
          className="h-10 w-40 rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] pl-7 pr-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 min-[560px]:w-56"
        />
        <Search
          aria-hidden
          className="pointer-events-none absolute left-2 top-2.5 size-4 opacity-50"
        />
      </div>
      {open && debounced.trim().length >= 2 && (
        <ul
          role="listbox"
          aria-label="Funder results"
          className="absolute z-30 mt-1 max-h-72 w-72 overflow-y-auto rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-1 text-sm shadow-lg"
        >
          {funders.isPending && <li className="px-2 py-1.5 opacity-60">Searching…</li>}
          {funders.data?.items.length === 0 && (
            <li className="px-2 py-1.5 opacity-60">No funder matches “{debounced}”</li>
          )}
          {funders.data?.items.map((f) => (
            <li key={f.id} className="flex items-center gap-1 rounded px-1 hover:bg-[var(--muted)]">
              <button
                type="button"
                className="min-w-0 flex-1 py-1.5 text-left"
                onClick={() => {
                  setFunder({ id: f.id, name: f.name ?? `Funder ${f.id}` });
                  setOpen(false);
                  setInput("");
                }}
              >
                <span className="block truncate font-medium">{f.name}</span>
                <span className="text-xs opacity-70">
                  {(f.country ?? "").toUpperCase()}
                  {f.policy_structured ? "" : " · text-only policy"}
                </span>
              </button>
              <span
                className="shrink-0 rounded-full bg-[var(--muted)] px-1.5 py-0.5 text-xs"
                title={`${f.n_ut_works} works from this institution credit this funder`}
              >
                {f.n_ut_works}
              </span>
              <Link
                href={`/${inst}/funders/${f.id}`}
                className="shrink-0 px-1.5 py-1 text-xs underline decoration-dotted"
                title={`Open funder page for ${f.name}`}
              >
                view
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
