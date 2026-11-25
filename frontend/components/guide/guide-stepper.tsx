"use client";

import { Check } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

export type WizardStep = 1 | 2 | 3 | 4;

const STEP_KEYS: Record<WizardStep, string> = {
  1: "steps.manuscript",
  2: "steps.funder",
  3: "steps.budget",
  4: "steps.preferences",
};

const STEPS: WizardStep[] = [1, 2, 3, 4];

/** Four-step horizontal stepper with animated progress track. Completed
 * steps stay clickable so authors can jump back without losing state. */
export function GuideStepper({
  current,
  maxReached,
  canAdvanceFrom1,
  onSelectStep,
}: {
  current: WizardStep;
  maxReached: WizardStep;
  canAdvanceFrom1: boolean;
  onSelectStep: (step: WizardStep) => void;
}) {
  const t = useTranslations("guide");
  const progressPct = ((current - 1) / (STEPS.length - 1)) * 100;

  return (
    <nav aria-label={t("steps.ariaLabel")} className="mb-6">
      <div className="mb-2 flex items-center justify-between text-xs font-medium text-[var(--muted-foreground)] sm:hidden">
        <span>{t("steps.counter", { current, total: STEPS.length })}</span>
        <span className="font-semibold text-[var(--foreground)]">{t(STEP_KEYS[current])}</span>
      </div>

      {/* Smooth progress track */}
      <div className="relative mb-3 h-1.5 w-full overflow-hidden rounded-full bg-[var(--muted)]">
        <div
          className="guide-bar-fill h-full rounded-full bg-[var(--primary)]"
          style={{ width: `${Math.max(8, progressPct)}%` }}
        />
      </div>

      <ol className="grid grid-cols-4 gap-2">
        {STEPS.map((step) => {
          const isCurrent = step === current;
          const isDone = step < current;
          const clickable =
            step < current || (step <= maxReached && (step === 1 || canAdvanceFrom1));
          return (
            <li key={step}>
              <button
                type="button"
                disabled={!clickable && !isCurrent}
                aria-current={isCurrent ? "step" : undefined}
                onClick={() => {
                  if (clickable && !isCurrent) onSelectStep(step);
                }}
                className={cn(
                  "flex min-h-11 w-full items-center gap-2 rounded-[var(--radius)] border px-2.5 py-2 text-left text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 sm:px-3 sm:text-sm min-[1024px]:min-h-0",
                  isCurrent
                    ? "border-[var(--brand-tint-border)] bg-[var(--brand-tint-bg)] text-[var(--foreground)]"
                    : isDone
                      ? "border-[var(--border)] bg-[var(--card)] text-[var(--foreground)] hover:bg-[var(--muted)]"
                      : "border-transparent bg-transparent text-[var(--muted-foreground)] disabled:opacity-60",
                  clickable && !isCurrent && "cursor-pointer",
                )}
              >
                <span
                  className={cn(
                    "flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-bold tabular-nums",
                    isCurrent
                      ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : isDone
                        ? "bg-[var(--secondary)] text-[var(--secondary-foreground)]"
                        : "bg-[var(--muted)] text-[var(--muted-foreground)]",
                  )}
                >
                  {isDone ? <Check aria-hidden className="size-3.5" /> : step}
                </span>
                <span className="hidden truncate sm:inline">{t(STEP_KEYS[step])}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
