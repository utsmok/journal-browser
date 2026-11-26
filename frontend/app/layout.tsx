import type { Metadata } from "next";
import { Inter, Montserrat } from "next/font/google";
import { getTranslations } from "next-intl/server";
import "./globals.css";

import { SiteFooter } from "@/components/site-footer";
import { AboutUtilityLink, BrandLink, SiteNav } from "@/components/site-nav";
import { ShortlistLink } from "@/components/shortlist/shortlist-link";
import { SiteMenu } from "@/components/site-menu";
import { ThemeToggle } from "@/components/theme-toggle";
import { YearFilterControl } from "@/components/year-filter";
import { FeedbackWidget } from "@/components/feedback/feedback-widget";
import { NavigationProgress } from "@/components/navigation-progress";
import { Seeds } from "@/components/seed";
import { SectionMessages } from "@/i18n/section-messages";
import { type FreshnessResponse, freshnessRequest } from "@/lib/api";
import { qk } from "@/lib/query-keys";
import { requestInst } from "@/lib/request-path";
import { fetchForRender, fetchInstitutions } from "@/lib/server-fetch";
import { SITE_URL } from "@/lib/site-url";
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

async function getMetadata(): Promise<Metadata> {
  const t = await getTranslations("common");
  return {
    metadataBase: new URL(SITE_URL),
    title: {
      default: t("appTitle"),
      // Next's own %s placeholder stays in the message string.
      template: t("appTitleTemplate"),
    },
    description: t("appDescription"),
    openGraph: {
      type: "website",
      siteName: t("appTitle"),
      images: [{ url: "/og-image.png", width: 1200, height: 630, alt: t("appTitle") }],
    },
    // Title, description and image carry over from openGraph.
    twitter: { card: "summary_large_image" },
  };
}

export const generateMetadata = getMetadata;

// Runtime env (same JB_* vars the backend reads) so the server render
// already names this stack's institution instead of flashing the Twente
// default until /meta hydrates. force-dynamic: a build-time prerender would
// bake the image-build environment instead.
export const dynamic = "force-dynamic";

const SITE_FALLBACK = {
  name: process.env.JB_INSTITUTION_NAME ?? "University of Twente",
  short: process.env.JB_INSTITUTION_SHORT ?? "Twente",
  libraryUrl: process.env.JB_LIBRARY_URL ?? "https://www.utwente.nl/library",
  oaGuideUrl:
    process.env.JB_OA_GUIDE_URL ??
    "https://www.utwente.nl/en/service-portal/university-library/publication-archiving/open-access",
  supportEmail: process.env.JB_SUPPORT_EMAIL ?? "open-access@utwente.nl",
  adminContact: process.env.JB_ADMIN_CONTACT || null,
  researchPortalUrl: process.env.JB_RESEARCH_PORTAL_URL ?? "https://research.utwente.nl",
};

// Runs before first paint: no flash of the wrong theme on reload.
const THEME_SCRIPT = `(function(){try{var m=localStorage.getItem("jb-theme");if(m!=="light"&&m!=="dark")m="system";var d=m==="dark"||(m==="system"&&window.matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.classList.toggle("dark",d);}catch(e){}})();`;

function SiteHeader() {
  return (
    <header className="bg-[var(--secondary)] text-[var(--secondary-foreground)]">
      {/* One bar at every width: from `lg` the nav and utilities sit inline,
          below it they live in the SiteMenu drawer. */}
      <div className="mx-auto flex min-h-14 max-w-screen-2xl items-center justify-between gap-x-3 px-4 py-1 lg:min-h-16 lg:flex-nowrap lg:gap-x-4 lg:py-0">
        <BrandLink />
        <SiteMenu>
          <SiteNav />
          <div className="flex flex-col gap-3 border-t border-white/15 pt-5 lg:flex-row lg:items-center lg:gap-3 lg:border-0 lg:pt-0">
            <YearFilterControl />
            <ShortlistLink />
            <AboutUtilityLink />
            <ThemeToggle />
          </div>
        </SiteMenu>
      </div>
    </header>
  );
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const inst = await requestInst();
  const [t, institutions, freshness] = await Promise.all([
    getTranslations("common"),
    fetchInstitutions(),
    inst ? fetchForRender<FreshnessResponse>(freshnessRequest(inst)) : null,
  ]);
  return (
    <html lang="en" className={`${inter.variable} ${montserrat.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="flex min-h-screen flex-col font-sans antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-[var(--radius)] focus:bg-[var(--card)] focus:px-3 focus:py-2 focus:text-sm focus:shadow-md"
        >
          {t("skipToContent")}
        </a>
        <Providers siteFallback={SITE_FALLBACK}>
          {/* Seeded above the header: the shell reads the institution
              directory and the institution's freshness (site meta, footer
              update notice), and a boundary below it would hydrate after
              the header had already started its own fetches. */}
          <Seeds
            entries={[
              { queryKey: qk.institutions(), data: institutions },
              { queryKey: qk.freshness(inst), data: freshness },
            ]}
          >
            {/* The shell (header, footer, shared widgets) reads only "common";
              each section layout adds its own namespaces around its pages. */}
            <SectionMessages>
              <NavigationProgress />
              <SiteHeader />
              <main id="main" className="flex-1">
                {children}
                {/* In the flow on phones and tablets, so it never covers content;
                  a floating button from lg. */}
                <FeedbackWidget />
              </main>
              <SiteFooter />
            </SectionMessages>
          </Seeds>
        </Providers>
      </body>
    </html>
  );
}
