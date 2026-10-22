import { Badge } from "@/components/ui/badge";

export function DealBadge({ covered }: { covered: boolean }) {
  if (!covered) return null;
  return <Badge variant="secondary">OA deal</Badge>;
}

export function OaFlag({ isOa }: { isOa: boolean | null }) {
  if (isOa === null) return null;
  return isOa ? (
    <Badge>OA journal</Badge>
  ) : (
    <Badge variant="outline">Subscription</Badge>
  );
}

export function QuartileBadge({ quartile }: { quartile: string | null }) {
  if (!quartile) return null;
  return (
    <Badge variant={quartile === "Q1" ? "default" : "muted"}>{quartile}</Badge>
  );
}

/** Shown on rows outside the quality-bar corpus when scope=all. */
export function QualityBarBadge() {
  return (
    <Badge
      variant="outline"
      className="border-dashed font-normal opacity-75 normal-case"
    >
      outside quality bar
    </Badge>
  );
}
