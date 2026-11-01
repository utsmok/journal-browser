"use client";

import { useEffect, useState } from "react";

import { PageHeader } from "@/components/admin/admin-shell";
import { InstitutionSelect } from "@/components/admin/institution-select";
import { InstitutionSettingsForm } from "@/components/admin/settings-forms";
import { useInstitutionsDirectory } from "@/hooks/use-api";
import { useAdminToken } from "@/lib/admin";

/** Per-university settings: locked to one institution, or behind a picker. */
export function InstitutionsSection({ inst }: { inst?: string }) {
  const [token, setToken] = useAdminToken();
  const [picked, setPicked] = useState("");
  const directory = useInstitutionsDirectory();
  const code = inst ?? picked;

  // Keep the picker on a real university once the directory arrives.
  useEffect(() => {
    const unis = directory.data ?? [];
    if (!inst && unis.length > 0 && !unis.some((entry) => entry.code === picked)) {
      setPicked(unis[0].code);
    }
  }, [directory.data, picked, inst]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Institution settings"
        lede="Per-university display name, short name, and ROR id."
      />
      {!inst && (
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="inst-settings-picker">University</label>
          <InstitutionSelect id="inst-settings-picker" value={picked} onChange={setPicked} />
        </div>
      )}
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
