"use client";

import { useEffect, useState } from "react";

import { PageHeader } from "@/components/admin/admin-shell";
import { InstitutionSelect } from "@/components/admin/institution-select";
import { InstitutionSettingsForm } from "@/components/admin/settings-forms";
import { useInstitutionsDirectory } from "@/hooks/use-api";
import { useAdminToken } from "@/lib/admin";

/** Per-university settings behind one picker. */
export default function AdminInstitutionsPage() {
  const [token, setToken] = useAdminToken();
  const [code, setCode] = useState("");
  const directory = useInstitutionsDirectory();

  // Keep the picker on a real university once the directory arrives.
  useEffect(() => {
    const unis = directory.data ?? [];
    if (unis.length > 0 && !unis.some((inst) => inst.code === code)) {
      setCode(unis[0].code);
    }
  }, [directory.data, code]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Institution settings"
        lede="Per-university display name, short name, and ROR id."
      />
      <div className="flex items-center gap-2 text-sm">
        <label htmlFor="inst-settings-picker">University</label>
        <InstitutionSelect id="inst-settings-picker" value={code} onChange={setCode} />
      </div>
      {code !== "" && (
        <InstitutionSettingsForm
          key={code}
          token={token ?? ""}
          code={code}
          onUnauthorized={setToken}
        />
      )}
    </div>
  );
}
