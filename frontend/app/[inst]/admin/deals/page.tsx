"use client";

import { DealsSection } from "@/components/admin/sections/deals-section";
import { useInstitution } from "@/hooks/use-institution";

export default function InstAdminDealsPage() {
  const inst = useInstitution();
  return <DealsSection basePath={`/${inst}/admin`} />;
}
