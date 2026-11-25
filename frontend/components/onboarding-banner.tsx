"use client";

import { Compass, Handshake, Search, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import * as React from "react";

const STORAGE_KEY = "ojb_onboarding_v1";

/** Hydration-safe localStorage state for the first-visit onboarding banner. */
export function useOnboardingState() {
  const [ready, setReady] = React.useState(false);
  const [dismissed, setDismissed] = React.useState(true);

  React.useEffect(() => {
    try {
      setDismissed(window.localStorage.getItem(STORAGE_KEY) === "dismissed");
    } catch {
      setDismissed(false);
    }
    setReady(true);
  }, []);

  const dismiss = React.useCallback(() => {
    setDismissed(true);
    try {
      window.localStorage.setItem(STORAGE_KEY, "dismissed");
    } catch {
      // Storage disabled — session-only dismissal still works.
    }
  }, []);

  const reopen = React.useCallback(() => {
    setDismissed(false);
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Ignore storage errors.
    }
  }, []);

  return { ready, visible: ready && !dismissed, dismissed: ready && dismissed, dismiss, reopen };
}

/**
 * Dismissible first-time visitor quick-start card shown above the journal
 * directory when unfiltered. Introduces the three main workflows cleanly.
 */
export function OnboardingBanner({
  inst,
  instShort,
  onTryBrowse,
  onTryGuided,
  onDismiss,
}: {
  inst: string;
  instShort: string;
  onTryBrowse: () => void;
  onTryGuided: () => void;
  onDismiss: () => void;
}) {
  const t = useTranslations("home");

  return (
    <section
      aria-label={t("onboarding.ariaLabel")}
      className="relative rounded-[var(--radius)] border border-[var(--brand-tint-border)] bg-[var(--card)] p-4 shadow-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <Compass aria-hidden className="size-4 shrink-0 text-[var(--primary-text)]" />
          <p className="text-sm font-semibold text-[var(--foreground)]">
            {t("onboarding.title", { short: instShort })}
          </p>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label={t("onboarding.dismiss")}
          title={t("onboarding.dismiss")}
          className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1 rounded-md px-2 text-xs font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] sm:min-h-0 sm:min-w-0 sm:py-1"
        >
          <span className="hidden sm:inline">{t("onboarding.dismissShort")}</span>
          <X aria-hidden className="size-3.5" />
        </button>
      </div>
      <div className="mt-3 grid gap-2.5 sm:grid-cols-3">
        <button
          type="button"
          onClick={onTryBrowse}
          className="group rounded-lg border border-[var(--border)] bg-[var(--background)] p-3 text-left transition-colors hover:border-[var(--primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
        >
          <span className="flex items-center gap-1.5 text-xs font-semibold text-[var(--foreground)] group-hover:text-[var(--primary-text)]">
            <Search aria-hidden className="size-3.5 shrink-0" />
            {t("onboarding.step1Title")}
          </span>
          <span className="mt-1 block text-xs leading-relaxed text-[var(--muted-foreground)]">
            {t("onboarding.step1Body")}
          </span>
        </button>

        <button
          type="button"
          onClick={onTryGuided}
          className="group rounded-lg border border-[var(--border)] bg-[var(--background)] p-3 text-left transition-colors hover:border-[var(--primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
        >
          <span className="flex items-center gap-1.5 text-xs font-semibold text-[var(--foreground)] group-hover:text-[var(--primary-text)]">
            <Sparkles aria-hidden className="size-3.5 shrink-0" />
            {t("onboarding.step2Title")}
          </span>
          <span className="mt-1 block text-xs leading-relaxed text-[var(--muted-foreground)]">
            {t("onboarding.step2Body")}
          </span>
        </button>

        <div className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-3">
          <span className="flex items-center gap-1.5 text-xs font-semibold text-[var(--foreground)]">
            <Handshake aria-hidden className="size-3.5 shrink-0" />
            {t("onboarding.step3Title")}
          </span>
          <span className="mt-1 block text-xs leading-relaxed text-[var(--muted-foreground)]">
            {t("onboarding.step3Body")}{" "}
            <Link
              href={`/${inst}/deals`}
              className="font-medium text-[var(--primary-text)] underline-offset-2 hover:underline"
            >
              {t("onboarding.step3Deals")}
            </Link>
            {" · "}
            <Link
              href={`/${inst}/funders`}
              className="font-medium text-[var(--primary-text)] underline-offset-2 hover:underline"
            >
              {t("onboarding.step3Funders")}
            </Link>
          </span>
        </div>
      </div>
    </section>
  );
}
