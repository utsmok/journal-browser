"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { CollapsibleCard } from "@/components/collapsible-card";
import { MoreToggle, NAMES_LIMIT } from "@/components/journal/shared";

/** Alternate titles from OpenAlex, capped like topics: chips plus a
 * reveal toggle once the list runs long. */
export function OtherNamesCard({ names }: { names: string[] }) {
  const t = useTranslations("journals");
  const [open, setOpen] = React.useState(false);
  const shown = open ? names : names.slice(0, NAMES_LIMIT);
  return (
    <CollapsibleCard
      id="names"
      title={t("names.title")}
      count={names.length}
      defaultOpen={false}
      compact
      description={
        <p className="text-xs text-[var(--muted-foreground)]">{t("names.description")}</p>
      }
      contentClassName="flex flex-wrap items-center gap-1.5"
    >
      {shown.map((name) => (
        <Badge key={name} variant="muted" className="font-normal normal-case">
          {name}
        </Badge>
      ))}
      {names.length > NAMES_LIMIT && (
        <MoreToggle
          open={open}
          onToggle={() => setOpen((o) => !o)}
          moreLabel={t("names.showAll", { count: String(names.length) })}
        />
      )}
    </CollapsibleCard>
  );
}
