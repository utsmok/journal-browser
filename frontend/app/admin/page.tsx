"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type Run = {
  id: number;
  source: string;
  entity_type: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  stats: Record<string, unknown>;
};

type FlaggedDeal = {
  id: number;
  publisher: string;
  esac_id: string | null;
  status: string;
  duration: string | null;
  journals: number;
  reason: string | null;
};

type Settings = Record<string, string | number | boolean>;

async function adminGet<T>(path: string, token: string): Promise<T> {
  const res = await fetch(`/api/v1/admin${path}`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`${res.status} on ${path}`);
  return (await res.json()) as T;
}

function StatusBadge({ status }: { status: string }) {
  const variant =
    status === "completed" ? "secondary" : status === "failed" ? "outline" : "muted";
  return <Badge variant={variant}>{status}</Badge>;
}

export default function AdminPage() {
  const [token, setToken] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [flagged, setFlagged] = useState<FlaggedDeal[]>([]);
  const [settings, setSettings] = useState<Settings>({});

  useEffect(() => {
    setToken(sessionStorage.getItem("jb-admin-token"));
  }, []);

  const logout = useCallback(() => {
    sessionStorage.removeItem("jb-admin-token");
    setToken(null);
  }, []);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    Promise.all([
      adminGet<Run[]>("/runs?limit=100", token),
      adminGet<FlaggedDeal[]>("/flagged", token),
      adminGet<Settings>("/settings", token),
    ])
      .then(([r, f, s]) => {
        if (cancelled) return;
        setRuns(r);
        setFlagged(f);
        setSettings(s);
      })
      .catch((err) => {
        if (cancelled) return;
        sessionStorage.removeItem("jb-admin-token");
        setToken(null);
        setError(String(err.message ?? err));
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (!token) {
    return (
      <div className="mx-auto mt-20 max-w-sm space-y-4">
        <h1 className="text-xl font-semibold">Admin</h1>
        <p className="text-sm text-muted-foreground">
          Harvest runs, errors, and the effective configuration. Password via
          JB_ADMIN_PASSWORD; the panel is disabled when it is unset.
        </p>
        <form
          className="space-y-2"
          onSubmit={async (e) => {
            e.preventDefault();
            setError(null);
            const res = await fetch("/api/v1/admin/login", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ password }),
            });
            if (!res.ok) {
              setError(res.status === 403 ? "Wrong password (or admin disabled)." : String(res.status));
              return;
            }
            const { token: t } = (await res.json()) as { token: string };
            sessionStorage.setItem("jb-admin-token", t);
            setToken(t);
          }}
        >
          <Input
            type="password"
            aria-label="Admin password"
            placeholder="Admin password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Button type="submit" className="w-full">
            Sign in
          </Button>
        </form>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-10">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Admin</h1>
        <Button variant="outline" onClick={logout}>
          Sign out
        </Button>
      </div>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Harvest runs (newest first)</h2>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>#</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Started</TableHead>
              <TableHead>Stats</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {runs.map((run) => (
              <TableRow key={run.id}>
                <TableCell>{run.id}</TableCell>
                <TableCell>
                  {run.source}/{run.entity_type}
                </TableCell>
                <TableCell>
                  <StatusBadge status={run.status} />
                </TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground">
                  {run.started_at?.slice(0, 19).replace("T", " ")}
                </TableCell>
                <TableCell className="max-w-md truncate font-mono text-xs" title={JSON.stringify(run.stats)}>
                  {JSON.stringify(run.stats)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
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
                <TableCell className="max-w-md truncate text-muted-foreground" title={deal.reason ?? ""}>
                  {deal.reason ?? "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Effective settings (read-only)</h2>
        <p className="text-sm text-muted-foreground">
          Environment changes belong in <code>.env</code> plus a compose
          restart — never edited here, so the panel cannot drift from the
          deployment.
        </p>
        <Table>
          <TableBody>
            {Object.entries(settings).map(([key, value]) => (
              <TableRow key={key}>
                <TableCell className="font-mono text-xs">{key}</TableCell>
                <TableCell>
                  {typeof value === "boolean" ? (value ? "set" : "—") : String(value)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>
    </div>
  );
}
