"use client";

/** One badge vocabulary for documents, used by institutions, officers and students. */
import { Badge } from "@/components/ui/primitives";
import type { ChecklistStatus, VerificationStatus } from "@/lib/types";

const CHECKLIST: Record<ChecklistStatus, { label: string; tone: "neutral" | "warning" | "success" | "danger" }> = {
  missing: { label: "missing", tone: "neutral" },
  uploaded: { label: "uploaded", tone: "warning" },
  verified: { label: "verified", tone: "success" },
  rejected: { label: "rejected", tone: "danger" },
};

const VERIFICATION: Record<VerificationStatus, { label: string; tone: "neutral" | "warning" | "success" | "danger" }> = {
  pending: { label: "checking", tone: "neutral" },
  auto_verified: { label: "auto-verified", tone: "success" },
  needs_review: { label: "needs officer review", tone: "warning" },
  verified: { label: "verified by officer", tone: "success" },
  rejected: { label: "rejected", tone: "danger" },
};

export function ChecklistBadge({ status }: { status: ChecklistStatus }) {
  const entry = CHECKLIST[status];
  return <Badge tone={entry.tone}>{entry.label}</Badge>;
}

export function VerificationBadge({ status }: { status: VerificationStatus }) {
  const entry = VERIFICATION[status] ?? VERIFICATION.pending;
  return <Badge tone={entry.tone}>{entry.label}</Badge>;
}
