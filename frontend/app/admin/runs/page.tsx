"use client";

import { useState } from "react";

import { PageHeader } from "@/components/admin/admin-shell";
import { InstitutionSelect } from "@/components/admin/institution-select";
import { RunsTable } from "@/components/admin/runs-table";
import { Button } from "@/components/ui/button";
import { useAdminResource } from "@/hooks/use-admin-resource";
import { useAdminToken, type AdminRun } from "@/lib/admin";

/** All harvest runs with institution scoping and a failed-only toggle. */
export default function AdminRunsPage() {
  const [token, setToken] = useAdminToken();
  const logout = () => setToken(null);
  const [inst, setInst] = useState("all");
  const [failedOnly, setFailedOnly] = useState(false);

  const instQ = inst === "all" ? "" : `&institution=${encodeURIComponent(inst)}`;
  const runs = useAdminResource<AdminRun[]>(
    `/runs?limit=200${instQ}`,
    token ?? "",
    logout,
    "harvest runs",
  );
  const rows = (runs.data ?? []).filter((run) => !failedOnly || run.status === "failed");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Harvest runs"
        lede="Newest first. Failed runs keep their error stats; superseded stale runs are marked failed."
      >
        <Button variant="outline" size="sm" onClick={() => void runs.refresh()}>
          Refresh
        </Button>
      </PageHeader>

      <div className="flex flex-wrap items-center gap-4 text-sm">
        <div className="flex items-center gap-2">
          <label htmlFor="runs-inst">Institution</label>
          <InstitutionSelect id="runs-inst" value={inst} onChange={setInst} allLabel="All" />
        </div>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={failedOnly}
            onChange={(event) => setFailedOnly(event.target.checked)}
          />
          Failed only
        </label>
        <span className="text-muted-foreground" aria-live="polite">
          {runs.loading ? "loading…" : `${rows.length.toLocaleString("en")} runs`}
        </span>
      </div>

      {runs.error && <p className="text-sm text-destructive">{runs.error}</p>}
      <RunsTable runs={rows} />
    </div>
  );
}
