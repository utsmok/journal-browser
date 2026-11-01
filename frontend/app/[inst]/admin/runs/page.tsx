"use client";

import { RunsSection } from "@/components/admin/sections/runs-section";
import { useInstitution } from "@/hooks/use-institution";

export default function InstAdminRunsPage() {
  const inst = useInstitution();
  return <RunsSection inst={inst} basePath={`/${inst}/admin`} />;
}
