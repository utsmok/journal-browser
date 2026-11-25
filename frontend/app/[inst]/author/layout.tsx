import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { SectionMessages } from "@/i18n/section-messages";
import { type InstRoute, instPage, pageContext } from "@/lib/page-meta";

export async function generateMetadata({ params }: InstRoute): Promise<Metadata> {
  const { inst } = await params;
  const [common, { t, short }] = await Promise.all([
    getTranslations("common"),
    pageContext(inst, "authors"),
  ]);
  return {
    title: { default: t("meta.title"), template: common("appTitleTemplate") },
    ...instPage(inst, "/author", t("meta.listDescription", { inst: short })),
  };
}

export default function AuthorsLayout({ children }: { children: React.ReactNode }) {
  return (
    <SectionMessages namespaces={["authors", "journals", "search", "collaborations"]}>
      {children}
    </SectionMessages>
  );
}
