import { Badge } from "@/components/ui/badge";

export function DealBadge({ covered }: { covered: boolean }) {
  if (!covered) return null;
  return <Badge variant="secondary">OA deal</Badge>;
}

type OaType = "gold" | "diamond" | "hybrid" | "subscription";

const OA_TYPE_META: Record<OaType, { label: string; title: string; className: string }> = {
  gold: {
    label: "Gold OA",
    title: "Fully open access journal, listed in DOAJ.",
    className:
      "border border-amber-300 bg-amber-100 text-[var(--primary-text)] dark:border-amber-400/40 dark:bg-amber-400/15 dark:text-[var(--primary-text)]",
  },
  diamond: {
    label: "Diamond OA",
    title: "Open access without article fees for authors or readers.",
    className:
      "border border-teal-300 bg-teal-100 text-teal-900 dark:border-teal-400/40 dark:bg-teal-400/15 dark:text-teal-300",
  },
  hybrid: {
    label: "Hybrid",
    title: "Subscription journal with open access publishing via a deal.",
    className:
      "border border-blue-300 bg-blue-100 text-blue-900 dark:border-blue-400/40 dark:bg-blue-400/15 dark:text-blue-300",
  },
  subscription: {
    label: "Subscription",
    title: "No open access route listed.",
    className: "bg-[var(--muted)] text-[var(--muted-foreground)]",
  },
};

/**
 * OA-type badge (gold / diamond / hybrid / subscription). The backend
 * computes oa_type; when it is absent (old backend) we fall back to
 * Subscription only for journals known not to be OA, and omit otherwise
 * rather than guess.
 */
export function OaTypeBadge({
  oaType,
  isOa,
}: {
  oaType?: OaType | null;
  isOa?: boolean | null;
}) {
  const type: OaType | null = oaType ?? (isOa === false ? "subscription" : null);
  if (!type) return null;
  const meta = OA_TYPE_META[type];
  return (
    <Badge variant="outline" className={meta.className} title={meta.title}>
      {meta.label}
    </Badge>
  );
}

/** Work-level OA statuses; one color map shared by chips and the trend chart. */
export const OA_STATUS_ORDER = [
  "gold",
  "hybrid",
  "green",
  "bronze",
  "diamond",
  "closed",
] as const;

export const OA_STATUS_META: Record<
  string,
  { label: string; chip: string; bar: string }
> = {
  gold: {
    label: "Gold",
    chip: "border border-amber-300 bg-amber-100 text-amber-900 dark:border-amber-400/40 dark:bg-amber-400/15 dark:text-amber-300",
    bar: "bg-amber-400 dark:bg-amber-500",
  },
  hybrid: {
    label: "Hybrid",
    chip: "border border-blue-300 bg-blue-100 text-blue-900 dark:border-blue-400/40 dark:bg-blue-400/15 dark:text-blue-300",
    bar: "bg-blue-400 dark:bg-blue-500",
  },
  green: {
    label: "Green",
    chip: "border border-emerald-300 bg-emerald-100 text-emerald-900 dark:border-emerald-400/40 dark:bg-emerald-400/15 dark:text-emerald-300",
    bar: "bg-emerald-400 dark:bg-emerald-500",
  },
  bronze: {
    label: "Bronze",
    chip: "border border-orange-300 bg-orange-100 text-orange-900 dark:border-orange-400/40 dark:bg-orange-400/15 dark:text-orange-300",
    bar: "bg-orange-400 dark:bg-orange-500/80",
  },
  diamond: {
    label: "Diamond",
    chip: "border border-teal-300 bg-teal-100 text-teal-900 dark:border-teal-400/40 dark:bg-teal-400/15 dark:text-teal-300",
    bar: "bg-teal-400 dark:bg-teal-500",
  },
  closed: {
    label: "Closed",
    chip: "border border-slate-300 bg-slate-100 text-slate-700 dark:border-slate-500/40 dark:bg-slate-500/15 dark:text-slate-300",
    bar: "bg-slate-300 dark:bg-slate-600",
  },
};

/** Small OA-status chip for a single work; legend/chart reuse the same colors. */
export function OaStatusChip({ status }: { status?: string | null }) {
  if (!status) return null;
  const meta = OA_STATUS_META[status];
  if (!meta) return null;
  return (
    <Badge variant="outline" className={meta.chip}>
      {meta.label}
    </Badge>
  );
}

export function QuartileBadge({ quartile }: { quartile: string | null }) {
  if (!quartile) return null;
  return (
    <Badge variant={quartile === "Q1" ? "default" : "muted"}>{quartile}</Badge>
  );
}
