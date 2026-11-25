import type { Metadata } from "next";

import { type InstRoute, instPage, pageContext } from "@/lib/page-meta";

export async function generateMetadata({ params }: InstRoute): Promise<Metadata> {
  const { inst } = await params;
  const { t } = await pageContext(inst, "docs");
  return { title: t("meta.title"), ...instPage(inst, "/docs", t("meta.description")) };
}

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
