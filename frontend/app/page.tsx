"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

type Institution = {
  code: string;
  name: string;
  short_name: string | null;
  data_window_start: number;
  data_window_end: number | null;
};

function coverageLabel(start: number, end: number | null) {
  if (end === null) return `Coverage: ${start} – present`;
  if (end === start) return `Coverage: ${start}`;
  return `Coverage: ${start} – ${end}`;
}

/** Landing: one card per hosted institution; straight redirect when solo. */
export default function LandingPage() {
  const router = useRouter();
  const [institutions, setInstitutions] = React.useState<Institution[] | null>(null);
  const [error, setError] = React.useState(false);

  const load = React.useCallback(() => {
    setError(false);
    setInstitutions(null);
    fetch("/api/v1/institutions", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((list: Institution[]) => {
        setInstitutions(list);
        if (list.length === 1) router.replace(`/${list[0].code}`);
      })
      .catch(() => setError(true));
  }, [router]);

  React.useEffect(() => {
    load();
  }, [load]);

  if (error) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 text-center">
        <h1 className="font-heading text-2xl font-bold">Journal Browser</h1>
        <p className="mt-4 text-[var(--muted-foreground)]">
          The institution list is unavailable. Check that the backend is running.
        </p>
        <button type="button" onClick={load} className={buttonVariants({ className: "mt-6" })}>
          Retry
        </button>
      </div>
    );
  }

  if (!institutions) {
    return (
      <div
        className="mx-auto max-w-2xl px-4 py-16"
        aria-busy="true"
        aria-label="Loading institutions"
      >
        <h1 className="font-heading text-2xl font-bold">Journal Browser</h1>
        <ul className="mt-8 space-y-3">
          {[0, 1, 2].map((i) => (
            <li
              key={i}
              className="animate-pulse rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] px-5 py-4 shadow-sm"
            >
              <div className="h-5 w-2/3 rounded bg-[var(--muted)]" />
              <div className="mt-3 h-4 w-1/3 rounded bg-[var(--muted)]" />
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl px-4 py-16">
      <h1 className="font-heading text-2xl font-bold">Journal Browser</h1>
      <p className="mt-2 text-[var(--muted-foreground)]">
        Choose your institution to browse its journal deals and publication data.
      </p>
      <ul className="mt-8 space-y-3">
        {institutions.map((inst) => (
          <li key={inst.code}>
            <Link
              href={`/${inst.code}`}
              className="block rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] px-5 py-4 shadow-sm transition hover:shadow-md"
            >
              <span className="flex flex-wrap items-center gap-2">
                <span className="text-lg font-semibold">{inst.name}</span>
                {inst.short_name && (
                  <span className="rounded-full bg-[var(--muted)] px-2 py-0.5 text-xs font-medium text-[var(--muted-foreground)]">
                    {inst.short_name}
                  </span>
                )}
              </span>
              <span className="mt-1 block text-sm text-[var(--muted-foreground)]">
                {coverageLabel(inst.data_window_start, inst.data_window_end)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
