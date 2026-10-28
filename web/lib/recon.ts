import type { ReconStatus } from "./types";

/** Years the platform holds records for (reporting_calendar.yaml). */
export const RECON_YEARS = ["2026-27", "2025-26"];
export const CURRENT_YEAR = "2026-27";

export const RECON_LABELS: Record<ReconStatus, string> = {
  confirmed: "Confirmed",
  needs_review: "Needs review",
  rejected: "Rejected",
};

/** Save text the page already holds (a CSV template) as a file. */
export function saveText(text: string, filename: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
