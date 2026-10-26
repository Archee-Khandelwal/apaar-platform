"use client";

/** Own flags only. Cross-institution findings never name the other college. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { PageHeader } from "@/components/AppShell";
import { DataTable, type Column } from "@/components/DataTable";
import { ExplanationPanel } from "@/components/ExplanationPanel";
import { SeverityBadge, StatusBadge } from "@/components/SeverityBadge";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Button, Select, Spinner, Textarea } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { flagLabel, relative } from "@/lib/format";
import type { InstitutionFlag, Severity } from "@/lib/types";

const SEVERITIES: Severity[] = ["critical", "high", "medium", "low"];
const STATUSES = ["open", "under_review", "escalated", "resolved", "dismissed"];

export default function InstitutionFlagsPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("-severity");
  const [selected, setSelected] = useState<InstitutionFlag | null>(null);
  const [note, setNote] = useState("");

  const query = useQuery({
    queryKey: ["institution-flags", page, severity, status, sort],
    queryFn: () =>
      api.institutionFlags({ page, page_size: 20, severity: severity || undefined, status: status || undefined, sort }),
  });

  const update = useMutation({
    mutationFn: (payload: { id: number; status?: string; note?: string }) =>
      api.updateInstitutionFlag(payload.id, { status: payload.status, note: payload.note }),
    onSuccess: (updated) => {
      toast(`Finding marked ${updated.status.replace("_", " ")}.`, "success");
      setSelected(null);
      setNote("");
      queryClient.invalidateQueries({ queryKey: ["institution-flags"] });
      queryClient.invalidateQueries({ queryKey: ["institution-dashboard"] });
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  const columns: Column<InstitutionFlag>[] = [
    {
      key: "severity",
      header: "Severity",
      sortKey: "severity",
      cell: (row) => <SeverityBadge severity={row.severity} />,
    },
    { key: "type", header: "Finding", cell: (row) => <span className="font-medium">{flagLabel(row.type)}</span> },
    {
      key: "title",
      header: "What we saw",
      cell: (row) => <span className="line-clamp-2 max-w-md text-sm">{row.title}</span>,
    },
    { key: "status", header: "Status", cell: (row) => <StatusBadge status={row.status} /> },
    { key: "year", header: "Year", cell: (row) => row.academic_year ?? "—" },
    {
      key: "created",
      header: "Raised",
      sortKey: "created_at",
      cell: (row) => <span className="text-xs text-muted-foreground">{relative(row.created_at)}</span>,
    },
  ];

  return (
    <>
      <PageHeader
        title="Flag inbox"
        description="Every finding against your institution, with the reasoning and the evidence behind it."
      />

      <DataTable
        columns={columns}
        rows={query.data?.items ?? []}
        loading={query.isLoading}
        total={query.data?.total}
        page={page}
        pageSize={20}
        sort={sort}
        onSortChange={setSort}
        onPageChange={setPage}
        onRowClick={setSelected}
        emptyTitle="No findings against your institution"
        emptyDescription="Findings appear here after an upload is validated, or when AICTE's detectors run."
        toolbar={
          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={severity}
              onChange={(event) => {
                setSeverity(event.target.value);
                setPage(1);
              }}
              className="w-40"
            >
              <option value="">All severities</option>
              {SEVERITIES.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
            <Select
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setPage(1);
              }}
              className="w-44"
            >
              <option value="">All statuses</option>
              {STATUSES.map((item) => (
                <option key={item} value={item}>
                  {item.replace("_", " ")}
                </option>
              ))}
            </Select>
            <p className="text-xs text-muted-foreground">Click a row for the full explanation.</p>
          </div>
        }
      />

      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
          {selected && (
            <>
              <ExplanationPanel flag={{ ...selected, institution_name: null, state: null }} />
              <div className="mt-5 space-y-2 border-t border-border pt-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  What did you do about it?
                </p>
                <Textarea
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="e.g. Row corrected and re-uploaded in upload #44."
                />
                <p className="text-xs text-muted-foreground">
                  You can mark a finding under review or resolved. Escalating and dismissing stay
                  with AICTE.
                </p>
              </div>
              <DialogFooter>
                <Button
                  variant="outline"
                  disabled={update.isPending}
                  onClick={() => update.mutate({ id: selected.id, status: "under_review", note: note || undefined })}
                >
                  Mark under review
                </Button>
                <Button
                  disabled={update.isPending || note.trim().length === 0}
                  onClick={() => update.mutate({ id: selected.id, status: "resolved", note })}
                >
                  {update.isPending && <Spinner />}
                  Mark resolved
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
