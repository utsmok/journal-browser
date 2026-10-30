"use client";

import { useEffect, useState } from "react";

import { LoginForm } from "@/components/admin/login-form";
import { RunsTable } from "@/components/admin/runs-table";
import { InstitutionSettingsForm } from "@/components/admin/settings-forms";
import { Button } from "@/components/ui/button";
import { useInstitutionsDirectory } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { AdminError, adminGet, useAdminToken, type AdminRun } from "@/lib/admin";

/** Per-university admin: this uni's harvest runs + its institution settings. */
export default function InstAdminPage() {
  const inst = useInstitution();
  const [token, setToken] = useAdminToken();
  const [runs, setRuns] = useState<AdminRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const directory = useInstitutionsDirectory();
  const uni = directory.data?.find((i) => i.code === inst);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    adminGet<AdminRun[]>(`/runs?limit=100&institution=${encodeURIComponent(inst)}`, token)
      .then((r) => {
        if (cancelled) return;
        setRuns(r);
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof AdminError && err.status === 401) {
          setToken(null);
          return;
        }
        setError(`Could not load runs (${err instanceof Error ? err.message : err}).`);
      });
    return () => {
      cancelled = true;
    };
  }, [token, inst, setToken]);

  if (!token) return <LoginForm onToken={setToken} />;

  return (
    <div className="mx-auto max-w-5xl space-y-10">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Admin — {uni?.short_name ?? uni?.name ?? inst}</h1>
        <Button variant="outline" onClick={() => setToken(null)}>
          Sign out
        </Button>
      </div>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Harvest runs (newest first)</h2>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <RunsTable runs={runs} directory={uni ? [uni] : []} />
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Institution settings</h2>
        <InstitutionSettingsForm token={token} code={inst} onUnauthorized={setToken} />
      </section>
    </div>
  );
}
