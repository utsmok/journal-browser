"use client";

import { useQuery } from "@tanstack/react-query";
import { Building2, Check, ExternalLink, Landmark } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { FunderPicker } from "@/components/funder/funder-picker";
import { useInstitution } from "@/hooks/use-institution";
import { apiGet, type FunderSearchResponse } from "@/lib/api";
import type { FunderPrefs } from "@/lib/funder-prefs";
import { cn } from "@/lib/utils";

/** Step 2: binary funder choice + dynamic institution-top quick-select chips
 * + full Jisc OPF FunderPicker synced with localStorage. */
export function StepFunder({
  hasFunder,
  funder,
  instLabel,
  onSetHasFunder,
  onSelectFunder,
}: {
  hasFunder: boolean;
  funder: FunderPrefs;
  instLabel: string;
  onSetHasFunder: (yes: boolean) => void;
  onSelectFunder: (funder: FunderPrefs) => void;
}) {
  const t = useTranslations("guide");
  const inst = useInstitution();

  // Pull top institution-cited funders dynamically when "Yes" is active.
  const topFunders = useQuery({
    queryKey: ["guide-top-funders", inst],
    queryFn: () => apiGet<FunderSearchResponse>(`/${inst}/funders`, { limit: 8 }),
    enabled: Boolean(inst) && hasFunder,
    staleTime: 5 * 60_000,
  });

  const choices = [
    {
      value: true,
      Icon: Landmark,
      title: t("funder.yesTitle"),
      desc: t("funder.yesDesc"),
    },
    {
      value: false,
      Icon: Building2,
      title: t("funder.noTitle"),
      desc: t("funder.noDesc", { institution: instLabel }),
    },
  ] as const;

  return (
    <div className="guide-step-enter space-y-5">
      <div>
        <h2 className="text-xl font-bold tracking-tight">{t("funder.heading")}</h2>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">{t("funder.description")}</p>
      </div>

      {/* Binary choice cards */}
      <div role="radiogroup" aria-label={t("funder.heading")} className="grid gap-3 sm:grid-cols-2">
        {choices.map(({ value, Icon, title, desc }) => {
          const selected = hasFunder === value;
          return (
            <button
              key={String(value)}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onSetHasFunder(value)}
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

      {/* Funder picker & quick-select chips when funded */}
      {hasFunder && (
        <div className="guide-step-enter space-y-4 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--muted)]/50 p-4">
          {topFunders.data && topFunders.data.items.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                {t("funder.quickSelectHeading", { institution: instLabel })}
              </p>
              <div className="flex flex-wrap gap-2">
                {topFunders.data.items.map((item) => {
                  const name = item.name ?? `Funder ${item.id}`;
                  const active = funder?.id === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      aria-pressed={active}
                      onClick={() => onSelectFunder(active ? null : { id: item.id, name })}
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-[var(--radius)] border px-2.5 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2",
                        active
                          ? "border-[var(--brand-tint-border)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                          : "border-[var(--border)] bg-[var(--card)] text-[var(--foreground)] hover:bg-[var(--muted)]",
                      )}
                    >
                      {active && <Check aria-hidden className="size-3" />}
                      <span className="max-w-[220px] truncate">{name}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
              {t("funder.searchHeading")}
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <FunderPicker />
              {funder && inst && (
                <Link
                  href={`/${inst}/funders/${funder.id}`}
                  className="inline-flex items-center gap-1 text-xs font-medium text-[var(--primary-text)] underline-offset-4 hover:underline"
                >
                  {t("funder.viewPolicy")}
                  <ExternalLink aria-hidden className="size-3" />
                </Link>
              )}
            </div>
            <p className="mt-2 text-xs text-[var(--muted-foreground)]">
              {funder
                ? t("funder.selectedNotice", { name: funder.name })
                : t("funder.selectPrompt")}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
