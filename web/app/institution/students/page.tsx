"use client";

/** Own students, masked, with a versioned status change. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { PageHeader } from "@/components/ui/page";
import { DataTable, TableFilters, type Column } from "@/components/DataTable";
import { MaskedApaar, MaskedName } from "@/components/Masked";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Badge, Button, Input, Label, Select, Spinner, Textarea } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { dateOnly } from "@/lib/format";
import type { StudentRow } from "@/lib/types";

const YEARS = ["", "2026-27", "2025-26"];
const STATUS_CHANGES = [
  { value: "cancelled", label: "Admission cancelled" },
  { value: "migrated", label: "Migrated to another institution" },
  { value: "dropped", label: "Dropped out" },
  { value: "completed", label: "Completed the programme" },
];

export default function StudentsPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [year, setYear] = useState("2026-27");
  const [apaarStatus, setApaarStatus] = useState("");
  const [target, setTarget] = useState<StudentRow | null>(null);
  const [status, setStatus] = useState("cancelled");
  const [reason, setReason] = useState("");

  const query = useQuery({
    queryKey: ["students", page, search, year, apaarStatus],
    queryFn: () =>
      api.students({
        page,
        page_size: 25,
        q: search || undefined,
        academic_year: year || undefined,
        apaar_status: apaarStatus || undefined,
      }),
  });

  const change = useMutation({
    mutationFn: () =>
      api.changeEnrolmentStatus(target!.enrolment.id, { status, reason: reason.trim() }),
    onSuccess: (result) => {
      toast(`Enrolment marked ${result.status} (version ${result.version}).`, "success");
      setTarget(null);
      setReason("");
      queryClient.invalidateQueries({ queryKey: ["students"] });
      queryClient.invalidateQueries({ queryKey: ["seat-matrix"] });
      queryClient.invalidateQueries({ queryKey: ["institution-dashboard"] });
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  const columns: Column<StudentRow>[] = [
    {
      key: "apaar",
      header: "APAAR",
      width: "w-[9.5rem]",
      nowrap: true,
      cell: (row) => <MaskedApaar value={row.apaar_masked} />,
    },
    {
      key: "name",
      header: "Name",
      width: "w-[9.5rem]",
      cell: (row) => (
        <span className="flex items-center gap-2">
          <MaskedName value={row.name_masked} />
          {row.is_minor && <Badge tone="warning">minor</Badge>}
        </span>
      ),
    },
    {
      key: "programme",
      header: "Programme",
      cell: (row) => (
        <span className="block">
          <span className="block leading-snug">
            {row.enrolment.course} {row.enrolment.branch}
          </span>
          <span className="mt-0.5 block text-xs text-muted-foreground">
            Year {row.enrolment.year_of_study} · {row.enrolment.admission_type}
          </span>
        </span>
      ),
    },
    {
      key: "apaar_status",
      header: "APAAR status",
      width: "w-[8.5rem]",
      cell: (row) => (
        <Badge tone={row.apaar_status === "provided" ? "success" : row.apaar_status === "pending" ? "warning" : "neutral"}>
          {row.apaar_status.replace("_", " ")}
        </Badge>
      ),
    },
    {
      key: "status",
      header: "Enrolment",
      width: "w-[7.5rem]",
      cell: (row) => (
        <span className="text-sm">
          {row.enrolment.status}
          {row.enrolment.version > 1 && (
            <span className="ml-1 text-xs text-muted-foreground">v{row.enrolment.version}</span>
          )}
        </span>
      ),
    },
    {
      key: "admitted",
      header: "Admitted",
      width: "w-[7.5rem]",
      nowrap: true,
      cell: (row) => <span className="text-xs">{dateOnly(row.enrolment.admitted_on)}</span>,
    },
    {
      key: "flags",
      header: "Flags",
      width: "w-[5rem]",
      align: "right",
      cell: (row) => (row.flag_count > 0 ? <Badge tone="danger">{row.flag_count}</Badge> : "—"),
    },
    {
      key: "actions",
      header: "",
      width: "w-[10rem]",
      align: "right",
      cell: (row) => (
        <Button
          size="sm"
          variant="outline"
          onClick={(event) => {
            event.stopPropagation();
            setTarget(row);
            setStatus("cancelled");
          }}
          disabled={row.enrolment.status !== "admitted"}
        >
          Change status
        </Button>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Students"
        description="Every student you have reported, and the enrolment record behind each one."
      />

      <DataTable
        minWidth="min-w-[66rem]"
        columns={columns}
        rows={query.data?.items ?? []}
        loading={query.isLoading}
        total={query.data?.total}
        page={page}
        pageSize={25}
        onPageChange={setPage}
        emptyTitle="No students match these filters"
        rowKey={(row) => row.enrolment.id}
        toolbar={
          <TableFilters hint="Masked by default — raw identifiers are never shown in this portal.">
            <Input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
              placeholder="Last 4 digits of APAAR, or masked name"
              className="w-64"
            />
            <Select
              value={year}
              onChange={(event) => {
                setYear(event.target.value);
                setPage(1);
              }}
              className="w-36"
            >
              {YEARS.map((option) => (
                <option key={option} value={option}>
                  {option || "All years"}
                </option>
              ))}
            </Select>
            <Select
              value={apaarStatus}
              onChange={(event) => {
                setApaarStatus(event.target.value);
                setPage(1);
              }}
              className="w-44"
            >
              <option value="">Any APAAR status</option>
              <option value="provided">provided</option>
              <option value="pending">pending</option>
              <option value="not_applicable">not applicable (FN/OCI)</option>
            </Select>
          </TableFilters>
        }
      />

      <Dialog open={Boolean(target)} onOpenChange={(open) => !open && setTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Change enrolment status</DialogTitle>
            <DialogDescription>
              {target && (
                <>
                  {target.name_masked} · {target.apaar_masked} · {target.enrolment.course}{" "}
                  {target.enrolment.branch}, {target.enrolment.academic_year}
                </>
              )}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="status">New status</Label>
              <Select id="status" value={status} onChange={(event) => setStatus(event.target.value)}>
                {STATUS_CHANGES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="reason">Reason (required, at least 10 characters)</Label>
              <Textarea
                id="reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="e.g. Admission cancelled on student request; fee refunded."
              />
            </div>
            <p className="text-xs text-muted-foreground">
              The change is versioned with your name and the reason, and the seat matrix is
              recalculated — so cancelling an excess admission can close an intake finding.
            </p>
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setTarget(null)}>
              Cancel
            </Button>
            <Button disabled={reason.trim().length < 10 || change.isPending} onClick={() => change.mutate()}>
              {change.isPending && <Spinner />}
              Save change
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
