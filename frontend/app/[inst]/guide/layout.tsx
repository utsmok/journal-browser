import type { Metadata } from "next";

import { SectionMessages } from "@/i18n/section-messages";
import { type InstRoute, instPage, pageContext } from "@/lib/page-meta";

export async function generateMetadata({ params }: InstRoute): Promise<Metadata> {
  const { inst } = await params;
  const { t } = await pageContext(inst, "guide");
  return { title: t("meta.title"), ...instPage(inst, "/guide", t("meta.description")) };
}

export default function GuideLayout({ children }: { children: React.ReactNode }) {
  return (
    <SectionMessages namespaces={["guide", "home", "journals", "search"]}>
      {children}
    </SectionMessages>
  );
}
