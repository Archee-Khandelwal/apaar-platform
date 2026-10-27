"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { useState } from "react";

import { AICTE_INSTITUTION_TABS, PageHeader, SubTabs } from "@/components/ui/page";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge, Button, Spinner } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { count, dateTime } from "@/lib/format";
import type { NonReportingRow } from "@/lib/types";

export default function NonReportingPage() {
  const { user } = useAuth();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [pending, setPending] = useState<number | null>(null);

  const query = useQuery({
    queryKey: ["aicte-non-reporting", page],
    queryFn: () => api.nonReporting({ page, page_size: 25 }),
  });

  const remind = useMutation({
    mutationFn: (institutionId: number) => api.remind(institutionId),
    onMutate: (institutionId) => setPending(institutionId),
    onSuccess: () => {
      toast("Reminder queued (mocked) and written to the audit log.", "success");
      queryClient.invalidateQueries({ queryKey: ["aicte-non-reporting"] });
    },
    onError: (error: Error) => toast(error.message, "danger"),
    onSettled: () => setPending(null),
  });

  const columns: Column<NonReportingRow>[] = [
    {
      key: "name",
      header: "Institution",
      cell: (row) => (
        <span className="block">
          <span className="block font-medium leading-snug">{row.name}</span>
          <span className="mt-0.5 block text-xs text-muted-foreground">{row.state}</span>
        </span>
      ),
    },
    {
      key: "deadline",
      header: "Reporting deadline",
      width: "w-[12rem]",
      cell: (row) => (
        <span className="text-sm">
          {dateTime(row.reporting_deadline)}
          <span className="block text-xs text-muted-foreground">
            {row.days_overdue > 0
              ? `${row.days_overdue} day(s) overdue`
              : row.days_to_deadline !== null && row.days_to_deadline !== undefined
                ? `due in ${row.days_to_deadline} day(s)`
                : ""}
          </span>
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      width: "w-[7rem]",
      nowrap: true,
      cell: (row) =>
        row.days_overdue > 0 ? <Badge tone="danger">overdue</Badge> : <Badge tone="warning">not filed</Badge>,
    },
    {
      key: "last",
      header: "Last upload ever",
      width: "w-[11rem]",
      cell: (row) => <span className="text-xs text-muted-foreground">{dateTime(row.last_upload_at)}</span>,
    },
    {
      key: "reminders",
      header: "Reminders",
      width: "w-[8rem]",
      align: "right",
      cell: (row) => (
        <span className="text-sm">
          {count(row.reminders_sent)}
          {row.last_reminder_at && (
            <span className="block text-xs text-muted-foreground">{dateTime(row.last_reminder_at)}</span>
          )}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      width: "w-[9.5rem]",
      align: "right",
      cell: (row) =>
        user?.role === "aicte_officer" ? (
          <Button
            size="sm"
            variant="outline"
            disabled={remind.isPending}
            onClick={() => remind.mutate(row.institution_id)}
          >
            {pending === row.institution_id ? <Spinner /> : <Send className="h-3.5 w-3.5" />}
            Send reminder
          </Button>
        ) : null,
    },
  ];

  return (
    <>
      <PageHeader
        title="Not reporting"
        description="Approved institutions that have filed no student-level data for the current year. Reminders are mocked in this prototype, and logged."
      />

      <SubTabs tabs={AICTE_INSTITUTION_TABS} current="/aicte/non-reporting" />

      <DataTable
        minWidth="min-w-[66rem]"
        columns={columns}
        rows={query.data?.items ?? []}
        loading={query.isLoading}
        total={query.data?.total}
        page={page}
        pageSize={25}
        onPageChange={setPage}
        emptyTitle="Every institution has reported"
        emptyDescription="Nothing is outstanding for this academic year."
        rowKey={(row) => row.institution_id}
      />
    </>
  );
}
