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
