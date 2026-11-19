"use client";

import { CircleCheck, CircleHelp, CircleX } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import type { FunderFitOut } from "@/lib/api";
import type { FunderPrefs } from "@/lib/funder-prefs";

/** Small card in the green-OA area: how the selected funder's policy
 * judges this journal, with the engine's reasons. Text-only funder
 * policies (fit.status null) show the check-manually note. */
export const FIT_TIER = {
  compliant: {
    Icon: CircleCheck,
    color: "text-emerald-700 dark:text-emerald-400",
    labelKey: "funderFit.compliant",
  },
  check: {
    Icon: CircleHelp,
    color: "text-amber-600 dark:text-amber-400",
    labelKey: "funderFit.check",
  },
  no: {
    Icon: CircleX,
    color: "text-red-700 dark:text-red-400",
    labelKey: "funderFit.notCompliant",
  },
} as const;

export function FunderFitCard({
  fit,
  funder,
  inst,
}: {
  fit: FunderFitOut | null;
  funder: NonNullable<FunderPrefs>;
  inst: string;
}) {
  const t = useTranslations("journals");
  const tier = fit?.status ? FIT_TIER[fit.status] : null;
  return (
    <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        {tier && <tier.Icon aria-hidden className={`size-5 ${tier.color}`} />}
        <span className="font-medium">
          {tier
            ? t("funderFit.withStatus", { funderName: funder.name, status: t(tier.labelKey) })
            : t("funderFit.textOnly", { funderName: funder.name })}
        </span>
        <Link
          href={`/${inst}/funders/${funder.id}`}
          className="text-xs underline decoration-dotted underline-offset-2"
        >
          {t("funderFit.viewPolicy")}
        </Link>
      </div>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-[var(--muted-foreground)]">
        {(fit?.reasons ?? [t("funderFit.checkManually")]).map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
    </div>
  );
}
