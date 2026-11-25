import type { Metadata } from "next";

import { type InstRoute, instPage, pageContext } from "@/lib/page-meta";

export async function generateMetadata({ params }: InstRoute): Promise<Metadata> {
  const { inst } = await params;
  const { t, short } = await pageContext(inst, "deals");
  return {
    title: t("meta.title"),
    ...instPage(inst, "/deals", t("meta.description", { inst: short })),
  };
}

export default function DealsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
