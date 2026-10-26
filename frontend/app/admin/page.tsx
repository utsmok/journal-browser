"use client";

import { useEffect, useState } from "react";

import { LoginForm } from "@/components/admin/login-form";
import { RunsTable, StatusBadge } from "@/components/admin/runs-table";
import {
  GlobalSettingsForm,
  InstitutionSettingsForm,
} from "@/components/admin/settings-forms";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useInstitutionsDirectory } from "@/hooks/use-api";
import {
  AdminError,
  adminGet,
  useAdminToken,
  type AdminRun,
  type FlaggedDeal,
} from "@/lib/admin";

export default function AdminPage() {
  const [token, setToken] = useAdminToken();
  const [instFilter, setInstFilter] = useState<string>("all");
  const [selectedUni, setSelectedUni] = useState<string>("");
  const [runs, setRuns] = useState<AdminRun[]>([]);
  const [flagged, setFlagged] = useState<FlaggedDeal[]>([]);
  const [runsError, setRunsError] = useState<string | null>(null);
  const directory = useInstitutionsDirectory();
  const unis = directory.data ?? [];

  // Keep the institution-settings switcher on a real university.
  useEffect(() => {
    const codes = (directory.data ?? []).map((i) => i.code);
    if (codes.length > 0 && !codes.includes(selectedUni)) setSelectedUni(codes[0]);
  }, [directory.data, selectedUni]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    const instQ =
      instFilter === "all" ? "" : `&institution=${encodeURIComponent(instFilter)}`;
    Promise.all([
      adminGet<AdminRun[]>(`/runs?limit=100${instQ}`, token),
      adminGet<FlaggedDeal[]>("/flagged", token),
    ])
      .then(([r, f]) => {
        if (cancelled) return;
        setRuns(r);
        setFlagged(f);
        setRunsError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof AdminError && err.status === 401) {
          setToken(null);
          return;
        }
        setRunsError(`Could not load admin data (${err instanceof Error ? err.message : err}).`);
      });
    return () => {
      cancelled = true;
    };
  }, [token, instFilter, setToken]);

  if (!token) return <LoginForm onToken={setToken} />;

  return (
    <div className="mx-auto max-w-5xl space-y-10">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Admin</h1>
        <Button variant="outline" onClick={() => setToken(null)}>
          Sign out
        </Button>
      </div>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Harvest runs (newest first)</h2>
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="inst-filter" className="text-muted-foreground">
            Institution
          </label>
          <select
            id="inst-filter"
            className="rounded-[var(--radius)] border border-input bg-[var(--card)] px-2 py-1"
            value={instFilter}
            onChange={(e) => setInstFilter(e.target.value)}
          >
            <option value="all">All</option>
            {unis.map((i) => (
              <option key={i.code} value={i.code}>
                {i.short_name ?? i.name}
              </option>
            ))}
          </select>
        </div>
        {runsError && <p className="text-sm text-destructive">{runsError}</p>}
        <RunsTable runs={runs} directory={unis} />
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">
          Deals flagged for curation ({flagged.length})
        </h2>
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
            {flagged.map((deal) => (
              <TableRow key={deal.id}>
                <TableCell>{deal.publisher}</TableCell>
                <TableCell className="font-mono text-xs">{deal.esac_id ?? "—"}</TableCell>
                <TableCell>
                  <StatusBadge status={deal.status} />
                </TableCell>
                <TableCell>{deal.journals}</TableCell>
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

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Institution settings</h2>
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="inst-picker" className="text-muted-foreground">
            University
          </label>
          <select
            id="inst-picker"
            className="rounded-[var(--radius)] border border-input bg-[var(--card)] px-2 py-1"
            value={selectedUni}
            onChange={(e) => setSelectedUni(e.target.value)}
          >
            {unis.map((i) => (
              <option key={i.code} value={i.code}>
                {i.name}
              </option>
            ))}
          </select>
        </div>
        {selectedUni && (
          <InstitutionSettingsForm
            key={selectedUni}
            token={token}
            code={selectedUni}
            onUnauthorized={setToken}
          />
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Global settings</h2>
        <GlobalSettingsForm token={token} onUnauthorized={setToken} />
      </section>
    </div>
  );
}
