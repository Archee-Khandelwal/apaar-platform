"use client";

import { useQuery } from "@tanstack/react-query";
import { Clock, Copy, RefreshCw } from "lucide-react";

import { PageHeader } from "@/components/AppShell";
import { MaskedApaar } from "@/components/Masked";
import { ErrorState, LoadingSkeleton } from "@/components/States";
import { Badge, Button, Card, CardContent } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";

export default function IdCardPage() {
  const { toast } = useToast();
  const query = useQuery({ queryKey: ["student-id-card"], queryFn: api.idCard });

  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  const card = query.data;

  return (
    <>
      <PageHeader
        title="Digital ID card"
        description="Show this QR to an employer or institution. The token behind it expires, and you can revoke it."
        actions={
          <Button variant="outline" onClick={() => query.refetch()} disabled={query.isFetching}>
            <RefreshCw className="h-4 w-4" />
            New token
          </Button>
        }
      />

      {query.isLoading || !card ? (
        <LoadingSkeleton rows={6} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_1fr]">
          <Card className="overflow-hidden">
            <div className="bg-primary px-5 py-3 text-primary-foreground">
              <p className="text-[10px] uppercase tracking-widest opacity-80">
                APAAR student identity
              </p>
              <p className="text-sm font-semibold">Academic Bank of Credits</p>
            </div>
            <CardContent className="space-y-3 pt-4">
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Name</p>
                <p className="text-base font-semibold">{card.name ?? "—"}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">APAAR ID</p>
                <MaskedApaar value={card.apaar_masked} className="text-base" />
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Institution</p>
                <p className="text-sm">{card.institution_name ?? "—"}</p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Programme</p>
                <p className="text-sm">{card.program ?? "—"}</p>
                <p className="text-xs text-muted-foreground">
                  {card.academic_year}
                  {card.year_of_study ? ` · year ${card.year_of_study}` : ""}
                  {card.status ? ` · ${card.status}` : ""}
                </p>
              </div>
              {card.is_minor && <Badge tone="warning">Under 18 — parental consent required</Badge>}

              <div className="flex justify-center rounded-lg bg-white p-3">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`data:image/png;base64,${card.qr_png_base64}`}
                  alt="QR code containing a signed, short-lived verification token"
                  className="h-44 w-44"
                />
              </div>
              <p className="flex items-center justify-center gap-1.5 text-xs text-muted-foreground">
                <Clock className="h-3 w-3" />
                Token expires {dateTime(card.token_expires_at)}
              </p>
            </CardContent>
          </Card>

          <div className="space-y-4">
            <Card>
              <CardContent className="space-y-3 pt-5">
                <p className="text-sm font-semibold">How this works</p>
                <ul className="space-y-2 text-sm text-muted-foreground">
                  <li>
                    The QR holds a signed token, not your details. Anyone scanning it gets only{" "}
                    <strong>verified yes/no, programme and academic year</strong>.
                  </li>
                  <li>
                    The token is signed with the platform&apos;s key, so it cannot be edited — changing
                    one character makes it invalid.
                  </li>
                  <li>
                    It expires on its own. Press <em>New token</em> for a fresh one, and withdraw
                    consent in the consent manager to kill an issued one immediately.
                  </li>
                </ul>
                <div className="rounded-md bg-muted/50 p-3">
                  <p className="text-xs uppercase tracking-wide text-muted-foreground">
                    Token (for pasting into the public check)
                  </p>
                  <p className="mt-1 break-all font-mono text-xs">{card.token}</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText(card.token);
                          toast("Token copied.", "success");
                        } catch {
                          toast("Could not copy — select the text instead.", "warning");
                        }
                      }}
                    >
                      <Copy className="h-3.5 w-3.5" />
                      Copy token
                    </Button>
                    <Button asChild size="sm" variant="ghost">
                      <a href={card.verify_url} target="_blank" rel="noreferrer">
                        Open the public check
                      </a>
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
