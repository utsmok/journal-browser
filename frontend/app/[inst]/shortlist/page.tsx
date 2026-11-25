import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { ShortlistView } from "@/components/shortlist/shortlist-view";
import { parseShareIssns } from "@/lib/shortlist";

type ShortlistSearchParams = Promise<{ j?: string | string[] }>;

export async function generateMetadata({
  searchParams,
}: {
  searchParams: ShortlistSearchParams;
}): Promise<Metadata> {
  const { j } = await searchParams;
  const t = await getTranslations("shortlist");
  return {
    title: j === undefined ? t("meta.title") : t("meta.titleShared"),
    description: t("meta.description"),
  };
}

export default async function ShortlistPage({
  searchParams,
}: {
  searchParams: ShortlistSearchParams;
}) {
  const { j } = await searchParams;
  return (
    <ShortlistView
      shared={j !== undefined}
      sharedIssnLs={parseShareIssns(Array.isArray(j) ? j.join(",") : j)}
    />
  );
}
