"use client";

import { Download } from "lucide-react";
import { useTranslations } from "next-intl";

import { buttonVariants } from "@/components/ui/button";

/** Plain anchor with `download`, styled as an outline button: fetches one
 * of the uncapped CSV exports (gap lists, author works) through the same
 * /api proxy the api client uses. */
export function GapCsvButton({ href }: { href: string }) {
  const t = useTranslations("common");
  return (
    <a href={href} download className={buttonVariants({ variant: "outline", size: "sm" })}>
      <Download aria-hidden className="size-3.5 shrink-0" />
      {t("gapCsv.download")}
    </a>
  );
}
