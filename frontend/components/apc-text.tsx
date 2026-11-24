"use client";

import { useTranslations } from "next-intl";

import { apcStatsText, apcSummary, type ApcFields } from "@/lib/format";

/**
 * The APC of one journal in a list. A publisher list price is shown as
 * such. Without one, the range of amounts that institutions paid (OpenAPC)
 * is shown and marked "paid", so that a paid mean never passes for a list
 * price. The tooltips name the dataset and the year.
 */
export function ApcText({ apc, className }: { apc: ApcFields; className?: string }) {
  const t = useTranslations("common");
  const s = apcSummary(apc);

  if (s.kind === "list" && s.amount != null) {
    const source = s.source ?? "";
    const year = s.year ?? "—";
    const title =
      s.original !== null
        ? t("apc.listConvertedTitle", { amount: s.amount, source, year, original: s.original })
        : s.currency !== "EUR"
          ? t("apc.listNoRateTitle", {
              amount: s.amount,
              source,
              year,
              currency: s.currency ?? "",
            })
          : t("apc.listTitle", { amount: s.amount, source, year });
    return (
      <span className={`whitespace-nowrap tabular-nums ${className ?? ""}`} title={title}>
        {s.amount}
      </span>
    );
  }
  if (s.kind === "paid" && s.amount != null && s.paid != null) {
    const detail = apc.apc_stats.length > 0 ? apcStatsText(apc.apc_stats) : "";
    const paidTitle = t("apc.paidTitle", {
      range: s.amount,
      year: s.paid.period,
      mean: s.paid.amount,
      count: s.paid.count,
    });
    return (
      <span className={`inline-flex items-center gap-1 whitespace-nowrap ${className ?? ""}`}>
        <span className="tabular-nums" title={detail || paidTitle}>
          {s.amount}
        </span>
        <span className="text-[11px] text-[var(--muted-foreground)]" title={paidTitle}>
          {t("apc.paidLabel")}
        </span>
        {detail && (
          <span
            className="cursor-help rounded-full border border-[var(--muted-foreground)]/50 px-[5px] text-[10px] leading-[14px] text-[var(--muted-foreground)]"
            title={t("apc.paidDetail", { detail })}
            aria-label={t("apc.paidAria")}
          >
            ?
          </span>
        )}
      </span>
    );
  }
  return <span className={`text-[var(--muted-foreground)] ${className ?? ""}`}>{"—"}</span>;
}
