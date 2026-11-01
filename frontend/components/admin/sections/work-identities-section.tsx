"use client";

import { useState } from "react";

import { PageHeader } from "@/components/admin/admin-shell";
import { InstitutionSelect } from "@/components/admin/institution-select";
import { WorkIdentitiesPanel } from "@/components/admin/work-identities-table";
import { useAdminToken } from "@/lib/admin";

/** Work identity review across every institution (or one, locked). */
export function WorkIdentitiesSection({ inst }: { inst?: string }) {
  const [token, setToken] = useAdminToken();
  const [picked, setPicked] = useState("all");
  const scope = inst ?? (picked === "all" ? undefined : picked);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Work identities"
        lede="Confirm or mark missing cross-source work links. Click a row for the full record; flips are durable, audited, and never overwritten by harvests."
      />
      {!inst && (
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="work-identities-inst">Institution</label>
          <InstitutionSelect
            id="work-identities-inst"
            value={picked}
            onChange={setPicked}
            allLabel="All"
          />
        </div>
      )}
      <WorkIdentitiesPanel token={token ?? ""} inst={scope} onUnauthorized={() => setToken(null)} />
    </div>
  );
}
