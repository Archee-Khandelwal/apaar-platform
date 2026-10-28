"use client";

/**
 * One document case: the file beside the submitted record and what was read from it,
 * the issuer's answer, the tamper checks, and the officer's decision.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Lock, RefreshCw, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { VerificationBadge } from "@/components/DocumentStatusBadge";
import { FieldList, PageHeader, SectionCard } from "@/components/ui/page";
import { Badge, Button, Card, Label, Spinner, Textarea } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api, fileUrl } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { CaseFile } from "@/lib/types";

function MatchCell({ match }: { match?: boolean | null }) {
  if (match === true) return <Badge tone="success">match</Badge>;
  if (match === false) return <Badge tone="danger">mismatch</Badge>;
  return <Badge tone="neutral">not on document</Badge>;
}

export default function DocumentCasePage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [data, setData] = useState<CaseFile | null>(null);
  const [file, setFile] = useState<{ url: string; type: string } | null>(null);
  const [decisionReason, setDecisionReason] = useState("");

  useEffect(() => () => {
    if (file) URL.revokeObjectURL(file.url);
  }, [file]);

  const open = useMutation({
    mutationFn: async () => {
      const body = await api.documentCase(id, reason.trim());
      const blob = await fileUrl(`/aicte/documents/${id}/file`, { method: "POST", body: { reason: reason.trim() } }).catch(
        () => null,
      );
      return { body, blob };
    },
    onSuccess: ({ body, blob }) => {
      setData(body);
      setFile(blob);
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  const decide = useMutation({
    mutationFn: (decision: "approve" | "reject") => api.documentDecision(id, decision, decisionReason.trim()),
    onSuccess: (result) => {
      toast(`Decision recorded: ${result.verification_status}. It is in the audit chain.`, "success");
      queryClient.invalidateQueries({ queryKey: ["review-queue"] });
      open.mutate();
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  const recheck = useMutation({
    mutationFn: () => api.recheckDocument(id),
    onSuccess: (result) => {
      toast(`Re-checked: ${result.verification_status.replace("_", " ")}.`, "success");
      queryClient.invalidateQueries({ queryKey: ["review-queue"] });
      open.mutate();
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  const back = (
    <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2">
      <Link href="/aicte/documents">
        <ArrowLeft className="h-3.5 w-3.5" />
        Review queue
      </Link>
    </Button>
  );

  if (!data) {
    return (
      <>
        <div>
          {back}
          <PageHeader title="Open a document case" description="This case shows the student's real name and date of birth." />
        </div>
        <Card className="max-w-xl p-6">
          <p className="flex items-center gap-2 text-sm font-medium">
            <Lock className="h-4 w-4 text-primary" />
            Why are you opening it?
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Your reason is written to the access log, and the student can read it.
          </p>
          <form
            className="mt-4 space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              open.mutate();
            }}
          >
            <Label htmlFor="reason" className="sr-only">Reason</Label>
            <Textarea
              id="reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="e.g. Reviewing a name mismatch flagged on this marksheet."
            />
            <Button type="submit" disabled={reason.trim().length < 10 || open.isPending}>
              {open.isPending && <Spinner />}
              Open the case
            </Button>
          </form>
        </Card>
      </>
    );
  }

  const decided = data.verification_status === "verified" || Boolean(data.review.decision);
  const metadata = data.tamper.metadata ?? {};

  return (
    <>
      <div>
        {back}
        <PageHeader
          title={data.label}
          description={
            <span className="flex flex-wrap items-center gap-2">
              <VerificationBadge status={data.verification_status} />
              <span>
                {data.institution?.name} · {data.student.apaar ?? data.student.apaar_masked} · uploaded{" "}
                {dateTime(data.uploaded_at)} by {data.uploaded_by}
              </span>
            </span>
          }
          actions={
            <Button variant="outline" onClick={() => recheck.mutate()} disabled={recheck.isPending}>
              {recheck.isPending ? <Spinner /> : <RefreshCw className="h-4 w-4" />}
              Re-run checks
            </Button>
          }
        />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <SectionCard title="The document" bodyClassName="p-0">
          {file ? (
            file.type.startsWith("image/") ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={file.url} alt={data.label} className="w-full" />
            ) : (
              <iframe src={file.url} title={data.label} className="h-[640px] w-full" />
            )
          ) : (
            <p className="p-5 text-sm text-red-700">
              The file is withheld: it no longer matches the hash recorded at upload.
            </p>
          )}
        </SectionCard>

        <div className="space-y-6">
          <SectionCard title="Why it is here">
            <ul className="space-y-2 text-sm leading-relaxed">
              {data.reasons.map((item) => (
                <li
                  key={item.code}
                  className={
                    item.severity === "error" ? "text-red-700" : item.severity === "info" ? "text-muted-foreground" : "text-amber-800"
                  }
                >
                  • {item.message}
                </li>
              ))}
            </ul>
          </SectionCard>

          <SectionCard title="Submitted record vs the document" bodyClassName="p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-secondary/60">
                  <th className="px-4 py-2 text-left type-label">Field</th>
                  <th className="px-4 py-2 text-left type-label">Submitted</th>
                  <th className="px-4 py-2 text-left type-label">On the document</th>
                  <th className="px-4 py-2 text-left type-label">Result</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.comparison.map((row) => (
                  <tr key={row.field}>
                    <td className="px-4 py-2 font-medium">{row.field}</td>
                    <td className="px-4 py-2">{row.submitted ?? "—"}</td>
                    <td className="px-4 py-2">{row.on_document ?? "—"}</td>
                    <td className="px-4 py-2">
                      <MatchCell match={row.match} />
                      {row.detail !== null && row.detail !== undefined && (
                        <span className="ml-2 text-xs text-muted-foreground">{row.detail}%</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </SectionCard>

          <SectionCard title={`Issuer: ${data.issuer.label}`}>
            <FieldList
              fields={[
                { label: "Reference", value: data.issuer.reference_no ?? String(data.extracted.reference_no ?? "—") },
                { label: "Issuer", value: data.issuer.issuer_name ?? "—" },
                { label: "Issued on", value: data.issuer.issued_on ?? "—" },
                { label: "Matched by", value: data.issuer.matched_by === "hash" ? "identical file (SHA-256)" : data.issuer.matched_by === "facts" ? "key facts" : "—" },
                { label: "Facts that differ", value: data.issuer.differing_facts?.join(", ") || "—" },
              ]}
            />
          </SectionCard>

          <SectionCard title="Tamper checks">
            <FieldList
              fields={[
                { label: "Stored file", value: data.integrity_ok ? "matches its upload hash" : "DOES NOT match its upload hash" },
                { label: "SHA-256 at upload", value: <code className="break-all font-mono text-xs">{data.sha256}</code> },
                { label: "Created (metadata)", value: metadata.created ?? "—" },
                { label: "Modified (metadata)", value: metadata.modified ?? "—" },
                { label: "Producer", value: metadata.producer ?? "—" },
              ]}
            />
            {data.tamper.edited_after_issue && <p className="mt-3 text-sm text-amber-800">{data.tamper.edited_after_issue}</p>}
          </SectionCard>

          <SectionCard title="Decision">
            {decided && data.review.decision ? (
              <p className="text-sm">
                <strong>{data.review.decision === "approve" ? "Approved" : "Rejected"}</strong> by {data.review.by} on{" "}
                {dateTime(data.review.at)}: {data.review.reason}
              </p>
            ) : null}
            <div className="mt-3 space-y-3">
              <Textarea
                value={decisionReason}
                onChange={(event) => setDecisionReason(event.target.value)}
                placeholder="Reason for your decision (recorded in the hash-chained audit log)"
              />
              <div className="flex flex-wrap gap-2">
                <Button
                  onClick={() => decide.mutate("approve")}
                  disabled={decisionReason.trim().length < 10 || decide.isPending || !data.integrity_ok}
                >
                  <Check className="h-4 w-4" />
                  Approve
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => decide.mutate("reject")}
                  disabled={decisionReason.trim().length < 10 || decide.isPending}
                >
                  <X className="h-4 w-4" />
                  Reject
                </Button>
              </div>
            </div>
          </SectionCard>
        </div>
      </div>
    </>
  );
}
