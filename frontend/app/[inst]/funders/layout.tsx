import type { Metadata } from "next";

export const metadata: Metadata = {
  title: { default: "Funders", template: "%s — OJB" },
};

export default function FundersLayout({ children }: { children: React.ReactNode }) {
  return children;
}
