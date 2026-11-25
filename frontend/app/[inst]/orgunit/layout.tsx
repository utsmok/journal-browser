import type { Metadata } from "next";

import { SectionMessages } from "@/i18n/section-messages";
import { type InstRoute, instPage, pageContext } from "@/lib/page-meta";

export async function generateMetadata({ params }: InstRoute): Promise<Metadata> {
  const { inst } = await params;
  const { t, short } = await pageContext(inst, "orgunits");
  return {
    title: { default: t("meta.title"), template: t("meta.titleTemplate") },
    ...instPage(inst, "/orgunit", t("meta.listDescription", { inst: short })),
  };
}

export default function OrgUnitsLayout({ children }: { children: React.ReactNode }) {
  return (
    <SectionMessages
      namespaces={["orgunits", "journals", "search", "authors", "collaborations", "publishers"]}
    >
      {children}
    </SectionMessages>
  );
}
