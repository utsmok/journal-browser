import type { Metadata } from "next";

import { AdminGate } from "@/components/admin/admin-gate";

export const metadata: Metadata = {
  title: "Admin",
};

export default async function InstAdminLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ inst: string }>;
}) {
  const { inst } = await params;
  return (
    <AdminGate basePath={`/${inst}/admin`} brand={`Journal admin — ${inst}`}>
      {children}
    </AdminGate>
  );
}
