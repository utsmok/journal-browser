"use client";

import { useTranslations } from "next-intl";

import { CollapsibleCard } from "@/components/collapsible-card";
import { CopyButton, External } from "@/components/journal/shared";
import { SourceNote } from "@/components/source-note";

/** Ids and registry entries for this journal, gathered in one card:
 * ISSNs (copyable) plus DOAJ, OpenAlex, and Open Access NL records. */
export function IdentifiersCard({
  issnL,
  issns,
  doajUrl,
  openalexUrl,
  oaNlSlug,
}: {
  issnL: string;
  issns: string[];
  doajUrl?: string | null;
  openalexUrl?: string | null;
  oaNlSlug?: string | null;
}) {
  const t = useTranslations("journals");
  const rows = [
    ...[`ISSN-L ${issnL}`, ...issns.map((i) => `ISSN ${i}`)]
      .filter((v, i, a) => a.indexOf(v) === i)
      .map((label) => ({ key: label, label })),
    ...(doajUrl ? [{ key: "doaj", label: t("identifiers.doajRecord"), href: doajUrl }] : []),
    ...(openalexUrl
      ? [{ key: "openalex", label: t("identifiers.openalexSource"), href: openalexUrl }]
      : []),
    ...(oaNlSlug
      ? [
          {
            key: "oa-nl",
            label: t("identifiers.oaNlPublisher"),
            href: `https://openaccess.nl/en/publisher/${oaNlSlug}`,
          },
        ]
      : []),
  ];
  return (
    <CollapsibleCard
      id="identifiers"
      title={t("identifiers.title")}
      description={
        <p className="text-sm text-[var(--muted-foreground)]">{t("identifiers.description")}</p>
      }
      contentClassName="space-y-2 text-sm"
    >
      <ul className="divide-y divide-[var(--border)]">
        {rows.map((row) => (
          <li
            key={row.key}
            className="flex flex-wrap items-center justify-between gap-2 py-1.5 first:pt-0"
          >
            {"href" in row && row.href ? (
              <>
                <External href={row.href}>{row.label}</External>
                {row.key === "doaj" && (
                  <SourceNote
                    source={t("identifiers.viaDoaj")}
                    url="https://doaj.org"
                    codes={["doaj-canon"]}
                  />
                )}
              </>
            ) : (
              <>
                <span className="tabular-nums text-[var(--muted-foreground)]">{row.label}</span>
                <CopyButton text={row.label.replace(/^ISSN(-L)? /, "")} label={row.label} />
              </>
            )}
          </li>
        ))}
      </ul>
    </CollapsibleCard>
  );
}
