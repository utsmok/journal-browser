"use client";

import { AdminShell } from "@/components/admin/admin-shell";
import { LoginForm } from "@/components/admin/login-form";
import { useAdminToken } from "@/lib/admin";

/**
 * Login gate + chrome for every /admin/* page. Section pages stay
 * token-less: the layout renders the form until a token exists, so children
 * only ever mount authenticated.
 */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useAdminToken();
  if (!token) {
    return (
      <div className="mx-auto max-w-sm px-4 py-16">
        <LoginForm onToken={setToken} />
      </div>
    );
  }
  return <AdminShell onSignOut={() => setToken(null)}>{children}</AdminShell>;
}
