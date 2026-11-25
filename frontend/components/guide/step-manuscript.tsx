"use client";

import { CheckCircle2, ShieldCheck, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export const MIN_MANUSCRIPT_CHARS = 15;

const EXAMPLE_KEYS = ["microfluidics", "membranes", "responsibleAi"] as const;

export function combinedManuscriptLength(title: string, abstract: string): number {
  return `${title.trim()} ${abstract.trim()}`.trim().length;
}

/** Step 1: manuscript title, abstract/summary, one-click realistic examples,
 * and a clear local-embedding privacy commitment. */
export function StepManuscript({
  title,
  abstract,
  onChangeTitle,
  onChangeAbstract,
  onSelectExample,
}: {
  title: string;
  abstract: string;
  onChangeTitle: (value: string) => void;
  onChangeAbstract: (value: string) => void;
  onSelectExample: (title: string, abstract: string) => void;
}) {
  const t = useTranslations("guide");
  const combinedLen = combinedManuscriptLength(title, abstract);
  const ready = combinedLen >= MIN_MANUSCRIPT_CHARS;
  const remaining = Math.max(0, MIN_MANUSCRIPT_CHARS - combinedLen);

  return (
    <div className="guide-step-enter space-y-5">
      <div>
        <h2 className="text-xl font-bold tracking-tight">{t("manuscript.heading")}</h2>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">{t("manuscript.description")}</p>
      </div>

      {/* One-click demo manuscript examples */}
      <div>
        <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
          <Sparkles aria-hidden className="size-3.5 text-[var(--primary-text)]" />
          {t("manuscript.examplesHeading")}
        </p>
        <div className="flex flex-wrap gap-2">
          {EXAMPLE_KEYS.map((key) => {
            const exTitle = t(`manuscript.examples.${key}.title`);
            const exAbstract = t(`manuscript.examples.${key}.abstract`);
            const active = title.trim() === exTitle && abstract.trim() === exAbstract;
            return (
              <button
                key={key}
                type="button"
                onClick={() => onSelectExample(exTitle, exAbstract)}
                className={cn(
                  "min-h-11 rounded-[var(--radius)] border px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 min-[1024px]:min-h-0",
                  active
                    ? "border-[var(--brand-tint-border)] bg-[var(--brand-tint-bg)] text-[var(--foreground)]"
                    : "border-[var(--border)] bg-[var(--card)] text-[var(--foreground)] hover:bg-[var(--muted)]",
                )}
              >
                {t(`manuscript.examples.${key}.chip`)}
              </button>
            );
          })}
        </div>
      </div>

      {/* Manuscript inputs */}
      <div className="space-y-4">
        <div>
          <label htmlFor="guide-title" className="mb-1.5 block text-sm font-medium">
            {t("manuscript.titleLabel")}
          </label>
          <Input
            id="guide-title"
            value={title}
            maxLength={400}
            onChange={(e) => onChangeTitle(e.target.value)}
            placeholder={t("manuscript.titlePlaceholder")}
          />
        </div>

        <div>
          <div className="mb-1.5 flex items-baseline justify-between gap-2">
            <label htmlFor="guide-abstract" className="block text-sm font-medium">
              {t("manuscript.abstractLabel")}
            </label>
            <span
              aria-live="polite"
              className={cn(
                "inline-flex items-center gap-1 text-xs font-medium tabular-nums",
                ready ? "text-emerald-700 dark:text-emerald-400" : "text-[var(--muted-foreground)]",
              )}
            >
              {ready && <CheckCircle2 aria-hidden className="size-3.5" />}
              {ready
                ? t("manuscript.charCountReady", { count: combinedLen })
                : t("manuscript.charCountNeeded", { remaining })}
            </span>
          </div>
          <textarea
            id="guide-abstract"
            rows={5}
            maxLength={6000}
            value={abstract}
            onChange={(e) => onChangeAbstract(e.target.value)}
            placeholder={t("manuscript.abstractPlaceholder")}
            className="w-full rounded-[var(--radius)] border border-[var(--input)] bg-[var(--card)] px-3 py-2.5 text-base leading-relaxed placeholder:text-[var(--muted-foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] min-[560px]:text-sm"
          />
        </div>
      </div>

      {/* Privacy shield callout */}
      <div className="flex items-start gap-3 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)] px-4 py-3 text-xs">
        <ShieldCheck
          aria-hidden
          className="mt-0.5 size-4 shrink-0 text-emerald-700 dark:text-emerald-400"
        />
        <div>
          <p className="font-semibold text-[var(--foreground)]">{t("manuscript.privacyTitle")}</p>
          <p className="mt-0.5 text-[var(--muted-foreground)]">{t("manuscript.privacyBody")}</p>
        </div>
      </div>
    </div>
  );
}
