import type { Metadata } from "next";

import { SectionMessages } from "@/i18n/section-messages";
import { type InstRoute, instPage, pageContext } from "@/lib/page-meta";

export async function generateMetadata({ params }: InstRoute): Promise<Metadata> {
  const { inst } = await params;
  const { t, short } = await pageContext(inst, "funders");
  return {
    title: { default: t("title"), template: t("titleTemplate") },
    ...instPage(inst, "/funders", t("meta.listDescription", { inst: short })),
  };
}

export default function FundersLayout({ children }: { children: React.ReactNode }) {
  return (
    <SectionMessages namespaces={["funders", "journals", "search"]}>{children}</SectionMessages>
  );
}
