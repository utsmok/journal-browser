import type { Metadata } from "next";
import { Inter, Montserrat } from "next/font/google";
import "./globals.css";

import { SiteFooter } from "@/components/site-footer";
import { BrandLink, SiteNav } from "@/components/site-nav";
import { ThemeToggle } from "@/components/theme-toggle";
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


// Runtime env (same JB_* vars the backend reads) so the server render
// already names this stack's institution instead of flashing the Twente
// default until /meta hydrates. force-dynamic: a build-time prerender would
// bake the image-build environment instead.
export const dynamic = "force-dynamic";

const SITE_FALLBACK = {
  name: process.env.JB_INSTITUTION_NAME ?? "University of Twente",
  short: process.env.JB_INSTITUTION_SHORT ?? "Twente",
  libraryUrl:
    process.env.JB_LIBRARY_URL ?? "https://www.utwente.nl/library",
  oaGuideUrl:
    process.env.JB_OA_GUIDE_URL ??
    "https://www.utwente.nl/en/service-portal/university-library/publication-archiving/open-access",
  supportEmail:
    process.env.JB_SUPPORT_EMAIL ?? "open-access@utwente.nl",
  adminContact: process.env.JB_ADMIN_CONTACT || null,
  researchPortalUrl:
    process.env.JB_RESEARCH_PORTAL_URL ?? "https://research.utwente.nl",
};

// Runs before first paint: no flash of the wrong theme on reload.
const THEME_SCRIPT = `(function(){try{var m=localStorage.getItem("jb-theme");if(m!=="light"&&m!=="dark")m="system";var d=m==="dark"||(m==="system"&&window.matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.classList.toggle("dark",d);}catch(e){}})();`;

function SiteHeader() {
  return (
    <header className="bg-[var(--secondary)] text-[var(--secondary-foreground)]">
      <div className="mx-auto flex h-16 max-w-screen-2xl items-center justify-between gap-3 px-4">
        <BrandLink />
        <SiteNav />
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
        <Providers siteFallback={SITE_FALLBACK}>
          <SiteHeader />
          <main id="main" className="flex-1">{children}</main>
          <SiteFooter />
        </Providers>
      </body>
    </html>
  );
}
