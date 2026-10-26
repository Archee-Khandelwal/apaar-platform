"use client";

/** The flag queue: filters, facets, a case drawer and the officer's actions. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { PageHeader } from "@/components/AppShell";
import { DataTable, type Column } from "@/components/DataTable";
import { ExplanationPanel } from "@/components/ExplanationPanel";
import { RevealButton } from "@/components/RevealButton";
import { SeverityBadge, StatusBadge } from "@/components/SeverityBadge";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import { Button, Input, Label, Select, Spinner, Textarea } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { count, flagLabel, relative } from "@/lib/format";
import { FLAG_TYPES, type Flag, type Severity } from "@/lib/types";

const SEVERITIES: Severity[] = ["critical", "high", "medium", "low"];
const STATUSES = ["open", "under_review", "escalated", "resolved", "dismissed"];
const OFFICERS = ["aicte_officer1"];

export default function FlagQueuePage() {
  const { user } = useAuth();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const isOfficer = user?.role === "aicte_officer";

  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("-severity");
  const [type, setType] = useState("");
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [openOnly, setOpenOnly] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [assignee, setAssignee] = useState("");

  const list = useQuery({
    queryKey: ["aicte-flags", page, sort, type, severity, status, search, openOnly],
    queryFn: () =>
      api.flags({
        page,
        page_size: 20,
        sort,
        type: type || undefined,
        severity: severity || undefined,
        status: status || undefined,
        q: search || undefined,
        open_only: openOnly || undefined,
      }),
  });

  const detail = useQuery({
    queryKey: ["aicte-flag", selectedId],
    queryFn: () => api.flag(selectedId!),
    enabled: selectedId !== null,
  });

  const update = useMutation({
    mutationFn: (payload: { status?: string; assigned_to?: string; note?: string; reason?: string }) =>
      api.updateFlag(selectedId!, payload),
    onSuccess: (result) => {
      toast(`Case #${result.flag.id} is now ${result.flag.status.replace("_", " ")}.`, "success");
      setNote("");
      setReason("");
      queryClient.invalidateQueries({ queryKey: ["aicte-flags"] });
      queryClient.invalidateQueries({ queryKey: ["aicte-flag", selectedId] });
      queryClient.invalidateQueries({ queryKey: ["aicte-overview"] });
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  const columns: Column<Flag>[] = [
    {
      key: "severity",
      header: "Severity",
      sortKey: "severity",
      cell: (row) => <SeverityBadge severity={row.severity} />,
    },
    {
      key: "type",
      header: "Finding",
      sortKey: "type",
      cell: (row) => <span className="font-medium">{flagLabel(row.type)}</span>,
    },
    {
      key: "institution",
      header: "Institution",
      cell: (row) => (
        <span className="text-sm">
          {row.institution_name ?? "—"}
          {row.state && <span className="block text-xs text-muted-foreground">{row.state}</span>}
        </span>
      ),
    },
    {
      key: "title",
      header: "What we saw",
      cell: (row) => <span className="line-clamp-2 max-w-sm text-sm">{row.title}</span>,
    },
    { key: "status", header: "Status", sortKey: "status", cell: (row) => <StatusBadge status={row.status} /> },
    {
      key: "assigned",
      header: "Assigned",
      cell: (row) => <span className="text-xs">{row.assigned_to ?? "—"}</span>,
    },
    {
      key: "created",
      header: "Raised",
      sortKey: "created_at",
      cell: (row) => <span className="text-xs text-muted-foreground">{relative(row.created_at)}</span>,
    },
  ];

  const facets = list.data?.facets;

  return (
    <>
      <PageHeader
        title="Flag queue"
        description={
          isOfficer
            ? "Every finding, with its evidence. Click a row to open the case file."
            : "Findings in masked form. Evidence and case actions are available to officers."
        }
      />

      {facets && (
        <div className="mb-4 flex flex-wrap gap-2">
          {SEVERITIES.filter((item) => facets.by_severity[item]).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => {
                setSeverity(severity === item ? "" : item);
                setPage(1);
              }}
              className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                severity === item ? "border-primary bg-primary/10" : "border-border bg-card hover:bg-muted"
              }`}
            >
              <SeverityBadge severity={item} showDot={false} className="mr-1.5" />
              {count(facets.by_severity[item])}
            </button>
          ))}
        </div>
      )}

      <DataTable
        columns={columns}
        rows={list.data?.items ?? []}
        loading={list.isLoading}
        total={list.data?.total}
        page={page}
        pageSize={20}
        sort={sort}
        onSortChange={setSort}
        onPageChange={setPage}
        onRowClick={(row) => setSelectedId(row.id)}
        emptyTitle="No findings match these filters"
        toolbar={
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
              placeholder="Search titles and explanations"
              className="w-60"
            />
            <Select
              value={type}
              onChange={(event) => {
                setType(event.target.value);
                setPage(1);
              }}
              className="w-56"
            >
              <option value="">All finding types</option>
              {FLAG_TYPES.map((item) => (
                <option key={item} value={item}>
                  {flagLabel(item)}
                </option>
              ))}
            </Select>
            <Select
              value={status}
              onChange={(event) => {
                setStatus(event.target.value);
                setOpenOnly(false);
                setPage(1);
              }}
              className="w-40"
            >
              <option value="">Any status</option>
              {STATUSES.map((item) => (
                <option key={item} value={item}>
                  {item.replace("_", " ")}
                </option>
              ))}
            </Select>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={openOnly}
                onChange={(event) => {
                  setOpenOnly(event.target.checked);
                  if (event.target.checked) setStatus("");
                  setPage(1);
                }}
              />
              Open cases only
            </label>
          </div>
        }
      />

      <Dialog open={selectedId !== null} onOpenChange={(open) => !open && setSelectedId(null)}>
        <DialogContent className="max-h-[88vh] max-w-3xl overflow-y-auto">
          {detail.isLoading && <Spinner />}
          {detail.data && (
            <>
              <ExplanationPanel flag={detail.data} />

              {detail.data.students.length > 0 && (
                <div className="mt-4 rounded-md border border-border p-3">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Student on this case
                  </p>
                  {detail.data.students.map((student) => (
                    <div key={student.student_id} className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm">
                        <span className="font-mono text-xs">{student.apaar_masked}</span> ·{" "}
                        {student.name_masked}
                        {student.is_minor && " · minor"}
                      </span>
                      <RevealButton studentId={student.student_id} />
                    </div>
                  ))}
                </div>
              )}

              {isOfficer && (
                <div className="mt-5 space-y-3 border-t border-border pt-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Case actions
                  </p>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label htmlFor="assignee">Assign to</Label>
                      <Select
                        id="assignee"
                        value={assignee || detail.data.assigned_to || ""}
                        onChange={(event) => setAssignee(event.target.value)}
                      >
                        <option value="">Unassigned</option>
                        {OFFICERS.map((officer) => (
                          <option key={officer} value={officer}>
                            {officer}
                          </option>
                        ))}
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="reason">Reason (needed to dismiss or resolve)</Label>
                      <Input
                        id="reason"
                        value={reason}
                        onChange={(event) => setReason(event.target.value)}
                        placeholder="e.g. Verified against the admission register."
                      />
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="note">Case note</Label>
                    <Textarea
                      id="note"
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                      placeholder="e.g. Called the data cell; awaiting their response."
                    />
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Every change is written to the hash-chained audit log with your name.
                  </p>
                </div>
              )}

              {isOfficer && (
                <DialogFooter className="flex-wrap">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={update.isPending}
                    onClick={() =>
                      update.mutate({
                        status: "under_review",
                        note: note || undefined,
                        assigned_to: assignee || undefined,
                      })
                    }
                  >
                    Mark under review
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={update.isPending}
                    onClick={() =>
                      update.mutate({ status: "escalated", note: note || undefined, reason: reason || undefined })
                    }
                  >
                    Escalate
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={update.isPending || (!reason && !note)}
                    onClick={() => update.mutate({ status: "dismissed", reason: reason || note })}
                  >
                    Dismiss
                  </Button>
                  <Button
                    size="sm"
                    disabled={update.isPending || (!reason && !note)}
                    onClick={() => update.mutate({ status: "resolved", reason: reason || note })}
                  >
                    {update.isPending && <Spinner />}
                    Resolve
                  </Button>
                </DialogFooter>
              )}
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
