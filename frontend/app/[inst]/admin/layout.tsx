import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { AdminGate } from "@/components/admin/admin-gate";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin");
  return { title: t("meta.title") };
}

export default async function InstAdminLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ inst: string }>;
}) {
  const [{ inst }, t] = await Promise.all([params, getTranslations("admin")]);
  return (
    <AdminGate basePath={`/${inst}/admin`} brand={t("brandInst", { inst })}>
      {children}
    </AdminGate>
  );
}
