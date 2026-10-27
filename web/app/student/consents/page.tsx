"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, ShieldOff, X } from "lucide-react";

import { PageHeader, SectionCard } from "@/components/ui/page";
import { EmptyState, ErrorState, Skeleton } from "@/components/States";
import { Badge, Button, Spinner } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { ConsentRow } from "@/lib/types";

const TONE: Record<ConsentRow["status"], "neutral" | "success" | "warning" | "danger"> = {
  pending: "warning",
  approved: "success",
  denied: "neutral",
  revoked: "danger",
  expired: "neutral",
};

export default function ConsentsPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["student-consents"], queryFn: () => api.consents({ page_size: 50 }) });

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["student-consents"] });
    queryClient.invalidateQueries({ queryKey: ["student-me"] });
  }

  const approve = useMutation({
    mutationFn: (id: number) => api.approveConsent(id),
    onSuccess: (result) => {
      toast(`Approved. They can see ${result.shared_fields.join(", ")} until ${dateTime(result.expires_at)}.`, "success");
      invalidate();
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  const deny = useMutation({
    mutationFn: (id: number) => api.denyConsent(id),
    onSuccess: () => {
      toast("Denied. Nothing was shared.", "info");
      invalidate();
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  const revoke = useMutation({
    mutationFn: (id: number) => api.revokeConsent(id),
    onSuccess: (result) => {
      toast(
        `Consent withdrawn. ${result.tokens_invalidated} issued token(s) stopped working immediately.`,
        "warning",
      );
      invalidate();
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  const rows = query.data?.items ?? [];
  const pending = rows.filter((row) => row.status === "pending");
  const active = rows.filter((row) => row.status === "approved");
  const past = rows.filter((row) => !["pending", "approved"].includes(row.status));
  const busy = approve.isPending || deny.isPending || revoke.isPending;

  return (
    <>
      <PageHeader
        title="Consents"
        description="Who has asked to verify you, what they would learn, and what you have already allowed."
      />

      {query.isLoading ? (
        <Skeleton rows={3} height="h-32" />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No one has asked to verify you"
          description="When an employer or institution requests a verification, it will appear here first."
          icon={<ShieldOff className="h-6 w-6" />}
        />
      ) : (
        <div className="space-y-8">
          {pending.length > 0 && (
            <section>
              <h2 className="mb-3 type-section-title">
                Waiting for your answer ({pending.length})
              </h2>
              <div className="space-y-4">
                {pending.map((row) => (
                  <SectionCard
                    key={row.consent_id}
                    className="border-amber-200"
                    title={row.verifier_name}
                    description={row.purpose_label}
                    actions={
                      <span className="text-xs text-muted-foreground">
                        asked {dateTime(row.requested_at)}
                      </span>
                    }
                  >
                    <div className="rounded-md border border-border bg-secondary/50 p-4">
                      <p className="type-label">If you approve, they will see only</p>
                      <ul className="mt-2 flex flex-wrap gap-2 text-sm">
                        {row.will_share.map((item) => (
                          <li key={item} className="rounded bg-card px-2 py-1 ring-1 ring-inset ring-border">
                            {item}
                          </li>
                        ))}
                      </ul>
                      <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                        Not your name, not your date of birth, not your contact details.
                      </p>
                    </div>

                    {row.parental_consent_required && (
                      <p className="mt-4 flex items-start gap-2 rounded-md bg-amber-100 p-3 text-xs leading-relaxed text-amber-900">
                        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                        <span>
                          You are under 18, so this verification is marked{" "}
                          <strong>parental consent required</strong> — a parent or guardian should
                          answer this with you.
                        </span>
                      </p>
                    )}

                    <div className="mt-5 flex flex-wrap items-center gap-2">
                      <Button disabled={busy} onClick={() => approve.mutate(row.consent_id)}>
                        {approve.isPending ? <Spinner /> : <Check className="h-4 w-4" />}
                        Approve
                      </Button>
                      <Button variant="outline" disabled={busy} onClick={() => deny.mutate(row.consent_id)}>
                        <X className="h-4 w-4" />
                        Deny
                      </Button>
                      {row.expires_at && (
                        <span className="text-xs text-muted-foreground">
                          Expires {dateTime(row.expires_at)}
                        </span>
                      )}
                    </div>
                  </SectionCard>
                ))}
              </div>
            </section>
          )}

          {active.length > 0 && (
            <section>
              <h2 className="mb-3 type-section-title">Active consents ({active.length})</h2>
              <div className="space-y-4">
                {active.map((row) => (
                  <div
                    key={row.consent_id}
                    className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-emerald-200 bg-card p-5 shadow-card"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-semibold">{row.verifier_name}</p>
                      <p className="mt-0.5 text-sm text-muted-foreground">
                        {row.purpose_label} · approved {dateTime(row.responded_at)}
                      </p>
                    </div>
                    <Button
                      variant="destructive"
                      disabled={busy}
                      onClick={() => revoke.mutate(row.consent_id)}
                    >
                      {revoke.isPending ? <Spinner /> : <ShieldOff className="h-4 w-4" />}
                      Withdraw consent
                    </Button>
                  </div>
                ))}
              </div>
            </section>
          )}

          {past.length > 0 && (
            <SectionCard title="Past requests" bodyClassName="p-0">
              <ul className="divide-y divide-border">
                {past.map((row) => (
                  <li
                    key={row.consent_id}
                    className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 py-3 text-sm"
                  >
                    <span className="font-medium">{row.verifier_name}</span>
                    <span className="text-muted-foreground">{row.purpose_label}</span>
                    <Badge tone={TONE[row.status]}>{row.status}</Badge>
                    <span className="ml-auto text-xs text-muted-foreground">
                      {dateTime(row.revoked_at ?? row.responded_at ?? row.requested_at)}
                    </span>
                  </li>
                ))}
              </ul>
            </SectionCard>
          )}
        </div>
      )}
    </>
  );
}
