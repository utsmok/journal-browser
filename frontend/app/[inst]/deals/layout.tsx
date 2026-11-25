import type { Metadata } from "next";

import { SectionMessages } from "@/i18n/section-messages";
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
  return <SectionMessages namespaces={["deals", "journals", "search"]}>{children}</SectionMessages>;
}
