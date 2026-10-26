"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

type Institution = {
  code: string;
  name: string;
  short_name: string | null;
  data_window_start: number;
  data_window_end: number | null;
};

/** Landing: one card per hosted institution; straight redirect when solo. */
export default function LandingPage() {
  const router = useRouter();
  const [institutions, setInstitutions] = React.useState<Institution[] | null>(null);
  const [error, setError] = React.useState(false);

  React.useEffect(() => {
    fetch("/api/v1/institutions", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((list: Institution[]) => {
        setInstitutions(list);
        if (list.length === 1) router.replace(`/${list[0].code}`);
      })
      .catch(() => setError(true));
  }, [router]);

  if (error) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 text-center">
        <h1 className="font-heading text-2xl font-bold">Journal Browser</h1>
        <p className="mt-4 text-[var(--muted-foreground)]">
          The institution list is unavailable. Check that the backend is running.
        </p>
      </div>
    );
  }

  if (!institutions) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 text-center text-[var(--muted-foreground)]">
        Loading institutions…
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
              className="block rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] px-5 py-4 text-lg font-semibold shadow-sm transition hover:shadow-md"
            >
              {inst.name}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
