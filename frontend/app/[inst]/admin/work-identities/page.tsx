"use client";

import { WorkIdentitiesSection } from "@/components/admin/sections/work-identities-section";
import { useInstitution } from "@/hooks/use-institution";

export default function InstAdminWorkIdentitiesPage() {
  const inst = useInstitution();
  return <WorkIdentitiesSection inst={inst} />;
}
