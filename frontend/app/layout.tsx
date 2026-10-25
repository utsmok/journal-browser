import type { Metadata } from "next";
import { Inter, Montserrat } from "next/font/google";
import Link from "next/link";
import "./globals.css";

import { SiteFooter } from "@/components/site-footer";
import { ThemeToggle } from "@/components/theme-toggle";
import { NavLink } from "@/components/nav-link";
import { Providers } from "./providers";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const montserrat = Montserrat({
  subsets: ["latin"],
  variable: "--font-montserrat",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Journal Browser",
    template: "%s — Journal Browser",
  },
  description:
    "Find the best home for your next article: open access deals, publication statistics, and journal information.",
};

// Runs before first paint: no flash of the wrong theme on reload.
const THEME_SCRIPT = `(function(){try{var m=localStorage.getItem("jb-theme");if(m!=="light"&&m!=="dark")m="system";var d=m==="dark"||(m==="system"&&window.matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.classList.toggle("dark",d);}catch(e){}})();`;

function SiteHeader() {
  return (
    <header className="bg-[var(--secondary)] text-[var(--secondary-foreground)]">
      <div className="mx-auto flex h-16 max-w-screen-2xl items-center justify-between gap-3 px-4">
        <Link
          href="/"
          className="font-heading whitespace-nowrap text-base sm:text-lg font-bold tracking-tight"
        >
          Journal Browser
        </Link>
        <nav
          aria-label="Main"
          className="flex items-center gap-4 sm:gap-6 text-sm"
        >
          <NavLink href="/" label="Search" />
          <NavLink href="/deals" label="Deals" />
          <NavLink href="/about" label="About" />
        </nav>
        <ThemeToggle />
      </div>
    </header>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${montserrat.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="flex min-h-screen flex-col font-sans antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-[var(--radius)] focus:bg-[var(--card)] focus:px-3 focus:py-2 focus:text-sm focus:shadow-md"
        >
          Skip to content
        </a>
        <Providers>
          <SiteHeader />
          <main id="main" className="flex-1">{children}</main>
          <SiteFooter />
        </Providers>
      </body>
    </html>
  );
}
