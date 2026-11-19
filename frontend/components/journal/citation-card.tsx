"use client";

import { useTranslations } from "next-intl";

import { CollapsibleCard } from "@/components/collapsible-card";
import { CopyButton } from "@/components/journal/shared";
import { useInstitution } from "@/hooks/use-institution";
import type { JournalDetailResponse } from "@/lib/api";

export function CitationCard({ data }: { data: JournalDetailResponse }) {
  const t = useTranslations("journals");
  const inst = useInstitution();
  const today = new Date().toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
  const citation = t("citation.template", {
    title: data.journal.title ?? data.journal.issn_l,
    publisher: data.journal.publisher_name ?? t("header.unknownPublisher"),
    issnL: data.journal.issn_l,
    url: `${process.env.NEXT_PUBLIC_SITE_URL ?? "https://journalbrowser.samuelmok.cc"}/${inst}/journals/${data.journal.issn_l}`,
    date: today,
  });
  return (
    <CollapsibleCard id="cite" title={t("citation.title")} contentClassName="space-y-2 text-sm">
      <div className="flex items-start gap-2">
        {/* anywhere (not break-words): only `anywhere` lets the long canonical URL
              count as breakable for the grid column's min-content, so mobile stays 390px. */}
        <p className="min-w-0 flex-1 text-pretty [overflow-wrap:anywhere]">{citation}</p>
        <CopyButton text={citation} label={t("citation.copyLabel")} />
      </div>
      <p className="border-t border-[var(--border)] pt-2 text-xs text-[var(--muted-foreground)]">
        {t("citation.copyHint")}
      </p>
    </CollapsibleCard>
  );
}
