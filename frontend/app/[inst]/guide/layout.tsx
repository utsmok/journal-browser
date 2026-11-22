import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("guide");
  return {
    title: t("meta.title"),
    description: t("meta.description"),
  };
}

export default function GuideLayout({ children }: { children: React.ReactNode }) {
  return children;
}
