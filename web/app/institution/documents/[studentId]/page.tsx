"use client";

/** One student's document checklist: upload, replace, view, and why a check failed. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Eye, Upload } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef } from "react";

import { ChecklistBadge, VerificationBadge } from "@/components/DocumentStatusBadge";
import { MaskedApaar, MaskedName } from "@/components/Masked";
import { ErrorState, Skeleton } from "@/components/States";
import { PageHeader, SectionCard } from "@/components/ui/page";
import { Button, Spinner } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api, openFile } from "@/lib/api";
import { dateTime, nationalityLabel } from "@/lib/format";
import type { StudentChecklist } from "@/lib/types";

type Item = StudentChecklist["items"][number];

function ChecklistRow({ studentId, item }: { studentId: number; item: Item }) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const document = item.document;

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadDocument(studentId, item.doc_type, file),
    onSuccess: () => {
      toast(`${item.label} uploaded.`, "success");
      queryClient.invalidateQueries({ queryKey: ["student-checklist", studentId] });
      queryClient.invalidateQueries({ queryKey: ["documents-overview"] });
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  return (
    <li className="flex flex-wrap items-start gap-x-4 gap-y-3 p-5">
      <div className="min-w-0 flex-1 space-y-1.5">
        <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
          {item.label}
          <ChecklistBadge status={item.status} />
          {document && document.verification_status !== "pending" && (
            <VerificationBadge status={document.verification_status} />
          )}
        </p>
        {document ? (
          <p className="text-xs leading-relaxed text-muted-foreground">
            {document.original_filename} · {(document.size_bytes / 1024).toFixed(0)} KB ·{" "}
            {document.content_type.split("/")[1].toUpperCase()} · uploaded {dateTime(document.uploaded_at)} ·
            SHA-256 <code className="font-mono">{document.sha256.slice(0, 12)}…</code>
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">Not uploaded yet.</p>
        )}
        {document && document.reasons.length > 0 && (
          <ul className="space-y-1 text-xs leading-relaxed">
            {document.reasons.map((reason) => (
              <li key={reason.code} className={reason.severity === "info" ? "text-muted-foreground" : "text-amber-800"}>
                • {reason.message}
              </li>
            ))}
          </ul>
        )}
        {document?.review_reason && (
          <p className="text-xs text-muted-foreground">
            AICTE officer: <span className="text-foreground">{document.review_reason}</span>
          </p>
        )}
      </div>
      <div className="flex shrink-0 gap-2">
        {document && (
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              openFile(`/institution/documents/${document.id}/file`).catch((error: Error) =>
                toast(error.message, "danger"),
              )
            }
          >
            <Eye className="h-3.5 w-3.5" />
            View
          </Button>
        )}
        <input
          ref={input}
          type="file"
          accept="application/pdf,image/jpeg,image/png"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) upload.mutate(file);
            event.target.value = "";
          }}
        />
        <Button size="sm" variant={document ? "outline" : "default"} onClick={() => input.current?.click()} disabled={upload.isPending}>
          {upload.isPending ? <Spinner /> : <Upload className="h-3.5 w-3.5" />}
          {document ? "Replace" : "Upload"}
        </Button>
      </div>
    </li>
  );
}

export default function StudentDocumentsPage() {
  const params = useParams<{ studentId: string }>();
  const studentId = Number(params.studentId);
  const query = useQuery({
    queryKey: ["student-checklist", studentId],
    queryFn: () => api.studentChecklist(studentId),
    enabled: Number.isFinite(studentId),
  });

  if (query.isError) return <ErrorState error={query.error} onRetry={query.refetch} />;
  if (query.isLoading || !query.data) return <Skeleton rows={4} height="h-20" />;
  const data = query.data;

  return (
    <>
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2">
          <Link href="/institution/documents">
            <ArrowLeft className="h-3.5 w-3.5" />
            All students
          </Link>
        </Button>
        <PageHeader
          title="Document checklist"
          description={
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <MaskedApaar value={data.apaar_masked} />
              <span aria-hidden>·</span>
              <MaskedName value={data.name_masked} />
              <span aria-hidden>·</span>
              <span>
                {data.admission_type.replace(/_/g, " ")} admission, {data.academic_year}
                {data.category ? ` · ${data.category}` : ""}
                {data.nationality_status !== "indian" ? ` · ${nationalityLabel(data.nationality_status)}` : ""}
              </span>
            </span>
          }
        />
      </div>

      <SectionCard
        title={data.complete ? "Every required document is in" : `${data.counts.missing} missing, ${data.counts.rejected} rejected`}
        description="The checklist depends on how the student was admitted, their category and nationality status (document_checklist.yaml)."
        bodyClassName="p-0"
      >
        <ul className="divide-y divide-border">
          {data.items.map((item) => (
            <ChecklistRow key={item.doc_type} studentId={studentId} item={item} />
          ))}
        </ul>
      </SectionCard>
    </>
  );
}
