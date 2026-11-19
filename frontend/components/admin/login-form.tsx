"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AdminError, adminLogin } from "@/lib/admin";

/** Password gate shared by /admin and /{code}/admin; stores nothing itself. */
export function LoginForm({ onToken }: { onToken: (token: string) => void }) {
  const t = useTranslations("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  return (
    // Roughly centers the card between the site header and footer.
    <div className="flex min-h-[calc(100dvh-21rem)] flex-col justify-center">
      <div className="mx-auto w-full max-w-sm space-y-4">
        <h1 className="text-xl font-semibold">{t("login.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("login.description")}</p>
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
                  ? t("login.wrongPassword")
                  : t("login.signInFailed"),
              );
            }
          }}
        >
          <Input
            type="password"
            aria-label={t("login.passwordLabel")}
            placeholder={t("login.passwordPlaceholder")}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Button type="submit" className="w-full">
            {t("login.signIn")}
          </Button>
        </form>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </div>
    </div>
  );
}
