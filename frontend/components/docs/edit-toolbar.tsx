"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AdminError, adminLogin } from "@/lib/admin";

/**
 * Floating docs toolbar (hidden in print): admin sign-in, the editing
 * on/off toggle, and "Save as PDF". Sits above the feedback button and
 * shares its sessionStorage token with /admin.
 */
export function EditToolbar({
  token,
  onToken,
  editing,
  setEditing,
  authError,
}: {
  token: string | null;
  onToken: (token: string | null) => void;
  editing: boolean;
  setEditing: (on: boolean) => void;
  authError: string | null;
}) {
  const [loginOpen, setLoginOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function signIn(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      onToken(await adminLogin(password));
      setLoginOpen(false);
      setPassword("");
      setEditing(true);
    } catch (err) {
      setError(
        err instanceof AdminError && err.status === 403
          ? "Wrong password (or admin disabled)."
          : "Sign-in failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed bottom-20 right-4 z-50 flex flex-col items-end gap-2 print:hidden sm:bottom-24 sm:right-6">
      {authError && (
        <p className="max-w-64 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-xs text-destructive shadow">
          {authError}
        </p>
      )}
      {token && (
        <Button
          size="sm"
          variant={editing ? "default" : "outline"}
          onClick={() => setEditing(!editing)}
        >
          Editing: {editing ? "on" : "off"}
        </Button>
      )}
      {loginOpen ? (
        <form
          onSubmit={signIn}
          className="flex w-56 flex-col gap-2 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-3 shadow-lg"
        >
          <Input
            type="password"
            autoFocus
            aria-label="Admin password"
            placeholder="Admin password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="h-8 text-sm"
          />
          <div className="flex gap-2">
            <Button type="submit" size="sm" className="flex-1" disabled={busy}>
              Sign in
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                setLoginOpen(false);
                setError(null);
              }}
            >
              Cancel
            </Button>
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </form>
      ) : (
        <div className="flex gap-2">
          {!token && (
            <Button
              size="sm"
              variant="outline"
              className="shadow"
              onClick={() => setLoginOpen(true)}
            >
              Edit
            </Button>
          )}
          <Button size="sm" variant="outline" className="shadow" onClick={() => window.print()}>
            Save as PDF
          </Button>
        </div>
      )}
    </div>
  );
}
