"use client";

/** Confirmed / Needs review / Rejected, and the per-check pass / review / fail. */
import { Badge } from "@/components/ui/primitives";
import { RECON_LABELS } from "@/lib/recon";
import type { CheckResult, ReconStatus } from "@/lib/types";

const TONE: Record<ReconStatus, "success" | "warning" | "danger"> = {
  confirmed: "success",
  needs_review: "warning",
  rejected: "danger",
};

export function ReconBadge({ status }: { status: ReconStatus }) {
  return <Badge tone={TONE[status]}>{RECON_LABELS[status]}</Badge>;
}

const CHECK_TONE: Record<CheckResult, "success" | "warning" | "danger"> = {
  pass: "success",
  review: "warning",
  fail: "danger",
};

export function CheckBadge({ result }: { result: CheckResult }) {
  return <Badge tone={CHECK_TONE[result]}>{result}</Badge>;
}
