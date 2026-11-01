"use client";

import Link from "next/link";

import { LoginForm } from "@/components/admin/login-form";
import { IdentitiesPanel } from "@/components/admin/identities-table";
import { RunsTable } from "@/components/admin/runs-table";
import { InstitutionSettingsForm } from "@/components/admin/settings-forms";
import { WorkIdentitiesPanel } from "@/components/admin/work-identities-table";
import { Button } from "@/components/ui/button";
import { useAdminResource } from "@/hooks/use-admin-resource";
import { useInstitutionsDirectory } from "@/hooks/use-api";
import { useInstitution } from "@/hooks/use-institution";
import { useAdminToken, type AdminRun } from "@/lib/admin";

/** Per-university admin: this uni's harvest runs + its institution settings. */
export default function InstAdminPage() {
  const inst = useInstitution();
  const [token, setToken] = useAdminToken();
  const logout = () => setToken(null);
  const directory = useInstitutionsDirectory();
  const uni = directory.data?.find((i) => i.code === inst);
  const runs = useAdminResource<AdminRun[]>(
    `/runs?limit=100&institution=${encodeURIComponent(inst)}`,
    token ?? "",
    logout,
    "runs",
  );

  if (!token) return <LoginForm onToken={setToken} />;

  return (
    <div className="mx-auto max-w-5xl space-y-10">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Admin — {uni?.short_name ?? uni?.name ?? inst}</h1>
        <div className="flex items-center gap-2">
          <Link href="/admin" className="text-sm underline-offset-2 hover:underline">
            Full admin
          </Link>
          <Button variant="outline" onClick={() => setToken(null)}>
            Sign out
          </Button>
        </div>
      </div>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Harvest runs (newest first)</h2>
        {runs.error && <p className="text-sm text-destructive">{runs.error}</p>}
        <RunsTable runs={runs.data ?? []} directory={uni ? [uni] : []} />
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Author identity review</h2>
        <p className="text-sm text-[var(--muted-foreground)]">
          Resolution rows from the identity cascade. Confirming or rejecting is sticky across
          re-runs; flips reach the public author pages at the next authors ingest. Every flip is
          audited.
        </p>
        <IdentitiesPanel token={token} inst={inst} onUnauthorized={logout} />
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Work identity review</h2>
        <p className="text-sm text-[var(--muted-foreground)]">
          Cross-source links between local works and OpenAlex/OpenAIRE records. Flips are durable
          (harvests never overwrite existing rows) and audited; &lsquo;Miss&rsquo; marks a recorded
          lookup gap, not a bad link.
        </p>
        <WorkIdentitiesPanel token={token} inst={inst} onUnauthorized={logout} />
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Institution settings</h2>
        <InstitutionSettingsForm token={token} code={inst} onUnauthorized={logout} />
      </section>
    </div>
  );
}
