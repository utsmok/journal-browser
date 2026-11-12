"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/admin/admin-shell";
import { AdminDrawer } from "@/components/admin/drawer";
import { CopyButton } from "@/components/admin/record";
import {
  CreateDealForm,
  DealEditor,
  DealsTable,
  DealStatusBadge,
} from "@/components/admin/deal-editor";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAdminResource } from "@/hooks/use-admin-resource";
import { useInstitutionsDirectory } from "@/hooks/use-api";
import { useAdminToken, type AdminDeal, type FlaggedDeal } from "@/lib/admin";

/** Deal management: searchable table, curation queue, create/edit drawer. */
export function DealsSection({ basePath }: { basePath?: string }) {
  const t = useTranslations("admin");
  void basePath;
  const [token, setToken] = useAdminToken();
  const logout = () => setToken(null);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const directory = useInstitutionsDirectory();
  const unis = directory.data ?? [];

  const deals = useAdminResource<AdminDeal[]>("/deals", token ?? "", logout, "deals");
  const flagged = useAdminResource<FlaggedDeal[]>("/flagged", token ?? "", logout, "flagged deals");

  const q = query.trim().toLowerCase();
  const rows = useMemo(
    () =>
      (deals.data ?? []).filter(
        (deal) =>
          q === "" ||
          (deal.publisher ?? "").toLowerCase().includes(q) ||
          (deal.esac_id ?? "").toLowerCase().includes(q),
      ),
    [deals.data, q],
  );
  const selectedDeal = (deals.data ?? []).find((deal) => deal.id === selectedId) ?? null;

  const openDeal = (id: number) => {
    setCreating(false);
    setSelectedId(id);
  };
  const closeDrawer = () => {
    setSelectedId(null);
    setCreating(false);
  };

  return (
    <div className="space-y-8">
      <PageHeader title={t("deals.title")} lede={t("deals.lede")}>
        <Input
          aria-label={t("deals.filterAria")}
          placeholder={t("deals.filterPlaceholder")}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="w-64"
        />
        <Button
          size="sm"
          onClick={() => {
            setSelectedId(null);
            setCreating(true);
          }}
        >
          {t("deals.createTitle")}
        </Button>
        <Button variant="outline" size="sm" onClick={() => void deals.refresh()}>
          {t("refresh")}
        </Button>
      </PageHeader>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">{t("deals.allDeals", { count: rows.length })}</h2>
        {deals.error && <p className="text-sm text-destructive">{deals.error}</p>}
        <DealsTable deals={rows} selectedId={selectedId} onSelect={openDeal} />
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">
          {t("deals.flaggedTitle", { count: flagged.data?.length ?? 0 })}
        </h2>
        <p className="text-sm text-muted-foreground">{t("deals.flaggedHint")}</p>
        {flagged.error && <p className="text-sm text-destructive">{flagged.error}</p>}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("deals.flaggedColumnPublisher")}</TableHead>
              <TableHead>{t("deals.flaggedColumnEsac")}</TableHead>
              <TableHead>{t("deals.flaggedColumnStatus")}</TableHead>
              <TableHead>{t("deals.flaggedColumnJournals")}</TableHead>
              <TableHead>{t("deals.flaggedColumnReason")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(flagged.data ?? []).map((deal) => (
              <TableRow
                key={deal.id}
                className="cursor-pointer"
                title={t("deals.flaggedRowTitle")}
                onClick={() => openDeal(deal.id)}
              >
                <TableCell className="font-medium">{deal.publisher}</TableCell>
                <TableCell className="font-mono text-xs">{deal.esac_id ?? "—"}</TableCell>
                <TableCell>
                  <DealStatusBadge status={deal.status} />
                </TableCell>
                <TableCell className="tabular-nums">{deal.journals}</TableCell>
                <TableCell
                  className="max-w-md truncate text-muted-foreground"
                  title={deal.reason ?? ""}
                >
                  {deal.reason ?? "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>

      {(creating || selectedId !== null) && (
        <AdminDrawer
          title={
            creating || selectedId === null
              ? t("deals.drawerTitleNew")
              : t("deals.drawerTitle", { id: selectedId })
          }
          onClose={closeDrawer}
          actions={
            selectedDeal ? (
              <CopyButton
                text={JSON.stringify(selectedDeal, null, 2)}
                label={t("deals.copyDeal")}
              />
            ) : undefined
          }
        >
          {creating ? (
            <CreateDealForm
              token={token ?? ""}
              onUnauthorized={setToken}
              onCreated={(id) => {
                setCreating(false);
                setSelectedId(id);
                void deals.refresh();
              }}
              onCancel={closeDrawer}
            />
          ) : (
            selectedId !== null && (
              <DealEditor
                key={selectedId}
                dealId={selectedId}
                token={token ?? ""}
                institutions={unis}
                onUnauthorized={setToken}
                onChanged={() => {
                  void deals.refresh();
                  void flagged.refresh();
                }}
              />
            )
          )}
        </AdminDrawer>
      )}
    </div>
  );
}
