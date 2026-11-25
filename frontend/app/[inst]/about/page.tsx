"use client";

import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { FreshnessTable } from "@/components/freshness-table";
import { GithubIcon } from "@/components/github-icon";
import { SourceNote } from "@/components/source-note";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { useFreshness, useLimitations } from "@/hooks/use-api";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { errorMessage } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { harvestUrl } from "@/lib/freshness";

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

  // Latest first; collapsed to the recent tail so the public page stays a
  // summary, not a pipeline log.
  const [showAllRuns, setShowAllRuns] = useState(false);
  const harvestRows = [...(freshness?.harvests ?? [])].sort((a, b) =>
    (b.finished_at ?? "").localeCompare(a.finished_at ?? ""),
  );
  const shownHarvests = showAllRuns ? harvestRows : harvestRows.slice(0, 10);

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

      <section id="data-freshness" className="scroll-mt-24">
        <h2 className="mb-3 text-xl font-bold">{t("freshness.heading")}</h2>
        <Card>
          <CardContent className="pt-6">
            <p className="mb-4 max-w-prose text-sm text-[var(--muted-foreground)]">
              {t("freshness.intro")}
            </p>
            {freshnessQuery.isPending && (
              <p aria-live="polite" className="text-sm text-[var(--muted-foreground)]">
                …
              </p>
            )}
            {freshness && freshness.sources.length === 0 && (
              <p className="text-sm text-[var(--muted-foreground)]">{t("freshness.noRuns")}</p>
            )}
            {freshness && freshness.sources.length > 0 && (
              <FreshnessTable
                rows={freshness.sources}
                institution={institution}
                portalUrl={site.researchPortalUrl}
              />
            )}
            <p className="mt-4 max-w-prose text-xs text-[var(--muted-foreground)]">
              {t("freshness.footnote")}{" "}
              {t("freshness.statsWindow", {
                window:
                  site.windowStart === undefined
                    ? t("freshness.statsWindowFallback")
                    : site.windowStart,
              })}
            </p>
            <p className="mt-3 max-w-prose text-xs text-[var(--muted-foreground)]">
              {t("privacy.note")}
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
                    const url = harvestUrl(h.source);
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
                        <td className="py-1.5 tabular-nums">{formatDate(h.finished_at)}</td>
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
                  <GithubIcon className="size-4" /> {chunk}
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
