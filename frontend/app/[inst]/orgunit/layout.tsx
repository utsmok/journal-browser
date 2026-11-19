import type { Metadata } from "next";

import { getTranslations } from "next-intl/server";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("orgunits");
  return {
    title: { default: t("meta.title"), template: t("meta.titleTemplate") },
  };
}

export default function OrgUnitsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
