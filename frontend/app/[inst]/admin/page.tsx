"use client";

import { OverviewSection } from "@/components/admin/sections/overview-section";
import { useInstitution } from "@/hooks/use-institution";

export default function InstAdminPage() {
  const inst = useInstitution();
  return <OverviewSection inst={inst} basePath={`/${inst}/admin`} />;
}
