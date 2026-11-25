import type { Metadata } from "next";

import { SectionMessages } from "@/i18n/section-messages";

// A shortlist lives in the visitor's own browser; search engines have nothing
// to index here.
export const metadata: Metadata = { robots: { index: false, follow: true } };

export default function ShortlistLayout({ children }: { children: React.ReactNode }) {
  return <SectionMessages namespaces={["shortlist", "home"]}>{children}</SectionMessages>;
}
