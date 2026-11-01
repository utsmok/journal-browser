"use client";

import { IdentitiesSection } from "@/components/admin/sections/identities-section";
import { useInstitution } from "@/hooks/use-institution";

export default function InstAdminIdentitiesPage() {
  const inst = useInstitution();
  return <IdentitiesSection inst={inst} />;
}
