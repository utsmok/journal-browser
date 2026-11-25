"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { GithubIcon } from "@/components/github-icon";
import { instFromSegment } from "@/lib/global-segments";
import { useFreshness, useInstitutionsDirectory } from "@/hooks/use-api";
import { useSiteMeta } from "@/hooks/use-site-meta";
import { formatDate } from "@/lib/format";
import { staleSources } from "@/lib/freshness";

/** Footer with institution links from settings when scoped to an
 * institution; the chooser at "/" gets only the repo link and attribution.
 * Discreet links to the data-pipeline page and the docs index (DECISIONS
 * 12); admin stays unlinked. Institution pages also state when the data was
 * last updated (the oldest of the institution's core sources) and warn when
 * a source is overdue or failed. */
export function SiteFooter() {
  const t = useTranslations("common");
  const site = useSiteMeta();
  const pathname = usePathname() ?? "/";
  const seg = pathname.split("/")[1] ?? "";
  const inst = instFromSegment(seg);
  const firstInst = useInstitutionsDirectory().data?.[0]?.code;
  const freshness = useFreshness(inst).data;
  const stale = freshness ? staleSources(freshness.sources) : [];
  const docsHref = inst ? `/${inst}/docs` : firstInst ? `/${firstInst}/docs` : null;
  const scoped = Boolean(inst);
  const links: { href: string; label: string; icon?: "github" }[] = [
    ...(scoped
      ? [
          { href: site.libraryUrl, label: t("footer.libraryLink", { name: site.name }) },
          { href: site.oaGuideUrl, label: t("footer.oaGuideLink") },
          { href: `mailto:${site.supportEmail}`, label: site.supportEmail },
          ...(site.adminContact
            ? [
                {
                  href: `mailto:${site.adminContact}`,
                  label: t("footer.adminContact", { email: site.adminContact }),
                },
              ]
            : []),
        ]
      : []),
    {
      href: "https://github.com/utsmok/journal-browser",
      label: t("footer.sourceLink"),
      icon: "github" as const,
    },
  ];
  return (
    <footer className="mt-auto bg-[var(--secondary)] text-[var(--secondary-foreground)]">
      <div className="mx-auto max-w-screen-2xl px-4 py-6 text-sm">
        <ul className="flex flex-wrap items-center gap-x-6 gap-y-1">
          {links.map((l) => (
            <li key={l.href} className="flex items-center gap-1">
              <a
                href={l.href}
                {...(l.href.startsWith("mailto:")
                  ? {}
                  : { target: "_blank", rel: "noopener noreferrer" })}
                className="inline-flex items-center gap-1 underline-offset-2 hover:underline"
              >
                {l.icon === "github" && <GithubIcon className="size-4" />}
                <span className={l.icon ? "sr-only" : undefined}>{l.label}</span>
              </a>
            </li>
          ))}
        </ul>
        {freshness && (freshness.data_updated_at || stale.length > 0) && (
          <p className="mt-3 text-xs text-white/70" data-testid="footer-data-updated">
            {freshness.data_updated_at && (
              <>
                {t("footer.dataUpdated", { date: formatDate(freshness.data_updated_at) })}
                {" · "}
              </>
            )}
            <Link
              href={`/${inst}/about#data-freshness`}
              className="text-white/60 underline-offset-2 hover:text-white/90 hover:underline"
            >
              {t("footer.dataFreshnessLink")}
            </Link>
            {stale.length > 0 && <span className="text-amber-300"> · {t("footer.dataStale")}</span>}
          </p>
        )}
        <p className="mt-3 text-xs text-white/70">
          <Link
            href="/data-pipeline"
            className="text-white/60 underline-offset-2 hover:text-white/90 hover:underline"
          >
            {t("footer.dataPipelineLink")}
          </Link>
          {docsHref && (
            <>
              {" · "}
              <Link
                href={docsHref}
                className="text-white/60 underline-offset-2 hover:text-white/90 hover:underline"
              >
                {t("footer.docsLink")}
              </Link>
            </>
          )}
        </p>
        <p className="mt-3 text-xs text-white/70">{t("footer.dataSources")}</p>
      </div>
    </footer>
  );
}
