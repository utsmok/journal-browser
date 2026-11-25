import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { redirect } from "next/navigation";

import { OjbWordmark } from "@/components/logo";
import { RefreshButton } from "@/components/refresh-button";
import { buttonVariants } from "@/components/ui/button";
import { fetchInstitutions } from "@/lib/server-fetch";

export async function generateMetadata(): Promise<Metadata> {
  return { alternates: { canonical: "/" } };
}

function Hero({ siteName }: { siteName: string }) {
  return (
    <h1 className="font-heading text-2xl font-bold">
      <span className="sr-only">{siteName}</span>
      <OjbWordmark className="mx-auto block h-36 w-auto" />
    </h1>
  );
}

/** Landing: one card per hosted institution; straight redirect when solo. */
export default async function LandingPage() {
  const t = await getTranslations("home");
  const institutions = await fetchInstitutions();
  if (institutions?.length === 1) redirect(`/${institutions[0].code}`);

  if (!institutions) {
    return (
      <div className="mx-auto max-w-2xl px-4 pb-10 pt-6 text-center">
        <Hero siteName={t("landing.siteName")} />
        <p className="mt-4 text-[var(--muted-foreground)]">{t("landing.loadError")}</p>
        <RefreshButton
          label={t("landing.retry")}
          className={buttonVariants({ className: "mt-6" })}
        />
      </div>
    );
  }

  const coverage = (start: number, end: number | null) => {
    if (end === null) return t("landing.coverageToPresent", { start: String(start) });
    if (end === start) return t("landing.coverageSingleYear", { year: String(start) });
    return t("landing.coverageRange", { start: String(start), end: String(end) });
  };

  return (
    <div className="mx-auto max-w-2xl px-4 pb-6 pt-6">
      <Hero siteName={t("landing.siteName")} />
      <p className="mt-3 text-center text-[var(--muted-foreground)]">{t("landing.intro")}</p>
      <div className="mt-6 grid gap-3 sm:grid-cols-3">
        <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-3.5">
          <p className="text-xs font-semibold text-[var(--foreground)]">
            {t("landing.feature1Title")}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-[var(--muted-foreground)]">
            {t("landing.feature1Body")}
          </p>
        </div>
        <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-3.5">
          <p className="text-xs font-semibold text-[var(--foreground)]">
            {t("landing.feature2Title")}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-[var(--muted-foreground)]">
            {t("landing.feature2Body")}
          </p>
        </div>
        <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-3.5">
          <p className="text-xs font-semibold text-[var(--foreground)]">
            {t("landing.feature3Title")}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-[var(--muted-foreground)]">
            {t("landing.feature3Body")}
          </p>
        </div>
      </div>
      <ul className="mt-6 space-y-3">
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
      <p className="mt-8 text-center text-sm text-[var(--muted-foreground)]">
        {t("landing.valueLine")}
      </p>
    </div>
  );
}
