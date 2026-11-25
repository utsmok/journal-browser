import type { Metadata } from "next";

import { SectionMessages } from "@/i18n/section-messages";
import { type InstRoute, instPage, pageContext } from "@/lib/page-meta";

export async function generateMetadata({ params }: InstRoute): Promise<Metadata> {
  const { inst } = await params;
  const { t, short } = await pageContext(inst, "collaborations");
  return {
    title: { default: t("title"), template: t("titleTemplate") },
    ...instPage(inst, "/collaborations", t("meta.description", { inst: short })),
  };
}

export default function CollaborationsLayout({ children }: { children: React.ReactNode }) {
  return <SectionMessages namespaces={["collaborations", "journals"]}>{children}</SectionMessages>;
}
