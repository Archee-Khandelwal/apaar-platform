"use client";

/**
 * Accounts and password resets. A reset shows the temporary password exactly once; the
 * account can then do nothing but choose a new one, and its old sessions are ended.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useState } from "react";

import { DataTable, TableFilters, type Column } from "@/components/DataTable";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { PageHeader } from "@/components/ui/page";
import { Badge, Button, Input, Select, Spinner } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { ROLE_LABELS } from "@/lib/nav";
import type { AdminUser, PasswordReset, Role } from "@/lib/types";

export default function AdminUsersPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [role, setRole] = useState("");
  const [confirming, setConfirming] = useState<AdminUser | null>(null);
  const [issued, setIssued] = useState<PasswordReset | null>(null);

  const query = useQuery({
    queryKey: ["admin-users", page, search, role],
    queryFn: () =>
      api.adminUsers({ page, page_size: 25, q: search || undefined, role: role || undefined }),
  });

  const reset = useMutation({
    mutationFn: (userId: number) => api.resetPassword(userId),
    onSuccess: (result) => {
      setConfirming(null);
      setIssued(result);
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  const columns: Column<AdminUser>[] = [
    {
      key: "username",
      header: "Username",
      cell: (row) => <span className="font-mono text-xs font-medium">{row.username}</span>,
    },
    { key: "role", header: "Role", width: "w-[9rem]", cell: (row) => ROLE_LABELS[row.role] },
    { key: "name", header: "Account", cell: (row) => row.display_name },
    {
      key: "state",
      header: "Status",
      width: "w-[10rem]",
      cell: (row) =>
        row.must_change_password ? (
          <Badge tone="warning">awaiting new password</Badge>
        ) : (
          <Badge tone="success">active</Badge>
        ),
    },
    {
      key: "login",
      header: "Last sign-in",
      width: "w-[10rem]",
      nowrap: true,
      cell: (row) => <span className="text-xs text-muted-foreground">{dateTime(row.last_login_at)}</span>,
    },
    {
      key: "action",
      header: "",
      width: "w-[9rem]",
      align: "right",
      cell: (row) => (
        <Button size="sm" variant="outline" onClick={() => setConfirming(row)}>
          <KeyRound className="h-3.5 w-3.5" />
          Reset
        </Button>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Accounts"
        description="Every account has its own bcrypt-hashed password. Resetting one issues a single-use temporary password and signs that account out everywhere."
      />

      <DataTable
        minWidth="min-w-[52rem]"
        columns={columns}
        rows={query.data?.items ?? []}
        loading={query.isLoading}
        total={query.data?.total}
        page={page}
        pageSize={25}
        onPageChange={setPage}
        emptyTitle="No accounts match"
        rowKey={(row) => row.id}
        toolbar={
          <TableFilters hint="Resets are recorded in the audit log.">
            <Input
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
              placeholder="Username"
              className="w-56"
            />
            <Select
              value={role}
              onChange={(event) => {
                setRole(event.target.value);
                setPage(1);
              }}
              className="w-44"
            >
              <option value="">All roles</option>
              {(Object.keys(ROLE_LABELS) as Role[]).map((option) => (
                <option key={option} value={option}>
                  {ROLE_LABELS[option]}
                </option>
              ))}
            </Select>
          </TableFilters>
        }
      />

      <Dialog open={Boolean(confirming)} onOpenChange={(open) => !open && setConfirming(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reset the password for {confirming?.username}?</DialogTitle>
            <DialogDescription>
              Their current password stops working and every session they have is signed out.
              You will see a temporary password once; they must replace it when they sign in.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirming(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={reset.isPending}
              onClick={() => confirming && reset.mutate(confirming.id)}
            >
              {reset.isPending && <Spinner />}
              Reset password
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(issued)} onOpenChange={(open) => !open && setIssued(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Temporary password for {issued?.username}</DialogTitle>
            <DialogDescription>
              Shown only now — it is not stored anywhere in readable form. Pass it to the account
              holder over a separate channel.
            </DialogDescription>
          </DialogHeader>
          <p className="rounded-md border border-border bg-secondary px-4 py-3 text-center font-mono text-lg tracking-wider">
            {issued?.temporary_password}
          </p>
          <p className="text-xs text-muted-foreground">Audit entry #{issued?.audit_log_id}.</p>
          <DialogFooter>
            <Button onClick={() => setIssued(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
