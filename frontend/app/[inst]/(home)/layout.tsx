import type { Metadata } from "next";

import { type InstRoute, instPage, pageContext } from "@/lib/page-meta";

export async function generateMetadata({ params }: InstRoute): Promise<Metadata> {
  const { inst } = await params;
  const { t, short } = await pageContext(inst, "home");
  return {
    title: t("metadata.title"),
    ...instPage(inst, "", t("metadata.description", { inst: short })),
  };
}

export default function HomeLayout({ children }: { children: React.ReactNode }) {
  return children;
}
