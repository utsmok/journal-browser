"use client";

import { PageHeader } from "@/components/admin/admin-shell";
import { FeedbackSection } from "@/components/admin/feedback-table";
import { useAdminToken } from "@/lib/admin";

/** User feedback triage: status workflow, notes, and per-report page data. */
export default function AdminFeedbackPage() {
  const [token, setToken] = useAdminToken();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Feedback"
        lede="Triage user reports. Status flips are audited; deleting removes the report permanently."
      />
      <FeedbackSection token={token ?? ""} onUnauthorized={setToken} />
    </div>
  );
}
