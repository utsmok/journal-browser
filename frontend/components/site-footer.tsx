"use client";

import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { Github } from "lucide-react";

import { useSiteMeta } from "@/hooks/use-site-meta";

/** Footer with institution links from settings when scoped to an
 * institution; the chooser at "/" gets only the repo link and attribution. */
export function SiteFooter() {
  const t = useTranslations("common");
  const site = useSiteMeta();
  const seg = (usePathname() ?? "/").split("/")[1] ?? "";
  const scoped = Boolean(seg) && seg !== "admin";
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
                {l.icon === "github" && <Github aria-hidden className="size-4" />}
                <span className={l.icon ? "sr-only" : undefined}>{l.label}</span>
              </a>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-white/70">{t("footer.dataSources")}</p>
      </div>
    </footer>
  );
}
