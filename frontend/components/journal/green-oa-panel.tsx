"use client";

import * as React from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { CollapsibleCard } from "@/components/collapsible-card";
import { External } from "@/components/journal/shared";
import { SourceNote } from "@/components/source-note";
import type { Attribution } from "@/lib/api";
import type { GreenOaPolicy } from "@/components/journal/shared";

export const GREEN_OA_VERSION_KEYS: Record<string, string> = {
  submitted: "greenVersions.submitted",
  accepted: "greenVersions.accepted",
  published: "greenVersions.published",
};

/** Sherpa location slugs (verified against the live jisc_policy corpus). */
export const GREEN_OA_LOCATION_KEYS: Record<string, string> = {
  academic_social_network: "greenLocations.academicSocialNetwork",
  any_repository: "greenLocations.anyRepository",
  any_website: "greenLocations.anyWebsite",
  authors_homepage: "greenLocations.authorsHomepage",
  funder_designated_location: "greenLocations.funderDesignatedLocation",
  institutional_repository: "greenLocations.institutionalRepository",
  institutional_website: "greenLocations.institutionalWebsite",
  named_academic_social_network: "greenLocations.namedAcademicSocialNetwork",
  named_repository: "greenLocations.namedRepository",
  non_commercial_institutional_repository: "greenLocations.nonCommercialInstitutionalRepository",
  non_commercial_repository: "greenLocations.nonCommercialRepository",
  non_commercial_social_network: "greenLocations.nonCommercialSocialNetwork",
  non_commercial_subject_repository: "greenLocations.nonCommercialSubjectRepository",
  non_commercial_website: "greenLocations.nonCommercialWebsite",
  preprint_repository: "greenLocations.preprintRepository",
  subject_repository: "greenLocations.subjectRepository",
  this_journal: "greenLocations.thisJournal",
};

export function licenseLabel(license: string): string {
  if (license === "cc0") return "CC0";
  if (license.startsWith("cc_")) return `CC ${license.slice(3).replaceAll("_", "-").toUpperCase()}`;
  return license.charAt(0).toUpperCase() + license.slice(1).replaceAll("_", " ");
}

/** Scraped link descriptions arrive as bare filenames or "Website"; give
 * those a label that says what the document is. Returns null for labels
 * that are already specific (render the scraped text then). */
export function greenOaLinkLabel(
  t: (key: string) => string,
  description: string | null | undefined,
): string | null {
  const text = description?.trim() ?? "";
  if (!text) return null;
  if (/powerpoint|\.pptx?\b/i.test(text)) return t("greenOa.agreementSlides");
  if (/^website$/i.test(text)) return t("greenOa.publisherOaPage");
  return null;
}

export function locationPhrase(
  base: React.ReactNode,
  location: string,
  repositories: string[],
  links: Record<string, string>,
): React.ReactNode {
  if (!(location.startsWith("named_") && repositories.length > 0)) return base;
  return (
    <>
      {base}:{" "}
      {repositories.map((name, i) => (
        <React.Fragment key={name}>
          {i > 0 && ", "}
          {/* Linked when the name matched a jisc_repositories row. */}
          {links[name] ? <External href={links[name]}>{name}</External> : name}
        </React.Fragment>
      ))}
    </>
  );
}

export function GreenOaPanel({
  greenOa,
  attribution,
}: {
  greenOa: GreenOaPolicy;
  attribution: Partial<Attribution>;
}) {
  const t = useTranslations("journals");
  const routes = Object.entries(greenOa.routes);
  return (
    <CollapsibleCard
      id="green-oa"
      title={t("greenOa.title")}
      description={
        <p className="text-sm text-[var(--muted-foreground)]">{t("greenOa.description")}</p>
      }
      contentClassName="space-y-4 text-sm"
    >
      {greenOa.oa_prohibited && (
        <p className="font-medium text-red-700 dark:text-red-300">{t("greenOa.prohibited")}</p>
      )}
      {routes.map(([version, route]) => (
        <div key={version} className="space-y-1">
          <h3 className="flex flex-wrap items-center gap-2 font-semibold">
            {GREEN_OA_VERSION_KEYS[version] ? t(GREEN_OA_VERSION_KEYS[version]) : version}
            {route.additional_oa_fee === "yes" && (
              <Badge variant="muted" title={t("greenOa.feeHint")}>
                {t("greenOa.feeBadge")}
              </Badge>
            )}
          </h3>
          {route.locations.length > 0 && (
            <p>
              {t("greenOa.where")}{" "}
              {route.locations.map((location, i) => (
                <React.Fragment key={location}>
                  {i > 0 && "; "}
                  {locationPhrase(
                    GREEN_OA_LOCATION_KEYS[location]
                      ? t(GREEN_OA_LOCATION_KEYS[location])
                      : location.charAt(0).toUpperCase() + location.slice(1).replaceAll("_", " "),
                    location,
                    route.repositories,
                    greenOa.repository_links,
                  )}
                </React.Fragment>
              ))}
              .
            </p>
          )}
          {route.licenses.length > 0 && (
            <p>{t("greenOa.licence", { licenses: route.licenses.map(licenseLabel).join(", ") })}</p>
          )}
          {route.embargo_months != null && (
            <p>{t("greenOa.embargo", { count: route.embargo_months })}</p>
          )}
          {route.conditions.length > 0 && (
            // Jisc policy text is CC BY-NC-ND: shown verbatim, never paraphrased.
            <div>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                {t("greenOa.conditionsHeading")}
              </h4>
              <ul className="list-disc space-y-1 pl-4">
                {route.conditions.map((condition) => (
                  <li key={condition} className="text-pretty">
                    {condition}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ))}
      {routes.length === 0 && !greenOa.oa_prohibited && <p>{t("greenOa.empty")}</p>}
      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-[var(--border)] pt-3">
        {greenOa.policy_uri && (
          <External href={greenOa.policy_uri}>{t("greenOa.jiscLink")}</External>
        )}
        {greenOa.urls.map((u) => (
          <External key={u.url} href={u.url}>
            {greenOaLinkLabel(t, u.description) || u.url}
          </External>
        ))}
        <SourceNote {...attribution} codes={attribution.caveat_codes} />
      </div>
    </CollapsibleCard>
  );
}
