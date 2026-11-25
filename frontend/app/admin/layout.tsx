import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AdminGate } from "@/components/admin/admin-gate";
import { SectionMessages } from "@/i18n/section-messages";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin");
  return { title: t("meta.title"), robots: { index: false, follow: false } };
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <SectionMessages namespaces={["admin"]}>
      <AdminGate>{children}</AdminGate>
    </SectionMessages>
  );
}
