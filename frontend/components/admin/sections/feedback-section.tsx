"use client";

import { PageHeader } from "@/components/admin/admin-shell";
import { FeedbackSection as FeedbackPanel } from "@/components/admin/feedback-table";
import { useAdminToken } from "@/lib/admin";

/** User feedback triage: status workflow, notes, and per-report page data. */
export function FeedbackSection() {
  const [token, setToken] = useAdminToken();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Feedback"
        lede="Triage user reports. Click a row to fold out the report details and the page-data dump (copyable); status flips are audited."
      />
      <FeedbackPanel token={token ?? ""} onUnauthorized={setToken} />
    </div>
  );
}
