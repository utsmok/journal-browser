import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { buttonVariants } from "@/components/ui/button";

export default async function NotFound() {
  const t = await getTranslations("common");
  return (
    <div className="mx-auto max-w-screen-2xl px-4 py-24 text-center">
      <h1 className="text-3xl font-bold">{t("notFound.title")}</h1>
      <p className="mx-auto mt-2 max-w-prose text-[var(--muted-foreground)]">
        {t("notFound.intro")}{" "}
        {t.rich("notFound.pathLine", {
          path: "/<institution>/journals/<issn>",
          code: (chunks) => (
            <code className="mx-1 rounded bg-[var(--muted)] px-1 py-0.5">{chunks}</code>
          ),
        })}
      </p>
      <Link href="/" className={buttonVariants({ className: "mt-6" })}>
        {t("nav.allUniversities")}
      </Link>
    </div>
  );
}
