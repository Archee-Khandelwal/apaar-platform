"use client";

/** Drag-and-drop → column mapping → confirm → quality report. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  Info,
  Upload as UploadIcon,
} from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";

import { PageHeader } from "@/components/AppShell";
import { SeverityBadge } from "@/components/SeverityBadge";
import { Button, Card, CardContent, CardHeader, CardTitle, Label, Select, Spinner } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api, download } from "@/lib/api";
import { flagLabel } from "@/lib/format";
import type { QualityReport, UploadCreated } from "@/lib/types";
import { cn } from "@/lib/utils";

const CURRENT_YEAR = "2026-27";

function confidenceTone(confidence: number) {
  if (confidence >= 0.9) return "bg-emerald-100 text-emerald-800";
  if (confidence >= 0.7) return "bg-amber-100 text-amber-900";
  return "bg-red-100 text-red-800";
}

export default function UploadPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [created, setCreated] = useState<UploadCreated | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [report, setReport] = useState<QualityReport | null>(null);

  const upload = useMutation({
    mutationFn: (file: File) => api.createUpload(file, CURRENT_YEAR),
    onSuccess: (data) => {
      setCreated(data);
      setReport(null);
      setMapping(
        Object.fromEntries(data.proposed_mapping.map((column) => [column.source_column, column.field])),
      );
      toast(`Parsed ${data.rows_total} rows. Check the column mapping before we validate.`, "info");
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  const confirm = useMutation({
    mutationFn: () => api.confirmMapping(created!.upload_id, mapping, { academic_year: CURRENT_YEAR }),
    onSuccess: (data) => {
      setReport(data);
      queryClient.invalidateQueries({ queryKey: ["institution-dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["institution-flags"] });
      toast(
        `${data.rows_ok} rows accepted, ${data.rows_error} rejected, ${data.already_reported} already reported.`,
        data.rows_error > 0 ? "warning" : "success",
      );
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  function handleFile(file?: File | null) {
    if (file) upload.mutate(file);
  }

  const unmapped = created
    ? created.unmapped_required_fields.filter((field) => !Object.values(mapping).includes(field))
    : [];

  return (
    <>
      <PageHeader
        title="Upload student data"
        description="Excel or CSV. Headers do not have to match ours — we propose a mapping and you confirm it."
        actions={
          <Button
            variant="outline"
            onClick={() => download("/institution/template", "apaar_upload_template.csv")}
          >
            <Download className="h-4 w-4" />
            Download template
          </Button>
        }
      />

      <ol className="mb-5 flex flex-wrap items-center gap-2 text-xs">
        {["Choose a file", "Confirm the column mapping", "Quality report"].map((step, index) => {
          const state = index === 0 ? Boolean(created) : index === 1 ? Boolean(report) : false;
          const active =
            (index === 0 && !created) || (index === 1 && created && !report) || (index === 2 && report);
          return (
            <li
              key={step}
              className={cn(
                "flex items-center gap-1.5 rounded-full border px-3 py-1",
                active ? "border-primary bg-primary/5 font-medium text-primary" : "border-border",
                state && "text-muted-foreground",
              )}
            >
              <span className="flex h-4 w-4 items-center justify-center rounded-full bg-muted text-[10px] font-semibold">
                {index + 1}
              </span>
              {step}
            </li>
          );
        })}
      </ol>

      {/* ---------------------------------------------------------------- step 1 */}
      {!created && (
        <Card
          className={cn(
            "border-2 border-dashed transition-colors",
            dragging && "border-accent bg-accent/5",
          )}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            handleFile(event.dataTransfer.files?.[0]);
          }}
        >
          <CardContent className="flex flex-col items-center gap-3 py-14 text-center">
            <UploadIcon className="h-8 w-8 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium">Drop your admissions file here</p>
              <p className="mt-1 text-sm text-muted-foreground">
                .xlsx, .xls or .csv — up to 10 MB. Nothing is stored until you confirm the mapping.
              </p>
            </div>
            <input
              ref={inputRef}
              type="file"
              accept=".xlsx,.xls,.csv"
              className="hidden"
              onChange={(event) => handleFile(event.target.files?.[0])}
            />
            <Button onClick={() => inputRef.current?.click()} disabled={upload.isPending}>
              {upload.isPending ? <Spinner /> : <FileSpreadsheet className="h-4 w-4" />}
              Choose a file
            </Button>
            <p className="text-xs text-muted-foreground">
              Try the messy sample files in <code className="font-mono">/samples</code>.
            </p>
          </CardContent>
        </Card>
      )}

      {/* ---------------------------------------------------------------- step 2 */}
      {created && !report && (
        <Card>
          <CardHeader>
            <CardTitle>Confirm the column mapping</CardTitle>
            <p className="text-sm text-muted-foreground">
              {created.filename} · {created.rows_total} rows
              {created.blank_rows_skipped > 0 && ` · ${created.blank_rows_skipped} blank rows skipped`}
              {created.detected_sheet && ` · sheet "${created.detected_sheet}"`}
            </p>
          </CardHeader>
          <CardContent>
            {unmapped.length > 0 && (
              <p className="mb-3 flex items-start gap-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                These required fields are not mapped yet: {unmapped.join(", ")}.
              </p>
            )}

            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-sm">
                <thead className="bg-muted/60">
                  <tr>
                    <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Your column
                    </th>
                    <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Sample values
                    </th>
                    <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Confidence
                    </th>
                    <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      Maps to
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {created.proposed_mapping.map((column) => (
                    <tr key={column.source_column}>
                      <td className="px-3 py-2 font-medium">{column.source_column}</td>
                      <td className="max-w-[16rem] truncate px-3 py-2 text-xs text-muted-foreground">
                        {column.sample_values.join(", ") || "—"}
                      </td>
                      <td className="px-3 py-2">
                        {column.field ? (
                          <span
                            className={cn(
                              "rounded-full px-2 py-0.5 text-xs font-medium",
                              confidenceTone(column.confidence),
                            )}
                          >
                            {Math.round(column.confidence * 100)}%
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">ignored</span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <Select
                          value={mapping[column.source_column] ?? ""}
                          onChange={(event) =>
                            setMapping((current) => ({
                              ...current,
                              [column.source_column]: event.target.value || null,
                            }))
                          }
                        >
                          <option value="">— ignore this column —</option>
                          {created.available_fields.map((field) => (
                            <option key={field} value={field}>
                              {field}
                            </option>
                          ))}
                        </Select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Button onClick={() => confirm.mutate()} disabled={confirm.isPending}>
                {confirm.isPending && <Spinner />}
                Validate and import {created.rows_total} rows
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  setCreated(null);
                  setMapping({});
                }}
              >
                Start over
              </Button>
              <p className="text-xs text-muted-foreground">
                Rows with errors are reported, never stored. Rows already reported are skipped.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ---------------------------------------------------------------- step 3 */}
      {report && <QualityReportView report={report} onAgain={() => { setCreated(null); setReport(null); }} />}
    </>
  );
}

function QualityReportView({ report, onAgain }: { report: QualityReport; onAgain: () => void }) {
  const errors = report.issues.filter((issue) => issue.severity === "error");
  const warnings = report.issues.filter((issue) => issue.severity === "warning");
  const infos = report.issues.filter((issue) => issue.severity === "info");
  const score = report.quality_score ?? 0;
  const tone = score >= 85 ? "text-emerald-600" : score >= 65 ? "text-amber-600" : "text-red-600";

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-6 pt-5">
          <div className="text-center">
            <p className={cn("text-4xl font-semibold tabular-nums", tone)}>{score}</p>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">quality score</p>
          </div>
          <dl className="grid flex-1 gap-3 sm:grid-cols-4">
            {[
              ["Rows accepted", report.rows_ok, "text-emerald-700"],
              ["Rows rejected", report.rows_error, "text-red-700"],
              ["With warnings", report.rows_warning, "text-amber-700"],
              ["Already reported", report.already_reported, "text-slate-700"],
            ].map(([label, value, colour]) => (
              <div key={label as string}>
                <dt className="text-xs uppercase tracking-wide text-muted-foreground">{label as string}</dt>
                <dd className={cn("text-xl font-semibold tabular-nums", colour as string)}>
                  {value as number}
                </dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      {report.already_reported > 0 && (
        <p className="flex items-start gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-sm">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          {report.already_reported} row(s) were already reported for this programme and year, so they
          were skipped. Re-uploading the same file cannot create duplicate enrolments or raise your
          seat count.
        </p>
      )}

      {Object.keys(report.registry_check).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>APAAR registry check</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-4 text-sm">
            {Object.entries(report.registry_check).map(([key, value]) => (
              <div key={key}>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">
                  {key.replace(/_/g, " ")}
                </p>
                <p className="text-lg font-semibold tabular-nums">{value}</p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {report.flags_created.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Findings raised by this upload</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {report.flags_created.map((flag) => (
              <span
                key={flag.id}
                className="inline-flex items-center gap-2 rounded border border-border px-2 py-1 text-xs"
              >
                <SeverityBadge severity={flag.severity} showDot={false} />
                {flagLabel(flag.type)}
              </span>
            ))}
            <Button asChild size="sm" variant="outline">
              <Link href="/institution/flags">Open the flag inbox</Link>
            </Button>
          </CardContent>
        </Card>
      )}

      {[
        ["Errors — these rows were not stored", errors, "border-red-200 bg-red-50/40"],
        ["Warnings — stored, but worth checking", warnings, "border-amber-200 bg-amber-50/40"],
        ["Skipped — already reported", infos, "border-border bg-muted/30"],
      ].map(([title, issues, tones]) =>
        (issues as typeof errors).length > 0 ? (
          <Card key={title as string} className={tones as string}>
            <CardHeader>
              <CardTitle>
                {title as string} ({(issues as typeof errors).length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2">
                {(issues as typeof errors).slice(0, 25).map((issue, index) => (
                  <li key={index} className="rounded border border-border bg-card p-3 text-sm">
                    <p className="font-medium">
                      Row {issue.row}
                      {issue.field ? ` · ${issue.field}` : ""} — {issue.message}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      <strong>How to fix:</strong> {issue.fix_suggestion}
                    </p>
                  </li>
                ))}
              </ul>
              {(issues as typeof errors).length > 25 && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Showing the first 25. Download the CSV for the full list.
                </p>
              )}
            </CardContent>
          </Card>
        ) : null,
      )}

      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          onClick={() =>
            download(`/institution/uploads/${report.upload_id}/errors.csv`, `upload_${report.upload_id}_errors.csv`)
          }
        >
          <Download className="h-4 w-4" />
          Download error CSV
        </Button>
        <Button asChild variant="outline">
          <Link href="/institution/seat-matrix">See the seat matrix</Link>
        </Button>
        <Button variant="ghost" onClick={onAgain}>
          Upload another file
        </Button>
      </div>

      {report.rows_ok > 0 && (
        <p className="flex items-center gap-2 text-sm text-emerald-700">
          <CheckCircle2 className="h-4 w-4" />
          {report.enrolments_created ?? report.rows_ok} enrolment(s) stored. Contact details were
          hashed; APAAR, name and date of birth went to the encrypted vault.
        </p>
      )}
    </div>
  );
}
