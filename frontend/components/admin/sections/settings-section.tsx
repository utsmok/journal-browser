"use client";

import { PageHeader } from "@/components/admin/admin-shell";
import { GlobalSettingsForm } from "@/components/admin/settings-forms";
import { useAdminToken } from "@/lib/admin";

/** Deployment-wide settings; secrets arrive masked and keep their value. */
export function SettingsSection() {
  const [token, setToken] = useAdminToken();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Global settings"
        lede="Deployment-wide switches and secrets. Masked secrets keep their stored value unless you type a new one."
      />
      <GlobalSettingsForm token={token ?? ""} onUnauthorized={setToken} />
    </div>
  );
}
