"use client";

import { Award, BookOpen, Building2 } from "lucide-react";
import { useTranslations } from "next-intl";

import type { BudgetMode } from "@/lib/api";
import type { FunderPrefs } from "@/lib/funder-prefs";
import { formatEur } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Step 4: three clean switch cards + compact pre-submit summary. */
export function StepPreferences({
  preferInstitutionHistory,
  preferEstablished,
  includeNonJournals,
  instLabel,
  hasFunder,
  funder,
  budgetMode,
  maxApcEur,
  onToggleHistory,
  onToggleEstablished,
  onToggleNonJournals,
}: {
  preferInstitutionHistory: boolean;
  preferEstablished: boolean;
  includeNonJournals: boolean;
  instLabel: string;
  hasFunder: boolean;
  funder: FunderPrefs;
  budgetMode: BudgetMode;
  maxApcEur: number;
  onToggleHistory: (next: boolean) => void;
  onToggleEstablished: (next: boolean) => void;
  onToggleNonJournals: (next: boolean) => void;
}) {
  const t = useTranslations("guide");

  const toggles = [
    {
      id: "pref-history",
      Icon: Building2,
      title: t("preferences.historyTitle", { institution: instLabel }),
      desc: t("preferences.historyDesc", { institution: instLabel }),
      checked: preferInstitutionHistory,
      onChange: onToggleHistory,
    },
    {
      id: "pref-established",
      Icon: Award,
      title: t("preferences.establishedTitle"),
      desc: t("preferences.establishedDesc"),
      checked: preferEstablished,
      onChange: onToggleEstablished,
    },
    {
      id: "pref-non-journals",
      Icon: BookOpen,
      title: t("preferences.nonJournalsTitle"),
      desc: t("preferences.nonJournalsDesc"),
      checked: includeNonJournals,
      onChange: onToggleNonJournals,
    },
  ] as const;

  const budgetLabel =
    budgetMode === "none"
      ? t("preferences.budgetSummaryNone")
      : budgetMode === "capped"
        ? t("preferences.budgetSummaryCapped", { amount: formatEur(maxApcEur) })
        : budgetMode === "funder_pays"
          ? t("preferences.budgetSummaryFunderPays")
          : t("preferences.budgetSummaryAny");

  const funderLabel = hasFunder && funder ? funder.name : t("preferences.funderSummaryNone");

  return (
    <div className="guide-step-enter space-y-5">
      <div>
        <h2 className="text-xl font-bold tracking-tight">{t("preferences.heading")}</h2>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">
          {t("preferences.description")}
        </p>
      </div>

      <div className="space-y-3">
        {toggles.map(({ id, Icon, title, desc, checked, onChange }) => (
          <button
            key={id}
            id={id}
            type="button"
            role="switch"
            aria-checked={checked}
            onClick={() => onChange(!checked)}
            className={cn(
              "flex w-full items-start gap-3 rounded-[var(--radius)] border p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2",
              checked
                ? "border-[var(--brand-tint-border)] bg-[var(--brand-tint-bg)]"
                : "border-[var(--border)] bg-[var(--card)] hover:bg-[var(--muted)]",
            )}
          >
            <span
              className={cn(
                "mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-[var(--radius)]",
                checked
                  ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                  : "bg-[var(--muted)] text-[var(--muted-foreground)]",
              )}
            >
              <Icon aria-hidden className="size-4" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold text-[var(--foreground)]">{title}</span>
              <span className="mt-0.5 block text-xs leading-relaxed text-[var(--muted-foreground)]">
                {desc}
              </span>
            </span>
            {/* Tactile switch track */}
            <span
              aria-hidden
              className={cn(
                "mt-1 inline-flex h-6 w-11 shrink-0 items-center rounded-full border p-0.5 transition-colors",
                checked
                  ? "border-[var(--primary)] bg-[var(--primary)] justify-end"
                  : "border-[var(--border)] bg-[var(--muted)] justify-start",
              )}
            >
              <span
                className={cn(
                  "size-4 rounded-full",
                  checked ? "bg-[var(--primary-foreground)]" : "bg-[var(--card)]",
                )}
              />
            </span>
          </button>
        ))}
      </div>

      {/* Compact pre-submit criteria preview */}
      <div className="flex flex-wrap items-center gap-2 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)] px-4 py-3 text-xs">
        <span className="font-semibold text-[var(--foreground)]">
          {t("preferences.readySummary")}:
        </span>
        <span className="rounded-full bg-[var(--card)] px-2.5 py-0.5 font-medium text-[var(--foreground)]">
          {budgetLabel}
        </span>
        <span className="rounded-full bg-[var(--card)] px-2.5 py-0.5 font-medium text-[var(--foreground)]">
          {funderLabel}
        </span>
      </div>
    </div>
  );
}
