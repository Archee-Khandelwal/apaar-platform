import type { Severity, Suppressible } from "./types";

/** Render a count that may have been suppressed to "<5" for an AICTE analyst. */
export function count(value: Suppressible | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  return value.toLocaleString("en-IN");
}

export function isSuppressed(value: Suppressible | null | undefined): boolean {
  return typeof value === "string";
}

export function dateTime(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function dateOnly(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function relative(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value).getTime();
  if (Number.isNaN(parsed)) return value;
  const seconds = Math.round((Date.now() - parsed) / 1000);
  const units: [number, string][] = [
    [60, "second"],
    [3600, "minute"],
    [86400, "hour"],
    [2592000, "day"],
  ];
  if (seconds < 60) return "just now";
  for (let index = 1; index < units.length; index += 1) {
    const [limit, name] = units[index];
    if (seconds < limit) {
      const size = Math.round(seconds / units[index - 1][0]);
      return `${size} ${name}${size === 1 ? "" : "s"} ago`;
    }
  }
  return dateOnly(value);
}

/** PS field names for nationality status, e.g. nri -> "NRI Category". */
export const NATIONALITY_LABELS: Record<string, string> = {
  indian: "Indian",
  nri: "NRI Category",
  oci: "OCI Status",
  fn: "Foreign National (FN) Status",
};

export function nationalityLabel(value: string): string {
  return NATIONALITY_LABELS[value] ?? value;
}

/** Human label for a flag type, e.g. EXCESS_INTAKE -> "Excess intake". */
export function flagLabel(type: string): string {
  const words = type.toLowerCase().split("_");
  const special: Record<string, string> = { apaar: "APAAR", tfw: "TFW", oci: "OCI", pio: "PIO" };
  return words
    .map((word, index) =>
      special[word] ?? (index === 0 ? word[0].toUpperCase() + word.slice(1) : word),
    )
    .join(" ");
}

export const SEVERITY_ORDER: Record<Severity, number> = {
  low: 1,
  medium: 2,
  high: 3,
  critical: 4,
};

export function percent(value?: number | null, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(digits)}%`;
}
