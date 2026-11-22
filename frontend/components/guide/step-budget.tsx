"use client";

import { Check, Coins, Compass, Receipt, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { Input } from "@/components/ui/input";
import type { BudgetMode } from "@/lib/api";
import { formatEur } from "@/lib/format";
import { cn } from "@/lib/utils";

const CAP_PRESETS = [1000, 2000, 3500] as const;

/** Step 3: four tactile APC budget radio-cards with preset/custom cap drawer. */
export function StepBudget({
  budgetMode,
  maxApcEur,
  instLabel,
  onChangeBudgetMode,
  onChangeMaxApc,
}: {
  budgetMode: BudgetMode;
  maxApcEur: number;
  instLabel: string;
  onChangeBudgetMode: (mode: BudgetMode) => void;
  onChangeMaxApc: (eur: number) => void;
}) {
  const t = useTranslations("guide");

  const options: {
    mode: BudgetMode;
    Icon: typeof Sparkles;
    title: string;
    desc: string;
  }[] = [
    {
      mode: "none",
      Icon: Sparkles,
      title: t("budget.noneTitle"),
      desc: t("budget.noneDesc", { institution: instLabel }),
    },
    {
      mode: "capped",
      Icon: Coins,
      title: t("budget.cappedTitle"),
      desc: t("budget.cappedDesc"),
    },
    {
      mode: "funder_pays",
      Icon: Receipt,
      title: t("budget.funderPaysTitle"),
      desc: t("budget.funderPaysDesc"),
    },
    {
      mode: "any",
      Icon: Compass,
      title: t("budget.anyTitle"),
      desc: t("budget.anyDesc"),
    },
  ];

  return (
    <div className="guide-step-enter space-y-5">
      <div>
        <h2 className="text-xl font-bold tracking-tight">{t("budget.heading")}</h2>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">
          {t("budget.description", { institution: instLabel })}
        </p>
      </div>

      <div role="radiogroup" aria-label={t("budget.heading")} className="grid gap-3 sm:grid-cols-2">
        {options.map(({ mode, Icon, title, desc }) => {
          const selected = budgetMode === mode;
          return (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onChangeBudgetMode(mode)}
              className={cn(
                "flex items-start gap-3 rounded-[var(--radius)] border p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2",
                selected
                  ? "border-[var(--brand-tint-border)] bg-[var(--brand-tint-bg)]"
                  : "border-[var(--border)] bg-[var(--card)] hover:bg-[var(--muted)]",
              )}
            >
              <span
                className={cn(
                  "mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-[var(--radius)]",
                  selected
                    ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                    : "bg-[var(--muted)] text-[var(--muted-foreground)]",
                )}
              >
                <Icon aria-hidden className="size-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold text-[var(--foreground)]">
                  {title}
                </span>
                <span className="mt-1 block text-xs leading-relaxed text-[var(--muted-foreground)]">
                  {desc}
                </span>
              </span>
              <span
                aria-hidden
                className={cn(
                  "mt-1 flex size-4 shrink-0 items-center justify-center rounded-full border",
                  selected
                    ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                    : "border-[var(--border)]",
                )}
              >
                {selected && <Check className="size-3" />}
              </span>
            </button>
          );
        })}
      </div>

      {budgetMode === "capped" && (
        <div className="guide-step-enter rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)]/50 p-4">
          <label htmlFor="guide-max-apc" className="block text-sm font-medium">
            {t("budget.capLabel")}
          </label>
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            {CAP_PRESETS.map((preset) => {
              const active = maxApcEur === preset;
              return (
                <button
                  key={preset}
                  type="button"
                  aria-pressed={active}
                  onClick={() => onChangeMaxApc(preset)}
                  className={cn(
                    "rounded-[var(--radius)] border px-3 py-1.5 text-xs font-semibold tabular-nums transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2",
                    active
                      ? "border-[var(--brand-tint-border)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "border-[var(--border)] bg-[var(--card)] text-[var(--foreground)] hover:bg-[var(--muted)]",
                  )}
                >
                  €{formatEur(preset)}
                </button>
              );
            })}
            <div className="relative w-36">
              <span
                aria-hidden
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-[var(--muted-foreground)]"
              >
                €
              </span>
              <Input
                id="guide-max-apc"
                type="number"
                min={0}
                max={50000}
                step={100}
                value={maxApcEur}
                onChange={(e) => {
                  const val = Number(e.target.value);
                  if (Number.isFinite(val)) {
                    onChangeMaxApc(Math.max(0, Math.min(50000, Math.round(val))));
                  }
                }}
                className="pl-7 tabular-nums"
              />
            </div>
          </div>
          <p className="mt-2 text-xs text-[var(--muted-foreground)]">{t("budget.capCustomHint")}</p>
        </div>
      )}
    </div>
  );
}
