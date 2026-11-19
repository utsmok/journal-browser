"use client";

import { ExternalLink, Github } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { SourceNote } from "@/components/source-note";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { useFreshness, useLimitations } from "@/hooks/use-api";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { errorMessage } from "@/lib/api";

type SourceInfo = {
  name: string;
  url: string;
  /** Key of the role description in the "about" messages under "sources.". */
  roleKey: string;
  table?: string;
  harvest?: string;
};

const SOURCES: SourceInfo[] = [
  {
    name: "Pure",
    // Real portal URL comes from settings at render time (site.researchPortalUrl).
    url: "",
    roleKey: "pure",
    table: "institution_works_stats",
  },
  {
    name: "OpenAlex",
    url: "https://openalex.org",
    roleKey: "openalex",
    table: "journals",
  },
  {
    name: "DOAJ",
    url: "https://doaj.org",
    roleKey: "doaj",
    table: "doaj",
  },
  {
    name: "OpenAIRE",
    url: "https://openaire.eu",
    roleKey: "openaire",
    harvest: "openaire",
  },
  {
    name: "Crossref",
    url: "https://www.crossref.org",
    roleKey: "crossref",
    harvest: "crossref",
  },
  {
    name: "openaccess.nl",
    url: "https://www.openaccess.nl/en/publishing/publisher-deals",
    roleKey: "openaccessNl",
    harvest: "openaccess.nl",
  },
  {
    name: "JCT",
    url: "https://journalcheckertool.org/transformative-agreements/",
    roleKey: "jct",
    harvest: "jct",
  },
  {
    name: "OpenAPC",
    url: "https://github.com/OpenAPC/openapc-de",
    roleKey: "openapc",
    table: "apc_evidence",
  },
  {
    name: "Jisc Open Policy Finder",
    url: "https://openpolicyfinder.jisc.ac.uk",
    roleKey: "jiscOpf",
    harvest: "jisc_opf",
  },
  {
    name: "Scimago",
    url: "https://www.scimagojr.com",
    roleKey: "scimago",
    table: "scimagojr_metrics",
  },
];

/** Dates render with a fixed locale; unknown values fall back to the label
 * the caller passes in from the about messages. */
