import { getTranslations } from "next-intl/server";

const HARVEST_STAGES: { titleKey: string; detailKey: string }[] = [
  { titleKey: "storage.stageExternalInputs", detailKey: "storage.stageExternalInputsDetail" },
  { titleKey: "storage.stageDownload", detailKey: "storage.stageDownloadDetail" },
  { titleKey: "storage.stageSourceRecords", detailKey: "storage.stageSourceRecordsDetail" },
  { titleKey: "storage.stageNormalized", detailKey: "storage.stageNormalizedDetail" },
  { titleKey: "storage.stageDenormalized", detailKey: "storage.stageDenormalizedDetail" },
  { titleKey: "storage.stageCaches", detailKey: "storage.stageCachesDetail" },
  { titleKey: "storage.stageApiResponses", detailKey: "storage.stageApiResponsesDetail" },
];

const USER_WRITES: { titleKey: string; detailKey: string }[] = [
  { titleKey: "storage.stageUsageEvents", detailKey: "storage.stageUsageEventsDetail" },
  { titleKey: "storage.stageFeedbackItems", detailKey: "storage.stageFeedbackItemsDetail" },
  { titleKey: "storage.stageDocEdits", detailKey: "storage.stageDocEditsDetail" },
  { titleKey: "storage.stageManualOverrides", detailKey: "storage.stageManualOverridesDetail" },
  { titleKey: "storage.stageStatusChanges", detailKey: "storage.stageStatusChangesDetail" },
];

type Stage = { titleKey: string; detailKey: string };

function StageRow({ stages, t }: { stages: Stage[]; t: (key: string) => string }) {
  return (
    <div className="flex flex-row flex-wrap items-stretch gap-2">
      {stages.map((stage, i) => (
        <div key={stage.titleKey} className="contents">
          {i > 0 && (
            <span aria-hidden className="self-center text-[var(--muted-foreground)]">
              →
            </span>
          )}
          <div className="max-w-[13rem] min-w-[10rem] rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-3">
            <p className="text-sm font-semibold">{t(stage.titleKey)}</p>
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">{t(stage.detailKey)}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

export async function StorageFlow() {
  const t = await getTranslations("dataPipeline");
  return (
    <div className="space-y-3">
      <div>
        <p className="mb-2 text-xs font-medium tracking-wide text-[var(--muted-foreground)] uppercase">
          {t("storage.flowHarvestTitle")}
        </p>
        <StageRow stages={HARVEST_STAGES} t={t} />
      </div>
      <div>
        <p className="mb-2 text-xs font-medium tracking-wide text-[var(--muted-foreground)] uppercase">
          {t("storage.flowUserWritesTitle")}
        </p>
        <StageRow stages={USER_WRITES} t={t} />
      </div>
    </div>
  );
}
