"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { FieldList, PageHeader, SectionCard } from "@/components/ui/page";
import { ErrorState, Skeleton } from "@/components/States";
import { Badge, Button, Input, Label, Select, Spinner, Textarea } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ChecklistBadge } from "@/components/DocumentStatusBadge";
import { api, openFile } from "@/lib/api";
import { dateOnly, dateTime } from "@/lib/format";

const CORRECTABLE = [
  { value: "category", label: "Category" },
  { value: "gender", label: "Gender" },
  { value: "dob", label: "Date of birth" },
  { value: "student_name", label: "Name spelling" },
  { value: "phone", label: "Phone number" },
  { value: "email", label: "Email address" },
  { value: "guardian_phone", label: "Guardian contact" },
  { value: "year_of_study", label: "Year of study" },
];

export default function MyRecordsPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["student-me"], queryFn: api.studentMe });
  const corrections = useQuery({ queryKey: ["student-corrections"], queryFn: api.corrections });
  const documents = useQuery({ queryKey: ["student-documents"], queryFn: api.myDocuments });

  const [field, setField] = useState(CORRECTABLE[0].value);
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [enrolmentId, setEnrolmentId] = useState<string>("");

  const submit = useMutation({
    mutationFn: () =>
      api.requestCorrection({
        enrolment_id: enrolmentId ? Number(enrolmentId) : undefined,
        field,
        correct_value: value.trim(),
        note: note.trim() || undefined,
      }),
    onSuccess: () => {
      toast("Sent to your institution. They will see it in their flag inbox.", "success");
      setValue("");
      setNote("");
      queryClient.invalidateQueries({ queryKey: ["student-corrections"] });
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  if (me.isError) return <ErrorState error={me.error} onRetry={me.refetch} />;
  if (me.isLoading || !me.data) return <Skeleton rows={4} height="h-28" />;

  const { student, enrolments } = me.data;

  return (
    <>
      <PageHeader
        title="My records"
        description="Everything the platform holds about you, and how to get anything wrong put right."
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <SectionCard title="Your identity">
          <FieldList
            fields={[
              { label: "APAAR ID", value: student.apaar_masked },
              { label: "APAAR status", value: student.apaar_status.replace("_", " ") },
              { label: "Name", value: student.name ?? "—" },
              { label: "Date of birth", value: dateOnly(student.dob) },
              { label: "Category", value: student.category ?? "not reported" },
              { label: "Gender", value: student.gender ?? "not reported" },
              { label: "Nationality", value: student.nationality_status },
            ]}
          />
          <p className="mt-6 rounded-md bg-secondary/60 p-4 text-xs leading-relaxed text-muted-foreground">
            Your phone number, email and guardian contact are not shown because they are not stored:
            the platform keeps only a keyed hash, which cannot be turned back into the number.
            Matching for fraud detection happens on those hashes.
          </p>
        </SectionCard>

        <SectionCard
          title="Ask for a correction"
          description="This goes to your institution, who see it in their flag inbox."
        >
            <form
              className="space-y-3"
              onSubmit={(event) => {
                event.preventDefault();
                submit.mutate();
              }}
            >
              {enrolments.length > 1 && (
                <div className="space-y-1.5">
                  <Label htmlFor="enrolment">Which enrolment?</Label>
                  <Select
                    id="enrolment"
                    value={enrolmentId}
                    onChange={(event) => setEnrolmentId(event.target.value)}
                  >
                    <option value="">Most recent</option>
                    {enrolments.map((enrolment) => (
                      <option key={enrolment.id} value={String(enrolment.id)}>
                        {enrolment.institution_name} · {enrolment.academic_year}
                      </option>
                    ))}
                  </Select>
                </div>
              )}
              <div className="space-y-1.5">
                <Label htmlFor="field">What is wrong?</Label>
                <Select id="field" value={field} onChange={(event) => setField(event.target.value)}>
                  {CORRECTABLE.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="value">What should it be?</Label>
                <Input
                  id="value"
                  value={value}
                  onChange={(event) => setValue(event.target.value)}
                  placeholder="e.g. EWS"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="note">Anything to add? (optional)</Label>
                <Textarea
                  id="note"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="e.g. Fresh certificate issued in July 2026."
                />
              </div>
              <Button type="submit" disabled={!value.trim() || submit.isPending} className="w-full">
                {submit.isPending && <Spinner />}
                Send to my institution
              </Button>
            </form>
        </SectionCard>
      </div>

      <SectionCard title="My correction requests">
          {corrections.isLoading ? (
            <Skeleton rows={2} />
          ) : (corrections.data?.items.length ?? 0) === 0 ? (
            <p className="text-sm text-muted-foreground">You have not asked for any corrections.</p>
          ) : (
            <ul className="divide-y divide-border">
              {corrections.data!.items.map((item) => (
                <li key={item.correction_id} className="flex flex-wrap items-center gap-2 py-2.5 text-sm">
                  <span className="font-medium">{item.field}</span>
                  <span className="text-muted-foreground">→ {item.correct_value}</span>
                  <Badge tone={item.status === "accepted" ? "success" : "warning"}>
                    {item.status.replace(/_/g, " ")}
                  </Badge>
                  <span className="ml-auto text-xs text-muted-foreground">
                    {item.institution_name} · {dateTime(item.created_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
      </SectionCard>

      <SectionCard
        title="Documents your institution submitted"
        description="You can open any of them. Each opening is recorded in your access log, like any other access."
        bodyClassName="p-0"
      >
        {(documents.data?.items.length ?? 0) === 0 ? (
          <p className="p-5 text-sm text-muted-foreground">No documents have been submitted for you yet.</p>
        ) : (
          <ul className="divide-y divide-border">
            {documents.data!.items.map((item) => (
              <li key={item.id} className="flex flex-wrap items-center gap-3 p-4">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{item.label}</p>
                  <p className="text-xs text-muted-foreground">
                    {item.institution_name} · {dateTime(item.uploaded_at)}
                  </p>
                </div>
                <ChecklistBadge status={item.status as "uploaded" | "verified" | "rejected"} />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    openFile(`/student/documents/${item.id}/file`).catch((error: Error) =>
                      toast(error.message, "danger"),
                    )
                  }
                >
                  View
                </Button>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
    </>
  );
}
