import type { OaTypeCounts } from "@/lib/api";

/** Background colors for the OA composition bar; same hues as the
 * OaTypeBadge lockups (ACCESS_TEXT), as fills. */
export const OA_TYPE_BARS: Record<string, { label: string; bar: string }> = {
  gold: { label: "Gold OA", bar: "bg-[#f4aa2a] dark:bg-amber-400" },
  diamond: { label: "Diamond OA", bar: "bg-[#4fe4f8] dark:bg-cyan-300" },
  hybrid: { label: "Hybrid", bar: "bg-[#4d84c7] dark:bg-[#82b1e4]" },
  subscription: {
    label: "Subscription (closed)",
    bar: "bg-slate-500 dark:bg-slate-400",
  },
};

const OA_TYPE_ORDER = ["gold", "diamond", "hybrid", "subscription"] as const;

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
  if (total <= 0)
    return <span className="text-[var(--muted-foreground)]">—</span>;
  const parts = OA_TYPE_ORDER.map((type) => ({
    type,
    n: counts[type] ?? 0,
  })).filter((p) => p.n > 0);
  return (
    <div
      className={`flex w-full min-w-16 overflow-hidden rounded-full bg-[var(--muted)] ${className}`}
      role="img"
      aria-label={`Journal access mix: ${parts
        .map((p) => `${OA_TYPE_BARS[p.type].label} ${p.n}`)
        .join(", ")}`}
    >
      {parts.map((p) => (
        <div
          key={p.type}
          className={OA_TYPE_BARS[p.type].bar}
          style={{ flexGrow: p.n, flexBasis: 0 }}
          title={`${OA_TYPE_BARS[p.type].label}: ${p.n}`}
        />
      ))}
    </div>
  );
}

/** Label/count legend matching OaCompositionBar's segments. */
export function OaCompositionLegend({ counts }: { counts: OaTypeCounts }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--muted-foreground)]">
      {OA_TYPE_ORDER.map((type) => (
        <li key={type} className="flex items-center gap-1.5">
          <span
            aria-hidden
            className={`inline-block size-2.5 rounded-full ${OA_TYPE_BARS[type].bar}`}
          />
          {OA_TYPE_BARS[type].label}
          {counts[type] != null && (
            <span className="tabular-nums">{counts[type]}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
