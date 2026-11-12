"use client";

import { PageHeader } from "@/components/admin/admin-shell";
import { GlobalSettingsForm } from "@/components/admin/settings-forms";
import { useTranslations } from "next-intl";
import { useAdminToken } from "@/lib/admin";

/** Deployment-wide settings; secrets arrive masked and keep their value. */
export function SettingsSection() {
  const t = useTranslations("admin");
  const [token, setToken] = useAdminToken();

  return (
    <div className="space-y-6">
      <PageHeader title={t("settings.title")} lede={t("settings.lede")} />
      <GlobalSettingsForm token={token ?? ""} onUnauthorized={setToken} />
    </div>
  );
}
