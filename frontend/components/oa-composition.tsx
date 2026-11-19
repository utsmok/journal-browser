"use client";

import { useTranslations } from "next-intl";

import type { OaTypeCounts } from "@/lib/api";

/** Background colors for the OA composition bar; same hues as the
 * OaTypeBadge lockups (ACCESS_TEXT), as fills. Display names live in the
 * messages (facets.oaType*). */
export const OA_TYPE_BARS: Record<string, { bar: string }> = {
  gold: { bar: "bg-[#f4aa2a] dark:bg-amber-400" },
  diamond: { bar: "bg-[#4fe4f8] dark:bg-cyan-300" },
  generic: { bar: "bg-[#8f7ae5] dark:bg-[#a99af0]" },
  hybrid: { bar: "bg-[#4d84c7] dark:bg-[#82b1e4]" },
  subscription: { bar: "bg-slate-500 dark:bg-slate-400" },
};

const OA_TYPE_ORDER = ["gold", "diamond", "generic", "hybrid", "subscription"] as const;

const OA_TYPE_LABEL_KEYS: Record<string, string> = {
  gold: "facets.oaTypeGold",
  diamond: "facets.oaTypeDiamond",
  generic: "facets.oaTypeGeneric",
  hybrid: "facets.oaTypeHybrid",
  subscription: "facets.oaTypeSubscription",
};

/** Inline stacked journal OA composition. flexGrow splits segments exactly
 * proportionally (same trick as the OaTrend columns); zero segments drop out. */
export function OaCompositionBar({
  counts,
  total,
  className = "h-2.5",
}: {
  counts: OaTypeCounts;
  total: number;
  className?: string;
}) {
  const t = useTranslations("common");
  if (total <= 0) return <span className="text-[var(--muted-foreground)]">—</span>;
  const parts = OA_TYPE_ORDER.map((type) => ({
    type,
    n: counts[type] ?? 0,
  })).filter((p) => p.n > 0);
  return (
    <div
      className={`flex w-full min-w-16 overflow-hidden rounded-full bg-[var(--muted)] ${className}`}
      role="img"
      aria-label={t("composition.barLabel", {
        mix: parts.map((p) => `${t(OA_TYPE_LABEL_KEYS[p.type])} ${p.n}`).join(", "),
      })}
    >
      {parts.map((p) => (
        <div
          key={p.type}
          className={OA_TYPE_BARS[p.type].bar}
          style={{ flexGrow: p.n, flexBasis: 0 }}
          title={t("composition.segmentTitle", {
            label: t(OA_TYPE_LABEL_KEYS[p.type]),
            count: String(p.n),
          })}
        />
      ))}
    </div>
  );
}

/** Label/count legend matching OaCompositionBar's segments. */
export function OaCompositionLegend({ counts }: { counts: OaTypeCounts }) {
  const t = useTranslations("common");
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--muted-foreground)]">
      {OA_TYPE_ORDER.map((type) => (
        <li key={type} className="flex items-center gap-1.5">
          <span
            aria-hidden
            className={`inline-block size-2.5 rounded-full ${OA_TYPE_BARS[type].bar}`}
          />
          {t(OA_TYPE_LABEL_KEYS[type])}
          {counts[type] != null && <span className="tabular-nums">{counts[type]}</span>}
        </li>
      ))}
    </ul>
  );
}
