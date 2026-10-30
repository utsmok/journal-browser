import type { Metadata } from "next";

const API = process.env.API_PROXY_URL || "http://localhost:8000";

/** Per-journal document title; falls back to the layout default on failure. */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ issn_l: string }>;
}): Promise<Metadata> {
  const { issn_l } = await params;
  try {
    const res = await fetch(`${API}/api/v1/journals/${encodeURIComponent(issn_l)}`, {
      cache: "no-store",
    });
    if (res.ok) {
      const data = (await res.json()) as {
        journal?: { title?: string | null };
      };
      if (data.journal?.title) return { title: data.journal.title };
    }
  } catch {
    // Document title is cosmetic; the page still renders.
  }
  return {};
}

export default function JournalLayout({ children }: { children: React.ReactNode }) {
  return children;
}
