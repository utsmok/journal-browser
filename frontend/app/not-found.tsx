import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-24 text-center">
      <h1 className="text-3xl font-bold">Page not found</h1>
      <p className="mx-auto mt-2 max-w-prose text-[var(--muted-foreground)]">
        This address does not exist. Journal pages live at
        <code className="mx-1 rounded bg-[var(--muted)] px-1 py-0.5">
          /journals/&lt;issn&gt;
        </code>
        — search for the journal by title, ISSN, or topic instead.
      </p>
      <Link href="/" className={buttonVariants({ className: "mt-6" })}>
        Back to search
      </Link>
    </div>
  );
}
