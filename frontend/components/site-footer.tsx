"use client";

import { Github } from "lucide-react";

import { useSiteMeta } from "@/hooks/use-site-meta";

/** Footer with institution links from settings; the repo link is static. */
export function SiteFooter() {
  const site = useSiteMeta();
  const links: { href: string; label: string; icon?: "github" }[] = [
    { href: site.libraryUrl, label: `${site.name} Library` },
    { href: site.oaGuideUrl, label: "Open Access publishing guide" },
    { href: `mailto:${site.supportEmail}`, label: site.supportEmail },
    ...(site.adminContact
      ? [
          {
            href: `mailto:${site.adminContact}`,
            label: `${site.adminContact} (admin)`,
          },
        ]
      : []),
    {
      href: "https://github.com/utsmok/journal-browser",
      label: "Source code on GitHub",
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
                {l.icon === "github" && (
                  <Github aria-hidden className="size-4" />
                )}
                <span className={l.icon ? "sr-only" : undefined}>{l.label}</span>
              </a>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-white/70">
          Data: OpenAlex, cOAlition S Journal Checker Tool, openaccess.nl, OpenAPC,
          Scimago. Links on every page lead to the upstream source.
        </p>
      </div>
    </footer>
  );
}
