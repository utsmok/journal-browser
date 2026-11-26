"use client";

import { Bookmark } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { instFromSegment } from "@/lib/global-segments";
import { useShortlist } from "@/lib/shortlist";

/**
 * Header entry for the shortlist of the active institution, with the number
 * of saved journals. Phones show the bookmark and the number only. Outside
 * an institution (chooser, admin) there is no shortlist and the entry stays
 * away.
 */
export function ShortlistLink() {
  const pathname = usePathname() ?? "/";
  const inst = instFromSegment(pathname.split("/")[1] ?? "");
  if (!inst) return null;
  return <ShortlistCount inst={inst} active={pathname.startsWith(`/${inst}/shortlist`)} />;
}

function ShortlistCount({ inst, active }: { inst: string; active: boolean }) {
  const t = useTranslations("common");
  const count = useShortlist(inst).length;
  const label = t("nav.shortlistCountLabel", { count });
  return (
    <Link
      href={`/${inst}/shortlist`}
      aria-label={label}
      aria-current={active ? "page" : undefined}
      title={label}
      className="inline-flex min-h-11 items-center gap-1.5 rounded-[var(--radius)] px-2 text-sm text-white/90 hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70 lg:h-8 lg:min-h-0"
    >
      <Bookmark aria-hidden className="size-4" />
      <span>{t("nav.shortlist")}</span>
      {count > 0 && (
        <span aria-hidden className="tabular-nums">
          ({count})
        </span>
      )}
    </Link>
  );
}
