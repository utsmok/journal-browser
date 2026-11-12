import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("about");
  return { title: t("meta.title") };
}

export default function AboutLayout({ children }: { children: React.ReactNode }) {
  return children;
}
