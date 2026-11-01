"use client";

import { useState } from "react";

import { PageHeader } from "@/components/admin/admin-shell";
import { IdentitiesPanel } from "@/components/admin/identities-table";
import { InstitutionSelect } from "@/components/admin/institution-select";
import { useAdminToken } from "@/lib/admin";

/** Author identity review across every institution (or one, locked). */
export function IdentitiesSection({ inst }: { inst?: string }) {
  const [token, setToken] = useAdminToken();
  const [picked, setPicked] = useState("all");
  const scope = inst ?? (picked === "all" ? undefined : picked);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Author identities"
        lede="Confirm or reject external identity candidates. Click a row for the side-by-side comparison (local Pure profile vs external record, recent works, cascade evidence); flips are sticky and audited."
      />
      {!inst && (
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="identities-inst">Institution</label>
          <InstitutionSelect
            id="identities-inst"
            value={picked}
            onChange={setPicked}
            allLabel="All"
          />
        </div>
      )}
      <IdentitiesPanel token={token ?? ""} inst={scope} onUnauthorized={() => setToken(null)} />
    </div>
  );
}
