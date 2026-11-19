import type { Metadata } from "next";

import { getTranslations } from "next-intl/server";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("publishers");
  return { title: { default: t("title"), template: t("titleTemplate") } };
}

export default function PublishersLayout({ children }: { children: React.ReactNode }) {
  return children;
}
