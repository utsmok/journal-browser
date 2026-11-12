import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("docs");
  return { title: t("meta.title") };
}

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
