import * as React from "react";

import { JournalsLanding } from "@/components/search/journals-landing";

export default function HomePage() {
  return (
    <React.Suspense fallback={null}>
      <JournalsLanding initialView="browse" />
    </React.Suspense>
  );
}
