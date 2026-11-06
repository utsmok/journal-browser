import type { Metadata } from "next";

export const metadata: Metadata = {
  title: { default: "Authors", template: "%s — OJB" },
};

export default function AuthorsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
