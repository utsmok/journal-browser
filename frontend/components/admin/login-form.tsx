"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AdminError, adminLogin } from "@/lib/admin";

/** Password gate shared by /admin and /{code}/admin; stores nothing itself. */
export function LoginForm({ onToken }: { onToken: (token: string) => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="mx-auto mt-20 max-w-sm space-y-4">
      <h1 className="text-xl font-semibold">Admin</h1>
      <p className="text-sm text-muted-foreground">
        Harvest runs and configuration. Password via JB_ADMIN_PASSWORD; the
        panel is disabled when it is unset.
      </p>
      <form
        className="space-y-2"
        onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          try {
            onToken(await adminLogin(password));
          } catch (err) {
            setError(
              err instanceof AdminError && err.status === 403
                ? "Wrong password (or admin disabled)."
                : "Sign-in failed.",
            );
          }
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
