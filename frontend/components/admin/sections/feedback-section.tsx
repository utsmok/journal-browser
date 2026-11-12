"use client";

import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/admin/admin-shell";
import { FeedbackSection as FeedbackPanel } from "@/components/admin/feedback-table";
import { useAdminToken } from "@/lib/admin";

/** User feedback triage: status workflow, notes, and per-report page data. */
export function FeedbackSection() {
  const t = useTranslations("admin");
  const [token, setToken] = useAdminToken();

  return (
    <div className="space-y-6">
      <PageHeader title={t("feedback.title")} lede={t("feedback.lede")} />
      <FeedbackPanel token={token ?? ""} onUnauthorized={setToken} />
    </div>
  );
}
