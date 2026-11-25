"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import * as React from "react";
import { useTranslations } from "next-intl";

const STORAGE_KEY = "jb-theme";
const MODES = ["light", "dark", "system"] as const;
type Mode = (typeof MODES)[number];

const NEXT_MODE: Record<Mode, Mode> = { light: "dark", dark: "system", system: "light" };

const LABEL_KEYS: Record<Mode, string> = {
  light: "theme.switchToLight",
  dark: "theme.switchToDark",
  system: "theme.switchToSystem",
};

function apply(mode: Mode) {
  const dark =
    mode === "dark" ||
    (mode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

const ICONS = { light: Sun, dark: Moon, system: Monitor } as const;

/**
 * Cycles light -> dark -> system, persists to localStorage["jb-theme"], and
 * applies the class immediately. The pre-paint inline script in layout.tsx
 * owns the initial state; this only changes it. Below the `lg` breakpoint it
 * is a labelled row of the menu drawer; from `lg` it is an icon button in
 * the header bar.
 */
export function ThemeToggle() {
  const t = useTranslations("common");
  const [mode, setMode] = React.useState<Mode>("system");

  React.useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    setMode(MODES.includes(stored as Mode) ? (stored as Mode) : "system");
  }, []);

  // Follow the OS while in system mode so the theme tracks without a reload.
  React.useEffect(() => {
    if (mode !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => apply("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [mode]);

  const cycle = () => {
    const next = NEXT_MODE[mode];
    localStorage.setItem(STORAGE_KEY, next);
    apply(next);
    setMode(next);
  };

  const Icon = ICONS[mode];
  return (
    <button
      type="button"
      onClick={cycle}
      aria-label={t(LABEL_KEYS[mode])}
      title={t("theme.label", { mode })}
      className="inline-flex min-h-11 w-full items-center justify-start gap-2 rounded-[var(--radius)] px-3 text-base font-medium text-white/90 hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70 lg:size-8 lg:min-h-0 lg:justify-center lg:px-0"
    >
      <Icon aria-hidden className="size-4" />
      <span className="lg:hidden">{t("theme.label", { mode })}</span>
    </button>
  );
}
