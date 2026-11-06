"use client";

import { AdminShell } from "@/components/admin/admin-shell";
import { LoginForm } from "@/components/admin/login-form";
import { useAdminToken } from "@/lib/admin";

/**
 * Login gate + chrome shared by the global and per-institution admin
 * sections. Renders the form until a token exists, so children only ever
 * mount authenticated. `basePath`/`brand` opt into the inst-scoped shell.
 */
export function AdminGate({
  children,
  basePath,
  brand,
}: {
  children: React.ReactNode;
  basePath?: string;
  brand?: string;
}) {
  const [token, setToken] = useAdminToken();
  if (!token) {
    return (
      <div className="mx-auto max-w-sm px-4 py-16">
        <LoginForm onToken={setToken} />
      </div>
    );
  }
  if (basePath) {
    return (
      <AdminShell basePath={basePath} brand={brand} onSignOut={() => setToken(null)}>
        {children}
      </AdminShell>
    );
  }
  return <AdminShell onSignOut={() => setToken(null)}>{children}</AdminShell>;
}
