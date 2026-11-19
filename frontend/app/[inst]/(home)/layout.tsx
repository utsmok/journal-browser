import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("home");

  return { title: t("metadata.title") };
}

export default function HomeLayout({ children }: { children: React.ReactNode }) {
  return children;
}
