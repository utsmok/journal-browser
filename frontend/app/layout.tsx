import type { Metadata } from "next";
import { Inter, Montserrat } from "next/font/google";
import "./globals.css";

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
    template: "%s | Journal Browser",
  },
  description:
    "Find the best home for your next article: open access deals, publication statistics, and journal information.",
};

function SiteHeader() {
  return (
    <header className="bg-[var(--secondary)] text-[var(--secondary-foreground)]">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4">
        <a href="/" className="font-heading text-lg font-bold tracking-tight">
          Journal Browser
        </a>
        <nav className="flex items-center gap-6 text-sm">
          <a href="/" className="hover:text-white/80">
            Search
          </a>
          <a href="/deals" className="hover:text-white/80">
            Deals
          </a>
          <a href="/about" className="hover:text-white/80">
            About
          </a>
        </nav>
      </div>
    </header>
  );
}

function SiteFooter() {
  return (
    <footer className="mt-auto bg-[var(--secondary)] text-[var(--secondary-foreground)]">
      <div className="mx-auto max-w-6xl px-4 py-6 text-sm">
        <p>
          Data: OpenAlex, cOAlition S Journal Checker Tool, openaccess.nl, OpenAPC,
          Scimago. Links on every page lead to the upstream source.
        </p>
      </div>
    </footer>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${montserrat.variable}`}>
      <body className="flex min-h-screen flex-col font-sans antialiased">
        <Providers>
          <SiteHeader />
          <main className="flex-1">{children}</main>
          <SiteFooter />
        </Providers>
      </body>
    </html>
  );
}
