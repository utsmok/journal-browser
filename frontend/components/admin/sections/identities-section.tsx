"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/admin/admin-shell";
import { IdentitiesPanel } from "@/components/admin/identities-table";
import { InstitutionSelect } from "@/components/admin/institution-select";
import { useAdminToken } from "@/lib/admin";

/** Author identity review across every institution (or one, locked). */
export function IdentitiesSection({ inst }: { inst?: string }) {
  const t = useTranslations("admin");
  const [token, setToken] = useAdminToken();
  const [picked, setPicked] = useState("all");
  const scope = inst ?? (picked === "all" ? undefined : picked);

  return (
    <div className="space-y-6">
      <PageHeader title={t("identities.title")} lede={t("identities.lede")} />
      {!inst && (
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="identities-inst">{t("identities.institutionLabel")}</label>
          <InstitutionSelect
            id="identities-inst"
            value={picked}
            onChange={setPicked}
            allLabel={t("all")}
          />
        </div>
      )}
      <IdentitiesPanel token={token ?? ""} inst={scope} onUnauthorized={() => setToken(null)} />
    </div>
  );
}
