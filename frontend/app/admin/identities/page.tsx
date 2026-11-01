"use client";

import { useState } from "react";

import { PageHeader } from "@/components/admin/admin-shell";
import { IdentitiesPanel } from "@/components/admin/identities-table";
import { InstitutionSelect } from "@/components/admin/institution-select";
import { useAdminToken } from "@/lib/admin";

/** Author identity review across every institution (or one, scoped). */
export default function AdminIdentitiesPage() {
  const [token, setToken] = useAdminToken();
  const [inst, setInst] = useState("all");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Author identities"
        lede="Confirm or reject external identity candidates. Every flip is audited and sticky across re-runs."
      />
      <div className="flex items-center gap-2 text-sm">
        <label htmlFor="identities-inst">Institution</label>
        <InstitutionSelect id="identities-inst" value={inst} onChange={setInst} allLabel="All" />
      </div>
      <IdentitiesPanel
        token={token ?? ""}
        inst={inst === "all" ? undefined : inst}
        onUnauthorized={() => setToken(null)}
      />
    </div>
  );
}
