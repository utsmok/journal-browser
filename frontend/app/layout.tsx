import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Journal Browser",
  description:
    "Find the best home for your next article: open access deals, publication statistics, and journal information.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
