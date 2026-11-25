"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";

import { SourceNote } from "@/components/source-note";
import { useInstitution } from "@/hooks/use-institution";

const OPENALEX_URL = "https://docs.openalex.org/about-the-data/works";
const OPENAIRE_URL = "https://openaire.eu";
const ROR_URL = "https://ror.org";

/** Where the partner data comes from and how it is built. The sources are
 * spelled out on the page, not only in the hover notes, and the last link
 * opens the methodology page. */
export function CollaborationSources() {
  const t = useTranslations("collaborations");
  const tc = useTranslations("common");
  const inst = useInstitution();
  const linkClass = "text-[var(--primary-text)] underline-offset-4 hover:underline";
  return (
    <section aria-labelledby="collaboration-sources-title">
      <h2 id="collaboration-sources-title" className="text-base font-semibold">
        {t("sources.title")}
      </h2>
      <div className="mt-2 flex flex-wrap items-center gap-x-6 gap-y-2">
        <SourceNote
          source={t("sources.openalex")}
          url={OPENALEX_URL}
          codes={["collaboration-partners", "openalex-awards"]}
        />
        <SourceNote
          source={t("sources.openaire")}
          url={OPENAIRE_URL}
          codes={["openaire-partners", "openaire-projects"]}
        />
        <SourceNote source={t("sources.ror")} url={ROR_URL} codes={["ror-record"]} />
      </div>
      <p className="mt-3 max-w-prose text-sm text-[var(--muted-foreground)]">
        {tc("sourceNote.explain.collaborations")}
      </p>
      <Link
        href={`/${inst}/docs/collaborations`}
        className={`mt-2 inline-flex min-h-11 items-center text-sm ${linkClass} min-[1024px]:min-h-0`}
      >
        {t("methodology")}
      </Link>
    </section>
  );
}