function fmt(value: unknown, unknownLabel: string) {
  if (value === null || value === undefined) return unknownLabel;
  if (typeof value === "string" && /^\d{4}/.test(value))
    return new Date(value).toLocaleDateString("en", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  return String(value);
}

function ExternalIcon() {
  return <ExternalLink aria-hidden className="size-3" />;
}

export default function AboutPage() {
  const t = useTranslations("about");
  const tc = useTranslations("common");
  const site = useSiteMeta();
  const freshnessQuery = useFreshness();
  const limitationsQuery = useLimitations();
  const freshness = freshnessQuery.data;
  const limitations = limitationsQuery.data;

  const tables = (freshness?.tables ?? {}) as Record<string, unknown>;
  // Latest first; collapsed to the recent tail so the public page stays a
  // summary, not a pipeline log.
  const [showAllRuns, setShowAllRuns] = useState(false);
  const harvestRows = [...(freshness?.harvests ?? [])].sort((a, b) =>
    (b.finished_at ?? "").localeCompare(a.finished_at ?? ""),
  );
  const shownHarvests = showAllRuns ? harvestRows : harvestRows.slice(0, 10);

  function stamp(info: SourceInfo) {
    if (info.table) return tables[info.table];
    const runs = (freshness?.harvests ?? [])
      .filter((h) => h.source === info.harvest && h.finished_at)
      .map((h) => h.finished_at)
      .sort();
    return runs.at(-1) ?? null;
  }

  const ror = freshness?.ror ?? null;
  const institution = freshness?.institution ?? site.name;
  const rorId = ror ? ror.replace(/^https?:\/\/ror\.org\//, "") : null;
  const rorHref = ror ? (/^https?:\/\//.test(ror) ? ror : `https://ror.org/${ror}`) : null;

  return (
    <div className="mx-auto max-w-screen-2xl space-y-10 px-4 py-10">
      <header>
        <h1 className="mb-2 text-3xl font-bold">{t("page.heading")}</h1>
        <div className="max-w-prose space-y-3">
          <p>
            {rorId && rorHref
              ? t.rich("page.introLeadRor", {
                  institution,
                  rorId,
                  bold: (chunk) => <strong>{chunk}</strong>,
                  link: (chunk) => (
                    <a
                      href={rorHref}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[var(--primary-text)] hover:underline"
                    >
                      {chunk}
                    </a>
                  ),
                })
              : t.rich("page.introLead", {
                  institution,
                  bold: (chunk) => <strong>{chunk}</strong>,
                })}{" "}
            {t("page.introPurpose")}
          </p>
          <p className="text-[var(--muted-foreground)]">
            {t.rich("page.introLegacy", {
              link: (chunk) => (
                <a
                  href="https://library.wur.nl/WebQuery/utbrowser?q=*"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[var(--primary-text)] underline-offset-2 hover:underline"
                >
                  {chunk}
                </a>
              ),
            })}{" "}
            {t("page.introPolicy")}
          </p>
        </div>
      </header>
      {(freshness?.degraded?.length ?? 0) > 0 && (
        <div
          role="alert"
          className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm"
        >
          <p className="font-semibold text-amber-600 dark:text-amber-400">{t("degraded.title")}</p>
          <ul className="mt-2 space-y-1 text-[var(--muted-foreground)]">
            {(freshness?.degraded ?? []).map((d) => (
              <li key={d.source}>
                <strong>{d.source}</strong>:{" "}
                {t("degraded.item", {
                  detail: d.detail,
                  time: new Date(d.since).toLocaleString("en", {
                    dateStyle: "medium",
                    timeStyle: "short",
                  }),
                })}
              </li>
            ))}
          </ul>
        </div>
      )}

      {(freshnessQuery.isError || limitationsQuery.isError) && (
        <p aria-live="polite" className="text-sm text-[var(--destructive)]">
          {errorMessage(tc, freshnessQuery.isError ? freshnessQuery.error : limitationsQuery.error)}{" "}
          <button
            type="button"
            onClick={() => {
              freshnessQuery.refetch();
              limitationsQuery.refetch();
            }}
            className="underline underline-offset-2 hover:no-underline"
          >
            {t("page.retry")}
          </button>
        </p>
      )}

      <section>
        <h2 className="mb-3 text-xl font-bold">{t("sources.heading")}</h2>
        <Card>
          <CardContent className="pt-6">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="sr-only">{t("sources.tableCaption")}</caption>
                <thead>
                  <tr className="text-left text-xs text-[var(--muted-foreground)]">
                    <th scope="col" className="py-1 pr-4 font-medium">
                      {t("sources.columnSource")}
                    </th>
                    <th scope="col" className="py-1 pr-4 font-medium">
                      {t("sources.columnProvides")}
                    </th>
                    <th scope="col" className="py-1 font-medium">
                      {t("sources.columnLatest")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {SOURCES.map((info) => (
                    <tr key={info.name} className="border-t border-[var(--border)] align-top">
                      <td className="py-2 pr-4 whitespace-nowrap">
                        <a
                          href={info.url || site.researchPortalUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-0.5 font-semibold text-[var(--primary-text)] hover:underline"
                        >
                          {info.name} <ExternalIcon />
                        </a>
                      </td>
                      <td className="py-2 pr-4 text-[var(--muted-foreground)]">
                        {t(`sources.${info.roleKey}`)}
                      </td>
                      <td className="py-2 text-xs whitespace-nowrap tabular-nums text-[var(--muted-foreground)]">
                        {freshnessQuery.isPending ? "…" : fmt(stamp(info), t("page.unknownValue"))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-4 max-w-prose text-xs text-[var(--muted-foreground)]">
              {t("sources.footnote")}{" "}
              {t("sources.statsWindow", {
                window:
                  site.windowStart === undefined
                    ? t("sources.statsWindowFallback")
                    : site.windowStart,
              })}
            </p>
          </CardContent>
        </Card>
      </section>

      {freshness && freshness.harvests.length > 0 && (
        <section>
          <h2 className="mb-3 text-xl font-bold">{t("harvests.heading")}</h2>
          <Card>
            <CardContent className="overflow-x-auto pt-6">
              <table className="w-full text-xs">
                <caption className="sr-only">{t("harvests.tableCaption")}</caption>
                <thead>
                  <tr className="text-left text-[var(--muted-foreground)]">
                    <th className="py-1 pr-3 font-medium">{t("harvests.columnSource")}</th>
                    <th className="py-1 pr-3 font-medium">{t("harvests.columnEntity")}</th>
                    <th className="py-1 pr-3 font-medium">{t("harvests.columnFilters")}</th>
                    <th className="py-1 pr-3 font-medium">{t("harvests.columnStatus")}</th>
                    <th className="py-1 font-medium">{t("harvests.columnFinished")}</th>
                  </tr>
                </thead>
                <tbody>
                  {shownHarvests.map((h, i) => {
                    const url = SOURCES.find(
                      (s) => s.name.toLowerCase() === h.source.toLowerCase(),
                    )?.url;
                    return (
                      <tr
                        key={`${h.source}-${h.entity_type}-${i}`}
                        className="border-t border-[var(--border)]"
                      >
                        <td className="py-1.5 pr-3">
                          {url ? (
                            <a
                              href={url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-[var(--primary-text)] hover:underline"
                            >
                              {h.source}
                            </a>
                          ) : (
                            h.source
                          )}
                        </td>
                        <td className="py-1.5 pr-3">{h.entity_type}</td>
                        <td className="py-1.5 pr-3">
                          <Badge variant={h.status === "completed" ? "muted" : "outline"}>
                            {h.status ?? "—"}
                          </Badge>
                        </td>
                        <td className="py-1.5 tabular-nums">
                          {fmt(h.finished_at, t("page.unknownValue"))}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="mt-3 text-xs text-[var(--muted-foreground)]">
                {t("harvests.footnote")}
                {harvestRows.length > shownHarvests.length && (
                  <>
                    {" "}
                    <button
                      type="button"
                      onClick={() => setShowAllRuns(true)}
                      className="font-medium text-[var(--primary-text)] underline underline-offset-2 hover:no-underline"
                    >
                      {t("harvests.showAll", { count: harvestRows.length })}
                    </button>
                  </>
                )}
              </p>
            </CardContent>
          </Card>
        </section>
      )}

      <section>
        <h2 className="mb-3 text-xl font-bold">{t("licences.heading")}</h2>
        <ul className="grid max-w-prose gap-x-10 gap-y-2 text-sm sm:grid-cols-2">
          <li>
            {t.rich("licences.code", {
              link: (chunk) => (
                <a
                  href="https://github.com/utsmok/journal-browser"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-[var(--primary-text)] underline-offset-2 hover:underline"
                >
                  <Github aria-hidden className="size-4" /> {chunk}
                </a>
              ),
            })}
          </li>
          <li>
            {t.rich("licences.policyFinder", {
              link: (chunk) => (
                <a
                  href="https://openpolicyfinder.jisc.ac.uk"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-0.5 text-[var(--primary-text)] underline-offset-2 hover:underline"
                >
                  {chunk} <ExternalIcon />
                </a>
              ),
            })}
          </li>
        </ul>
      </section>

      <section>
        <h2 className="mb-1 text-xl font-bold">{t("limitations.heading")}</h2>
        <p className="mb-4 max-w-prose text-sm text-[var(--muted-foreground)]">
          {t("limitations.intro")}
        </p>
        {(limitations ?? []).length === 0 && !limitationsQuery.isPending ? (
          <p className="text-sm text-[var(--muted-foreground)]">{t("limitations.empty")}</p>
        ) : (
          <ul className="grid gap-x-10 gap-y-5 md:grid-cols-2">
            {(limitations ?? []).map((l) => (
              <li key={l.code} className="text-sm">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  <span className="font-mono text-xs font-semibold">{l.code}</span>
                  <Badge
                    variant={l.severity === "warning" ? "default" : "muted"}
                    className="uppercase"
                  >
                    {l.severity}
                  </Badge>
                  <span className="text-xs text-[var(--muted-foreground)]">
                    {l.source} · {l.scope}
                  </span>
                </div>
                <p className="mt-1">
                  {l.hint}
                  {l.url && (
                    <a
                      href={l.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="ml-2 inline-flex items-center gap-0.5 text-[var(--primary-text)] hover:underline"
                    >
                      {t("limitations.moreInfo")} <ExternalIcon />
                    </a>
                  )}
                </p>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-4">
          <SourceNote
            source="Limitation registry"
            codes={["stats-window", "corpus-cutoff", "pure-canon-primary"]}
          />
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-xl font-bold">{t("contact.heading")}</h2>
        <div className="max-w-prose space-y-2 text-sm">
          <p className="text-[var(--muted-foreground)]">
            {t("contact.intro", { institution: site.name })}
          </p>
          <ul className="flex flex-wrap gap-x-6 gap-y-1">
            <li>
              <a
                href={site.libraryUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-0.5 text-[var(--primary-text)] hover:underline"
              >
                {t("contact.libraryLink", { institution: site.name })} <ExternalIcon />
              </a>
            </li>
            <li>
              <a
                href={site.oaGuideUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-0.5 text-[var(--primary-text)] hover:underline"
              >
                {t("contact.guideLink")} <ExternalIcon />
              </a>
            </li>
            <li>
              <a
                href={`mailto:${site.supportEmail}`}
                className="text-[var(--primary-text)] hover:underline"
              >
                {site.supportEmail}
              </a>
            </li>
          </ul>
          {site.adminContact && (
            <p className="text-[var(--muted-foreground)]">
              {t.rich("contact.adminIntro", {
                email: site.adminContact,
                link: (chunk) => (
                  <a
                    href={`mailto:${site.adminContact}`}
                    className="text-[var(--primary-text)] underline-offset-2 hover:underline"
                  >
                    {chunk}
                  </a>
                ),
              })}
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
