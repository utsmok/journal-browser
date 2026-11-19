"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { OjbWordmark } from "@/components/logo";

type Institution = {
  code: string;
  name: string;
  short_name: string | null;
  data_window_start: number;
  data_window_end: number | null;
};

/** Landing: one card per hosted institution; straight redirect when solo. */
export default function LandingPage() {
  const t = useTranslations("home");
  const router = useRouter();
  const [institutions, setInstitutions] = React.useState<Institution[] | null>(null);
  const [error, setError] = React.useState(false);

  const coverage = (start: number, end: number | null) => {
    if (end === null) return t("landing.coverageToPresent", { start: String(start) });
    if (end === start) return t("landing.coverageSingleYear", { year: String(start) });
    return t("landing.coverageRange", { start: String(start), end: String(end) });
  };

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
      <div className="mx-auto max-w-2xl px-4 pb-10 pt-6 text-center">
        <h1 className="font-heading text-2xl font-bold">
          <span className="sr-only">{t("landing.siteName")}</span>
          <OjbWordmark className="mx-auto block h-36 w-auto" />
        </h1>
        <p className="mt-4 text-[var(--muted-foreground)]">{t("landing.loadError")}</p>
        <button type="button" onClick={load} className={buttonVariants({ className: "mt-6" })}>
          {t("landing.retry")}
        </button>
      </div>
    );
  }

  if (!institutions) {
    return (
      <div
        className="mx-auto max-w-2xl px-4 pb-10 pt-6"
        aria-busy="true"
        aria-label={t("landing.loadingLabel")}
      >
        <h1 className="font-heading text-2xl font-bold">
          <span className="sr-only">{t("landing.siteName")}</span>
          <OjbWordmark className="mx-auto block h-36 w-auto" />
        </h1>
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
    <div className="mx-auto max-w-2xl px-4 pb-10 pt-6">
      <h1 className="font-heading text-2xl font-bold">
        <span className="sr-only">{t("landing.siteName")}</span>
        <OjbWordmark className="mx-auto block h-36 w-auto" />
      </h1>
      <p className="mt-3 text-center text-[var(--muted-foreground)]">{t("landing.intro")}</p>
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
                {coverage(inst.data_window_start, inst.data_window_end)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
