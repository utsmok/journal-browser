"use client";

import { InstitutionsSection } from "@/components/admin/sections/institutions-section";
import { useInstitution } from "@/hooks/use-institution";

export default function InstAdminInstitutionsPage() {
  const inst = useInstitution();
  return <InstitutionsSection inst={inst} />;
}
