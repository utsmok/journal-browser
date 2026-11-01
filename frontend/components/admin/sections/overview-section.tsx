"use client";

import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/admin/admin-shell";
import { RunDrawer } from "@/components/admin/run-drawer";
import { RunsTable } from "@/components/admin/runs-table";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAdminResource } from "@/hooks/use-admin-resource";
import { useAdminToken, type AdminRun, type AdminSummary, type FlaggedDeal } from "@/lib/admin";

function StatCard({
  href,
  label,
  value,
  warn,
}: {
  href: string;
  label: string;
  value: number | null;
  warn?: boolean;
}) {
  const tone = warn && (value ?? 0) > 0 ? "text-destructive" : "text-[var(--foreground)]";
  return (
    <Link
      href={href}
      className="rounded-[var(--radius)] border bg-[var(--card)] p-4 shadow-sm transition-colors hover:bg-[var(--muted)]"
    >
      <p className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
        {label}
      </p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone}`}>
        {value === null ? "…" : value.toLocaleString("en")}
      </p>
    </Link>
  );
}

/** Admin landing page: pipeline health counters plus recent activity. */
export function OverviewSection({ inst, basePath }: { inst?: string; basePath: string }) {
  const [token, setToken] = useAdminToken();
  const logout = () => setToken(null);
  const scope = inst ? `?institution=${encodeURIComponent(inst)}` : "";
  const summary = useAdminResource<AdminSummary>(
    `/summary${scope}`,
    token ?? "",
    logout,
    "summary",
  );
  const runs = useAdminResource<AdminRun[]>(
    `/runs?limit=8${inst ? `&institution=${encodeURIComponent(inst)}` : ""}`,
    token ?? "",
    logout,
    "recent runs",
  );
  const flagged = useAdminResource<FlaggedDeal[]>("/flagged", token ?? "", logout, "flagged deals");
  const [selectedRun, setSelectedRun] = useState<AdminRun | null>(null);

  const s = summary.data;
  const lastRun = s?.last_run;
  const flaggedRows = (flagged.data ?? []).slice(0, 6);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Overview"
        lede={
          inst
            ? `Pipeline health and open curation work for ${inst}.`
            : "Pipeline health and open curation work across all institutions."
        }
      />

      {summary.error && <p className="text-sm text-destructive">{summary.error}</p>}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatCard
          href={`${basePath}/runs`}
          label="Failed runs (24h)"
          value={s?.failed_runs_24h ?? null}
          warn
        />
        <StatCard href={`${basePath}/runs`} label="Running" value={s?.running_runs ?? null} warn />
        <StatCard
          href={`${basePath}/deals`}
          label="Flagged deals"
          value={s?.flagged_deals ?? null}
          warn
        />
        <StatCard
          href={`${basePath}/feedback`}
          label="Open feedback"
          value={s?.open_feedback ?? null}
          warn
        />
        <StatCard
          href={`${basePath}/identities`}
          label="Author candidates"
          value={s?.author_identity_candidates ?? null}
        />
        <StatCard
          href={`${basePath}/work-identities`}
          label="Work candidates"
          value={s?.work_identity_candidates ?? null}
        />
      </div>

      {!inst && (s?.flagged_deals ?? 0) > 0 && (
        <p className="text-xs text-muted-foreground">
          Deal and feedback counters are instance-global; run and candidate counters follow the
          institution scope of this page.
        </p>
      )}

      {lastRun && (
        <p className="text-sm text-muted-foreground">
          Last run:{" "}
          <span className="font-medium text-[var(--foreground)]">
            {lastRun.source} / {lastRun.entity_type}
          </span>{" "}
          — {lastRun.status}, started{" "}
          {lastRun.started_at ? new Date(lastRun.started_at).toLocaleString() : "—"}
          {lastRun.institution_code ? ` for ${lastRun.institution_code}` : ""}
        </p>
      )}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Recent harvest runs</h2>
          <Link href={`${basePath}/runs`} className="text-sm underline-offset-2 hover:underline">
            View all
          </Link>
        </div>
        {runs.error && <p className="text-sm text-destructive">{runs.error}</p>}
        <RunsTable runs={runs.data ?? []} onRowClick={setSelectedRun} />
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            Flagged deals{flagged.data ? ` (${flagged.data.length})` : ""}
          </h2>
          <Link href={`${basePath}/deals`} className="text-sm underline-offset-2 hover:underline">
            Review in deals
          </Link>
        </div>
        {flagged.error && <p className="text-sm text-destructive">{flagged.error}</p>}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Publisher</TableHead>
              <TableHead>ESAC</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Journals</TableHead>
              <TableHead>Reason</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {flaggedRows.map((deal) => (
              <TableRow key={deal.id}>
                <TableCell className="font-medium">{deal.publisher}</TableCell>
                <TableCell className="font-mono text-xs">{deal.esac_id ?? "—"}</TableCell>
                <TableCell>{deal.status}</TableCell>
                <TableCell className="tabular-nums">{deal.journals}</TableCell>
                <TableCell
                  className="max-w-md truncate text-muted-foreground"
                  title={deal.reason ?? ""}
                >
                  {deal.reason ?? "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>

      {selectedRun && <RunDrawer run={selectedRun} onClose={() => setSelectedRun(null)} />}
    </div>
  );
}
