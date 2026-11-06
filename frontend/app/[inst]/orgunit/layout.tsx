import type { Metadata } from "next";

export const metadata: Metadata = {
  title: { default: "Faculties", template: "%s — OJB" },
};

export default function OrgUnitsLayout({ children }: { children: React.ReactNode }) {
  return children;
}
