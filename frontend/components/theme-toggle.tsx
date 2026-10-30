"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import * as React from "react";

const STORAGE_KEY = "jb-theme";
const MODES = ["light", "dark", "system"] as const;
type Mode = (typeof MODES)[number];

const NEXT_META: Record<Mode, { next: Mode; label: string }> = {
  light: { next: "dark", label: "Switch to dark mode" },
  dark: { next: "system", label: "Switch to system theme" },
  system: { next: "light", label: "Switch to light mode" },
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
 * owns the initial state; this only changes it.
 */
export function ThemeToggle() {
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
    const next = NEXT_META[mode].next;
    localStorage.setItem(STORAGE_KEY, next);
    apply(next);
    setMode(next);
  };

  const Icon = ICONS[mode];
  return (
    <button
      type="button"
      onClick={cycle}
      aria-label={NEXT_META[mode].label}
      title={`Theme: ${mode}`}
      className="inline-flex size-8 items-center justify-center rounded-[var(--radius)] text-white/90 hover:bg-white/10 hover:text-white"
    >
      <Icon aria-hidden className="size-4" />
    </button>
  );
}
