"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { Button, buttonVariants } from "@/components/ui/button";

/**
 * Render-error boundary for the whole app. Fetch errors are handled
 * per-query; this catches what falls through (render-time exceptions) with
 * a token-styled card instead of Next's unbranded fallback.
 */
export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useTranslations("common");
  console.error(error);
  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-24 text-center">
      <div className="mx-auto max-w-md rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-8 text-left">
        <h1 className="text-2xl font-bold">{t("errorPage.title")}</h1>
        <p className="mt-2 text-sm text-[var(--muted-foreground)]">{t("errorPage.intro")}</p>
        <div className="mt-6 flex flex-wrap justify-end gap-3">
          <Button size="sm" onClick={reset}>
            {t("errorPage.retry")}
          </Button>
          <Link href="/" className={buttonVariants({ variant: "outline", size: "sm" })}>
            {t("errorPage.home")}
          </Link>
        </div>
      </div>
    </div>
  );
}
