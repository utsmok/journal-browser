"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/admin/admin-shell";
import { InstitutionSelect } from "@/components/admin/institution-select";
import { RunDrawer } from "@/components/admin/run-drawer";
import { RunsTable } from "@/components/admin/runs-table";
import { Button } from "@/components/ui/button";
import { useAdminResource } from "@/hooks/use-admin-resource";
import { useAdminToken, type AdminRun } from "@/lib/admin";

/** All harvest runs with institution scoping and a failed-only toggle. */
export function RunsSection({ inst, basePath }: { inst?: string; basePath: string }) {
  const t = useTranslations("admin");
  void basePath;
  const [token, setToken] = useAdminToken();
  const logout = () => setToken(null);
  const [picked, setPicked] = useState("all");
  const [failedOnly, setFailedOnly] = useState(false);
  const [selectedRun, setSelectedRun] = useState<AdminRun | null>(null);

  const scopeInst = inst ?? (picked === "all" ? undefined : picked);
  const instQ = scopeInst ? `&institution=${encodeURIComponent(scopeInst)}` : "";
  const runs = useAdminResource<AdminRun[]>(
    `/runs?limit=200${instQ}`,
    token ?? "",
    logout,
    "harvest runs",
  );
  const rows = (runs.data ?? []).filter((run) => !failedOnly || run.status === "failed");

  return (
    <div className="space-y-6">
      <PageHeader title={t("runs.title")} lede={t("runs.lede")}>
        <Button variant="outline" size="sm" onClick={() => void runs.refresh()}>
          {t("refresh")}
        </Button>
      </PageHeader>

      <div className="flex flex-wrap items-center gap-4 text-sm">
        {!inst && (
          <div className="flex items-center gap-2">
            <label htmlFor="runs-inst">{t("runs.institutionLabel")}</label>
            <InstitutionSelect
              id="runs-inst"
              value={picked}
              onChange={setPicked}
              allLabel={t("all")}
            />
          </div>
        )}
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={failedOnly}
            onChange={(event) => setFailedOnly(event.target.checked)}
          />
          {t("runs.failedOnly")}
        </label>
        <span className="text-muted-foreground" aria-live="polite">
          {runs.loading ? t("loading") : t("runs.runsCount", { count: rows.length })}
        </span>
      </div>

      {runs.error && <p className="text-sm text-destructive">{runs.error}</p>}
      <RunsTable runs={rows} onRowClick={setSelectedRun} />

      {selectedRun && <RunDrawer run={selectedRun} onClose={() => setSelectedRun(null)} />}
    </div>
  );
}
