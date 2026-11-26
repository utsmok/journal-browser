import { Seeds } from "@/components/seed";
import { type DealOut, dealsRequest } from "@/lib/api";
import type { InstRoute } from "@/lib/page-meta";
import { qk } from "@/lib/query-keys";
import { fetchForRender } from "@/lib/server-fetch";

import DealsPageClient from "./page-client";

/** Seeds both lists, so the server HTML carries the cards and the tab badges. */
export default async function DealsPage({ params }: InstRoute) {
  const { inst } = await params;
  const [current, archive] = await Promise.all([
    fetchForRender<DealOut[]>(dealsRequest(inst, "current")),
    fetchForRender<DealOut[]>(dealsRequest(inst, "archive")),
  ]);
  return (
    <Seeds
      entries={[
        { queryKey: qk.deals(inst, "current"), data: current },
        { queryKey: qk.deals(inst, "archive"), data: archive },
      ]}
    >
      <DealsPageClient />
    </Seeds>
  );
}
