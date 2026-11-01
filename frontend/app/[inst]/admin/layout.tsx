"use client";

import { AdminShell } from "@/components/admin/admin-shell";
import { LoginForm } from "@/components/admin/login-form";
import { useInstitution } from "@/hooks/use-institution";
import { useAdminToken } from "@/lib/admin";

/**
 * Login gate + chrome for the per-institution admin mirror. Same sections
 * as /admin, scoped to this institution via the basePath-prefixed routes.
 */
export default function InstAdminLayout({ children }: { children: React.ReactNode }) {
  const inst = useInstitution();
  const [token, setToken] = useAdminToken();
  if (!token) {
    return (
      <div className="mx-auto max-w-sm px-4 py-16">
        <LoginForm onToken={setToken} />
      </div>
    );
  }
  return (
    <AdminShell
      basePath={`/${inst}/admin`}
      brand={`Journal admin — ${inst}`}
      onSignOut={() => setToken(null)}
    >
      {children}
    </AdminShell>
  );
}
