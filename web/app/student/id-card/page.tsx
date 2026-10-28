"use client";

import { useQuery } from "@tanstack/react-query";
import { Clock, Copy, FileDown, RefreshCw } from "lucide-react";

import { PageHeader, SectionCard, TechnicalDetails } from "@/components/ui/page";
import { MaskedApaar } from "@/components/Masked";
import { ErrorState, Skeleton } from "@/components/States";
import { Badge, Button, Card } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";

function DegreeCertificateSection() {
  const query = useQuery({ queryKey: ["my-certificates"], queryFn: api.myCertificates });
  const items = query.data?.items ?? [];
  return (
    <SectionCard title="Degree certificate">
      {query.isLoading ? (
        <Skeleton rows={1} height="h-24" />
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">Degree certificate not issued yet.</p>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((item) => (
            <li key={item.serial} className="flex flex-wrap items-center gap-4 py-3">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={item.qr} alt="QR code that verifies this certificate" className="h-28 w-28 rounded bg-white p-1" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold">{item.program}</p>
                <p className="text-xs text-muted-foreground">
                  {item.institution} · {item.academic_year}
                </p>
                <p className="mt-1 font-mono text-xs">{item.serial}</p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Badge tone={item.status === "valid" ? "success" : "danger"}>
                    {item.status === "valid" ? "Valid" : "Revoked"} · issued {dateTime(item.issued_at)}
                  </Badge>
                  {item.status === "valid" && (
                    <Button variant="outline" size="sm" onClick={() => api.openMyCertificate(item.serial)}>
                      <FileDown className="h-4 w-4" /> View / download PDF
                    </Button>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

export default function IdCardPage() {
  const { toast } = useToast();
  const query = useQuery({ queryKey: ["student-id-card"], queryFn: api.idCard });

  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;

  const card = query.data;

  return (
    <>
      <PageHeader
        title="Certificates & ID"
        description="Your degree certificate, if one has been issued, and your ID card. Show the ID QR to an employer or institution. It proves your enrolment without revealing anything else."
        actions={
          <Button variant="outline" onClick={() => query.refetch()} disabled={query.isFetching}>
            <RefreshCw className="h-4 w-4" />
            New token
          </Button>
        }
      />

      <DegreeCertificateSection />

      {query.isLoading || !card ? (
        <Skeleton rows={4} height="h-32" />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
          <Card className="overflow-hidden">
            <div className="bg-primary px-5 py-3 text-primary-foreground">
              <p className="text-[10px] uppercase tracking-widest opacity-80">
                APAAR student identity
              </p>
              <p className="text-sm font-semibold">Academic Bank of Credits</p>
            </div>
            <div className="space-y-4 p-5">
              <div>
                <p className="type-label">Name</p>
                <p className="text-base font-semibold">{card.name ?? "—"}</p>
              </div>
              <div>
                <p className="type-label">APAAR ID</p>
                <MaskedApaar value={card.apaar_masked} className="text-base" />
              </div>
              <div>
                <p className="type-label">Institution</p>
                <p className="text-sm">{card.institution_name ?? "—"}</p>
              </div>
              <div>
                <p className="type-label">Programme</p>
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
            </div>
          </Card>

          <div className="min-w-0 space-y-6">
            <SectionCard title="How this works">
                <ul className="space-y-3 text-sm leading-relaxed text-muted-foreground">
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

                <div className="mt-5 flex flex-wrap gap-2">
                  <Button
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
                    <Copy className="h-4 w-4" />
                    Copy token
                  </Button>
                  <Button asChild variant="ghost">
                    <a href={card.verify_url} target="_blank" rel="noreferrer">
                      Open the public check
                    </a>
                  </Button>
                </div>

                <TechnicalDetails label="The raw token" className="mt-5">
                  <p className="break-all font-mono text-xs text-muted-foreground">{card.token}</p>
                </TechnicalDetails>
            </SectionCard>
          </div>
        </div>
      )}
    </>
  );
}
