"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import * as React from "react";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { OaStatusChip } from "@/components/badges";
import { CardPager } from "@/components/card-pager";
import { CollapsibleCard } from "@/components/collapsible-card";
import { doiHref, External, urlHost, WORKS_PAGE_SIZE } from "@/components/journal/shared";
import { useInstitution } from "@/hooks/use-institution";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { useYearRange } from "@/hooks/use-year-filter";
import { encodeNamePath } from "@/lib/api";
import { SourceNote } from "@/components/source-note";
import type { Attribution, OpenalexSource, WorksPage } from "@/lib/api";

/** Twente works in this journal, paginated from the /works endpoint. The
 * query itself lives on the page (it races the detail request); this card
 * renders whatever has arrived, skeleton rows while it is still loading. */
export function PublicationsCard({
  title,
  openalex,
  worksNote,
  requested,
  worksQuery,
}: {
  title: string;
  openalex: OpenalexSource | null;
  worksNote: Partial<Attribution>;
  requested: number;
  worksQuery: {
    data: WorksPage | undefined;
    isPending: boolean;
    isFetching: boolean;
  };
}) {
  const t = useTranslations("journals");
  const site = useSiteMeta();
  const inst = useInstitution();
  const { year_from, year_to } = useYearRange();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data, isPending, isFetching } = worksQuery;
  const works = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / WORKS_PAGE_SIZE));
  const page = Math.min(requested, pages);

  const setPage = (p: number) => {
    const next = new URLSearchParams(searchParams.toString());
    if (p > 1) next.set("page", String(p));
    else next.delete("page");
    router.replace(`${pathname}?${next}`, { scroll: false });
  };

  // A shared link can point past the last page; fall back to the last one.
  React.useEffect(() => {
    if (data && requested > pages) {
      const next = new URLSearchParams(searchParams.toString());
      next.set("page", String(pages));
      router.replace(`${pathname}?${next}`, { scroll: false });
    }
  }, [data, requested, pages, pathname, router, searchParams]);

  return (
    <CollapsibleCard
      id="publications"
      title={t("publications.title", { short: site.short })}
      defaultOpen={false}
      description={
        <p className="text-pretty text-sm text-[var(--muted-foreground)]">
          {t("publications.description", {
            short: site.short,
            period:
              year_from !== undefined
                ? `, ${year_from} to ${year_to}`
                : site.windowStart === undefined
                  ? ""
                  : `, ${site.windowStart} onwards`,
          })}
        </p>
      }
      contentClassName="space-y-3 text-sm"
    >
      {isPending && !data ? (
        <div className="space-y-2.5" aria-hidden>
          {[92, 75, 84, 60, 70].map((w, i) => (
            <div
              key={i}
              className="h-4 animate-pulse rounded bg-[var(--muted)]"
              style={{ width: `${w}%` }}
            />
          ))}
        </div>
      ) : works.length === 0 ? (
        // Also the pre-integration state: old backends 404 on /works.
        <p className="text-[var(--muted-foreground)]">
          {t("publications.empty", { name: site.name })}
        </p>
      ) : (
        <ul className="divide-y divide-[var(--border)]">
          {works.map((w) => {
            const href = doiHref(w.doi ?? null) ?? w.url;
            const oa = w.openaire ?? null;
            const usage = [
              oa?.views != null ? t("publications.usageViews", { count: oa.views }) : null,
              oa?.downloads != null
                ? t("publications.usageDownloads", { count: oa.downloads })
                : null,
            ].filter((part): part is string => part !== null);
            const licenseUrl = oa?.license?.startsWith("http") ? oa.license : null;
            // Grant codes read as noise inline ("NWO (10140254)"); the plain
            // names render, codes survive in the hover text.
            const funderNames: string[] = [];
            const funderDetails: string[] = [];
            for (const p of oa?.projects ?? []) {
              const name = p.funder ?? p.acronym ?? p.id;
              if (name == null) continue;
              if (!funderNames.includes(name)) funderNames.push(name);
              funderDetails.push(p.code ? `${name} (${p.code})` : name);
            }
            return (
              <li
                key={w.id}
                className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1 py-2 first:pt-0 last:pb-0"
              >
                {/* Full-basis line on phones: flex-1's 0% basis squeezed the
                    title into a ~63px column beside year/citations badges. */}
                {href ? (
                  <External
                    href={href}
                    className="min-w-0 w-full min-[480px]:w-auto min-[480px]:flex-1 font-medium"
                  >
                    {w.title ?? w.doi ?? w.url}
                  </External>
                ) : (
                  <span className="min-w-0 w-full min-[480px]:w-auto min-[480px]:flex-1 font-medium">
                    {w.title ?? t("publications.untitled")}
                  </span>
                )}
                {!w.in_openalex && (
                  <Badge
                    variant="outline"
                    className="font-normal text-[11px] text-[var(--muted-foreground)]"
                    title={t("publications.pureOnlyHint")}
                  >
                    {t("publications.pureOnly")}
                  </Badge>
                )}
                {w.year != null && (
                  <span className="tabular-nums text-[var(--muted-foreground)]">{w.year}</span>
                )}
                <OaStatusChip status={w.oa_status} />
                <span
                  className="text-xs tabular-nums text-[var(--muted-foreground)]"
                  title={t("publications.citationsTitle")}
                >
                  {t("publications.citations", { count: w.cited_by_count })}
                </span>
                <span
                  className="text-xs tabular-nums text-[var(--muted-foreground)]"
                  title={t("publications.fwciTitle")}
                >
                  {t("publications.fwci", { value: w.fwci != null ? w.fwci.toFixed(2) : "—" })}
                </span>
                {oa?.oa_url && (
                  <External
                    href={oa.oa_url}
                    className="text-xs"
                    title={t("publications.openaireCopyHint")}
                  >
                    {t("publications.openaireCopy")}
                  </External>
                )}
                {usage.length > 0 && (
                  <span
                    className="text-xs tabular-nums text-[var(--muted-foreground)]"
                    title={t("publications.usageTitle")}
                  >
                    {usage.join(" · ")}
                  </span>
                )}
                {oa?.license && (
                  <Badge
                    variant="outline"
                    className="font-normal text-[11px] text-[var(--muted-foreground)]"
                    title={licenseUrl ?? t("publications.licenseHint")}
                  >
                    {licenseUrl ? urlHost(licenseUrl) : oa.license}
                  </Badge>
                )}
                {w.is_retracted && (
                  <Badge
                    variant="outline"
                    title={t("publications.retractedHint")}
                    className="border-red-300 bg-red-100 text-red-700 dark:border-red-400/40 dark:bg-red-400/15 dark:text-red-300"
                  >
                    {t("publications.retracted")}
                  </Badge>
                )}
                {(w.ut_authors.length > 0 || w.ut_groups.length > 0 || funderNames.length > 0) && (
                  <div className="w-full text-xs text-[var(--muted-foreground)]">
                    {w.ut_authors.length > 0 && (
                      <span>
                        {w.ut_authors.map((a, i) => (
                          <React.Fragment key={a.id}>
                            {i > 0 && ", "}
                            <Link
                              href={`/${inst}/author/${a.id}`}
                              className="underline decoration-dotted underline-offset-2 hover:text-[var(--foreground)]"
                            >
                              {a.name}
                            </Link>
                          </React.Fragment>
                        ))}
                      </span>
                    )}
                    {w.ut_groups.map((g, i) => (
                      <React.Fragment key={g.name}>
                        {(w.ut_authors.length > 0 || i > 0) && " · "}
                        <Link
                          href={`/${inst}/orgunit/group/${encodeNamePath(g.name)}`}
                          className="underline decoration-dotted underline-offset-2 hover:text-[var(--foreground)]"
                        >
                          {g.name}
                        </Link>
                      </React.Fragment>
                    ))}
                    {funderNames.length > 0 && (
                      <>
                        {(w.ut_authors.length > 0 || w.ut_groups.length > 0) && " · "}
                        <span title={Array.from(new Set(funderDetails)).join(", ")}>
                          {t("publications.funders")} {funderNames.join(", ")}
                        </span>
                      </>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {pages > 1 && (
        <CardPager
          page={page}
          pages={pages}
          total={total}
          onPage={setPage}
          isFetching={isFetching}
          label={t("publications.pagerLabel")}
        />
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-[var(--border)] pt-3">
        {openalex?.id && (
          <External
            href={`https://openalex.org/works?filter=primary_location.source.id:${openalex.id}`}
          >
            {t("publications.allOpenalexLink")}
          </External>
        )}
        <External
          href={`https://explore.openaire.eu/search/find?keyword=%22${encodeURIComponent(title)}%22`}
        >
          {t("publications.openaireLink")}
        </External>
        <SourceNote {...worksNote} codes={worksNote.caveat_codes} />
      </div>
    </CollapsibleCard>
  );
}
