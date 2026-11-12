import type { Metadata } from "next";

import { getTranslations } from "next-intl/server";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("authors");
  const common = await getTranslations("common");
  return {
    title: { default: t("meta.title"), template: common("appTitleTemplate") },
  };
}

export default function AuthorsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
