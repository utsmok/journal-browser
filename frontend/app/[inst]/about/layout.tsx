import type { Metadata } from "next";

import { type InstRoute, instPage, pageContext } from "@/lib/page-meta";

export async function generateMetadata({ params }: InstRoute): Promise<Metadata> {
  const { inst } = await params;
  const { t, short } = await pageContext(inst, "about");
  return {
    title: t("meta.title"),
    ...instPage(inst, "/about", t("meta.description", { inst: short })),
  };
}

export default function AboutLayout({ children }: { children: React.ReactNode }) {
  return children;
}
