import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AdminGate } from "@/components/admin/admin-gate";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin");
  return { title: t("meta.title") };
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <AdminGate>{children}</AdminGate>;
}
