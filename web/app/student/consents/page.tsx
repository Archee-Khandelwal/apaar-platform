"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, ShieldOff, X } from "lucide-react";

import { PageHeader } from "@/components/AppShell";
import { EmptyState, ErrorState, LoadingSkeleton } from "@/components/States";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Spinner } from "@/components/ui/primitives";
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
        title="Consent manager"
        description="Nobody can verify you without your consent, and you can withdraw it at any time."
      />

      {query.isLoading ? (
        <LoadingSkeleton rows={4} />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No one has asked to verify you"
          description="When an employer or institution requests a verification, it will appear here first."
          icon={<ShieldOff className="h-6 w-6" />}
        />
      ) : (
        <div className="space-y-6">
          {pending.length > 0 && (
            <section>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Waiting for your answer ({pending.length})
              </h2>
              <div className="space-y-3">
                {pending.map((row) => (
                  <Card key={row.consent_id} className="border-amber-300 bg-amber-50/40">
                    <CardContent className="pt-5">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div>
                          <p className="font-semibold">{row.verifier_name}</p>
                          <p className="text-sm text-muted-foreground">{row.purpose_label}</p>
                        </div>
                        <span className="text-xs text-muted-foreground">
                          asked {dateTime(row.requested_at)}
                        </span>
                      </div>

                      <div className="mt-3 rounded-md border border-border bg-card p-3">
                        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                          If you approve, they will see only
                        </p>
                        <ul className="mt-1 flex flex-wrap gap-2 text-sm">
                          {row.will_share.map((item) => (
                            <li key={item} className="rounded bg-muted px-2 py-0.5">
                              {item}
                            </li>
                          ))}
                        </ul>
                        <p className="mt-2 text-xs text-muted-foreground">
                          Not your name, not your date of birth, not your contact details.
                        </p>
                      </div>

                      {row.parental_consent_required && (
                        <p className="mt-3 flex items-start gap-2 rounded-md bg-amber-100 p-2.5 text-xs text-amber-900">
                          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                          You are under 18, so this verification is marked{" "}
                          <strong>parental consent required</strong> — a parent or guardian should
                          answer this with you.
                        </p>
                      )}

                      <div className="mt-3 flex flex-wrap gap-2">
                        <Button size="sm" disabled={busy} onClick={() => approve.mutate(row.consent_id)}>
                          {approve.isPending ? <Spinner /> : <Check className="h-3.5 w-3.5" />}
                          Approve
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busy}
                          onClick={() => deny.mutate(row.consent_id)}
                        >
                          <X className="h-3.5 w-3.5" />
                          Deny
                        </Button>
                        {row.expires_at && (
                          <span className="self-center text-xs text-muted-foreground">
                            expires {dateTime(row.expires_at)}
                          </span>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </section>
          )}

          {active.length > 0 && (
            <section>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Active consents ({active.length})
              </h2>
              <div className="space-y-3">
                {active.map((row) => (
                  <Card key={row.consent_id} className="border-emerald-300 bg-emerald-50/30">
                    <CardContent className="flex flex-wrap items-center justify-between gap-3 pt-5">
                      <div>
                        <p className="font-semibold">{row.verifier_name}</p>
                        <p className="text-sm text-muted-foreground">
                          {row.purpose_label} · approved {dateTime(row.responded_at)}
                        </p>
                      </div>
                      <Button
                        size="sm"
                        variant="destructive"
                        disabled={busy}
                        onClick={() => revoke.mutate(row.consent_id)}
                      >
                        {revoke.isPending ? <Spinner /> : <ShieldOff className="h-3.5 w-3.5" />}
                        Withdraw consent
                      </Button>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </section>
          )}

          {past.length > 0 && (
            <section>
              <Card>
                <CardHeader>
                  <CardTitle>Past requests</CardTitle>
                </CardHeader>
                <CardContent>
                  <ul className="divide-y divide-border">
                    {past.map((row) => (
                      <li key={row.consent_id} className="flex flex-wrap items-center gap-2 py-2.5 text-sm">
                        <span className="font-medium">{row.verifier_name}</span>
                        <span className="text-muted-foreground">{row.purpose_label}</span>
                        <Badge tone={TONE[row.status]}>{row.status}</Badge>
                        <span className="ml-auto text-xs text-muted-foreground">
                          {dateTime(row.revoked_at ?? row.responded_at ?? row.requested_at)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            </section>
          )}
        </div>
      )}
    </>
  );
}
