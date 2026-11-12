import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("deals");
  return { title: t("meta.title") };
}

export default function DealsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
