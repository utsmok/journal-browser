"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/admin/admin-shell";
import { InstitutionSelect } from "@/components/admin/institution-select";
import { WorkIdentitiesPanel } from "@/components/admin/work-identities-table";
import { useAdminToken } from "@/lib/admin";

/** Work identity review across every institution (or one, locked). */
export function WorkIdentitiesSection({ inst }: { inst?: string }) {
  const t = useTranslations("admin");
  const [token, setToken] = useAdminToken();
  const [picked, setPicked] = useState("all");
  const scope = inst ?? (picked === "all" ? undefined : picked);

  return (
    <div className="space-y-6">
      <PageHeader title={t("workIdentities.title")} lede={t("workIdentities.lede")} />
      {!inst && (
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="work-identities-inst">{t("workIdentities.institutionLabel")}</label>
          <InstitutionSelect
            id="work-identities-inst"
            value={picked}
            onChange={setPicked}
            allLabel={t("all")}
          />
        </div>
      )}
      <WorkIdentitiesPanel token={token ?? ""} inst={scope} onUnauthorized={() => setToken(null)} />
    </div>
  );
}
