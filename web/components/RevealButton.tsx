"use client";

/**
 * Reveal a student's real identifiers. Officer only, reason mandatory (min 10 chars),
 * and the UI says plainly that the access is logged and visible to the student
 * (CLAUDE.md section 5 rules 6 and 7).
 */
import { useMutation } from "@tanstack/react-query";
import { Eye, ShieldAlert } from "lucide-react";
import { useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button, Label, Spinner, Textarea } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateOnly } from "@/lib/format";
import type { Revealed } from "@/lib/types";
import { useToast } from "@/components/ui/toast";

const MIN_REASON = 10;

export function RevealButton({
  studentId,
  label = "Reveal details",
  size = "sm",
}: {
  studentId: number;
  label?: string;
  size?: "sm" | "default";
}) {
  const { user } = useAuth();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [revealed, setRevealed] = useState<Revealed | null>(null);

  const mutation = useMutation({
    mutationFn: () => api.reveal(studentId, reason.trim()),
    onSuccess: (data) => {
      setRevealed(data);
      toast("This access has been logged and is visible to the student.", "warning");
    },
    onError: (error: Error) => toast(error.message, "danger"),
  });

  // Only an officer may reveal; for anyone else the control is not rendered at all.
  if (user?.role !== "aicte_officer") return null;

  function close() {
    setOpen(false);
    setReason("");
    setRevealed(null);
    mutation.reset();
  }

  return (
    <>
      <Button size={size} variant="outline" onClick={() => setOpen(true)}>
        <Eye className="h-3.5 w-3.5" />
        {label}
      </Button>

      <Dialog open={open} onOpenChange={(next) => (next ? setOpen(true) : close())}>
        <DialogContent>
          {!revealed ? (
            <>
              <DialogHeader>
                <DialogTitle>Reveal student details</DialogTitle>
                <DialogDescription>
                  This decrypts the student&apos;s APAAR ID, full name and date of birth. The
                  access is written to the audit trail and appears in the student&apos;s own
                  &ldquo;who accessed my data&rdquo; timeline.
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-2">
                <Label htmlFor="reveal-reason">Reason (required)</Label>
                <Textarea
                  id="reveal-reason"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="e.g. Verifying duplicate enrolment case #501 with both institutions."
                />
                <p className="text-xs text-muted-foreground">
                  {reason.trim().length < MIN_REASON
                    ? `At least ${MIN_REASON} characters — ${MIN_REASON - reason.trim().length} to go.`
                    : "This reason will be stored with your name and shown to the student."}
                </p>
              </div>

              <DialogFooter>
                <Button variant="ghost" onClick={close}>
                  Cancel
                </Button>
                <Button
                  disabled={reason.trim().length < MIN_REASON || mutation.isPending}
                  onClick={() => mutation.mutate()}
                >
                  {mutation.isPending && <Spinner />}
                  Reveal and log
                </Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>Student details</DialogTitle>
                <DialogDescription className="flex items-start gap-2 text-amber-800">
                  <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                  {revealed.notice}
                </DialogDescription>
              </DialogHeader>

              <dl className="grid gap-3 sm:grid-cols-2">
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">APAAR ID</dt>
                  <dd className="font-mono text-sm">{revealed.apaar_id ?? "not applicable"}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">Name</dt>
                  <dd className="text-sm">{revealed.name ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">
                    Date of birth
                  </dt>
                  <dd className="text-sm">{dateOnly(revealed.dob)}</dd>
                </div>
                <div>
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">Status</dt>
                  <dd className="text-sm">
                    {revealed.nationality_status}
                    {revealed.is_minor ? " · minor" : ""}
                  </dd>
                </div>
              </dl>

              <div className="mt-4">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Enrolments on record
                </p>
                <ul className="space-y-2">
                  {revealed.enrolments.map((enrolment) => (
                    <li key={enrolment.id} className="rounded border border-border p-2 text-sm">
                      <p className="font-medium">{enrolment.institution_name}</p>
                      <p className="text-xs text-muted-foreground">
                        {enrolment.program} · {enrolment.mode} · {enrolment.academic_year} · year{" "}
                        {enrolment.year_of_study} · {enrolment.status}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>

              <p className="mt-3 text-xs text-muted-foreground">
                Contact details are never returned, even here.
              </p>

              <DialogFooter>
                <Button onClick={close}>Close</Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
