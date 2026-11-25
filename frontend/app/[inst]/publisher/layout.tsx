import type { Metadata } from "next";

import { SectionMessages } from "@/i18n/section-messages";
import { type InstRoute, instPage, pageContext } from "@/lib/page-meta";

export async function generateMetadata({ params }: InstRoute): Promise<Metadata> {
  const { inst } = await params;
  const { t, short } = await pageContext(inst, "publishers");
  return {
    title: { default: t("title"), template: t("titleTemplate") },
    ...instPage(inst, "/publisher", t("meta.listDescription", { inst: short })),
  };
}

export default function PublishersLayout({ children }: { children: React.ReactNode }) {
  return (
    <SectionMessages namespaces={["publishers", "journals", "search", "authors", "orgunits"]}>
      {children}
    </SectionMessages>
  );
}
