"use client";

import { useState } from "react";

import { PageHeader } from "@/components/admin/admin-shell";
import { InstitutionSelect } from "@/components/admin/institution-select";
import { WorkIdentitiesPanel } from "@/components/admin/work-identities-table";
import { useAdminToken } from "@/lib/admin";

/** Work identity review across every institution (or one, scoped). */
export default function AdminWorkIdentitiesPage() {
  const [token, setToken] = useAdminToken();
  const [inst, setInst] = useState("all");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Work identities"
        lede="Confirm or mark missing cross-source work links. Every flip is audited."
      />
      <div className="flex items-center gap-2 text-sm">
        <label htmlFor="work-identities-inst">Institution</label>
        <InstitutionSelect
          id="work-identities-inst"
          value={inst}
          onChange={setInst}
          allLabel="All"
        />
      </div>
      <WorkIdentitiesPanel
        token={token ?? ""}
        inst={inst === "all" ? undefined : inst}
        onUnauthorized={() => setToken(null)}
      />
    </div>
  );
}
