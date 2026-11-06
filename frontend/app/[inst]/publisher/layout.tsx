import type { Metadata } from "next";

export const metadata: Metadata = {
  title: { default: "Publishers", template: "%s — OJB" },
};

export default function PublishersLayout({ children }: { children: React.ReactNode }) {
  return children;
}
