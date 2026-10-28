/**
 * Types mirroring docs/API_CONTRACT.md. Keep this file in step with the contract:
 * if a shape changes, change the contract first.
 */

export type Role =
  | "institution"
  | "aicte_viewer"
  | "aicte_officer"
  | "student"
  | "verifier"
  | "admin";

export type Severity = "low" | "medium" | "high" | "critical";
export type FlagStatus = "open" | "under_review" | "escalated" | "dismissed" | "resolved";
export type ApaarStatus = "provided" | "pending" | "not_applicable";
export type EnrolmentStatus = "admitted" | "cancelled" | "migrated" | "dropped" | "completed";
export type AdmissionType =
  | "regular"
  | "lateral"
  | "tfw"
  | "fn_pio_oci"
  | "pmsss"
  | "other_supernumerary";
export type ConsentStatus = "pending" | "approved" | "denied" | "revoked" | "expired";
export type TokenState = "genuine" | "expired" | "revoked" | "invalid";

/** A count that small-count suppression may replace with "<5" for aicte_viewer. */
export type Suppressible = number | "<5";

export const FLAG_TYPES = [
  "INVALID_APAAR",
  "APAAR_NOT_FOUND",
  "APAAR_MISMATCH",
  "DUPLICATE_IN_UPLOAD",
  "EXCESS_INTAKE",
  "CROSS_INSTITUTION_DUPLICATE",
  "POSSIBLE_DUAL_DEGREE",
  "IDENTITY_DUPLICATE",
  "LATE_ADMISSION",
  "STUDENT_CORRECTION",
] as const;
export type FlagType = (typeof FLAG_TYPES)[number];

export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  sort?: string | null;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> };
}

// ----------------------------------------------------------------- auth

export interface User {
  id: number;
  username: string;
  display_name: string;
  role: Role;
  institution_id?: number | null;
  student_id?: number | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface DemoUser {
  username: string;
  password: string;
  role: Role;
  label: string;
}

// ----------------------------------------------------------------- institution

export interface Program {
  id: number;
  course: string;
  branch: string;
  level: string;
  mode: "regular" | "online";
}

export interface InstitutionProfile {
  id: number;
  aicte_permanent_id: string;
  name: string;
  state: string;
  region: string;
  type: string;
  programs: Program[];
}

export interface ColumnProposal {
  source_column: string;
  field: string | null;
  confidence: number;
  sample_values: string[];
}

export interface UploadCreated {
  upload_id: number;
  filename: string;
  state: string;
  rows_total: number;
  blank_rows_skipped: number;
  detected_sheet?: string | null;
  proposed_mapping: ColumnProposal[];
  unmapped_required_fields: string[];
  available_fields: string[];
}

export interface RowIssue {
  row: number;
  severity: "error" | "warning" | "info";
  code: string;
  field?: string | null;
  message: string;
  value_masked?: string | null;
  fix_suggestion: string;
}

export interface QualityReport {
  upload_id: number;
  filename: string;
  state: string;
  academic_year?: string | null;
  quality_score?: number | null;
  rows_total: number;
  rows_ok: number;
  rows_error: number;
  rows_warning: number;
  blank_rows_skipped: number;
  already_reported: number;
  enrolments_created?: number | null;
  students_created?: number | null;
  registry_check: Record<string, number>;
  issue_counts: Record<string, number>;
  flags_created: { id: number; type: FlagType; severity: Severity }[];
  issues: RowIssue[];
  issues_truncated: boolean;
  column_mapping: Record<string, string | null>;
  errors_csv_url: string;
  created_at: string;
}

export interface UploadSummary {
  id: number;
  filename: string;
  state: string;
  academic_year?: string | null;
  rows_total: number;
  rows_ok: number;
  rows_error: number;
  rows_warning: number;
  quality_score?: number | null;
  created_at: string;
}

export interface SupernumeraryBucket {
  admission_type: AdmissionType;
  label: string;
  admitted: number;
  cap: number;
  cap_basis: string;
  valid: number;
  excess: number;
}

export interface ProgramSeatMatrix {
  program_id: number;
  course: string;
  branch: string;
  mode: string;
  academic_year: string;
  approved_intake: number;
  regular_admitted: number;
  regular_excess: number;
  supernumerary: SupernumeraryBucket[];
  total_admitted: number;
  valid_supernumerary: number;
  supernumerary_excess: number;
  vacant_regular_seats: number;
  excess: number;
  explanation: string;
  rule_set: string;
  flag_id?: number | null;
}

export interface SeatMatrix {
  academic_year: string;
  rule_set: string;
  programs: ProgramSeatMatrix[];
  totals: {
    approved_intake: number;
    regular_admitted: number;
    valid_supernumerary: number;
    total_admitted: number;
    excess: number;
  };
}

export interface InstitutionFlag {
  id: number;
  type: FlagType;
  severity: Severity;
  status: FlagStatus;
  title: string;
  explanation: string;
  evidence: Record<string, unknown>;
  student_id?: number | null;
  enrolment_id?: number | null;
  program_id?: number | null;
  academic_year?: string | null;
  created_at: string;
}

export interface StudentRow {
  student_id: number;
  apaar_masked: string;
  apaar_status: ApaarStatus;
  name_masked: string;
  gender?: string | null;
  category?: string | null;
  nationality_status: string;
  dob_year?: number | null;
  is_minor: boolean;
  flag_count: number;
  enrolment: {
    id: number;
    program_id: number;
    course: string;
    branch: string;
    academic_year: string;
    year_of_study: number;
    admission_type: AdmissionType;
    status: EnrolmentStatus;
    admitted_on?: string | null;
    version: number;
  };
}

export interface InstitutionDashboard {
  academic_year: string;
  students_reported: number;
  open_flags: Record<Severity, number>;
  latest_quality_score?: number | null;
  quality_trend: { upload_id: number; created_at: string; quality_score?: number | null }[];
  seat_matrix_summary: SeatMatrix["totals"];
  last_upload_at?: string | null;
}

// ----------------------------------------------------------------- aicte

export interface Overview {
  academic_year: string;
  kpis: {
    institutions_total: Suppressible;
    institutions_reporting: Suppressible;
    institutions_non_reporting: Suppressible;
    students_reported: Suppressible;
    total_excess_seats: Suppressible;
    open_flags: Record<Severity, Suppressible>;
    avg_data_quality?: number | null;
  };
  flags_by_type: { type: FlagType; count: Suppressible; max_severity: Severity }[];
  by_state: {
    state: string;
    institutions: Suppressible;
    institutions_reporting: Suppressible;
    students_reported: Suppressible;
    open_flags: Suppressible;
    excess_seats: Suppressible;
  }[];
  suppression_applied: boolean;
  generated_at: string;
}

export interface InstitutionRow {
  id: number;
  aicte_permanent_id: string;
  name: string;
  state: string;
  region: string;
  type: string;
  students_reported: Suppressible;
  open_flags: Record<Severity, Suppressible>;
  open_flags_total: Suppressible;
  excess_seats: Suppressible;
  last_upload_at?: string | null;
}

export interface Flag {
  id: number;
  type: FlagType;
  severity: Severity;
  status: FlagStatus;
  title: string;
  explanation: string;
  institution_id?: number | null;
  institution_name?: string | null;
  state?: string | null;
  academic_year?: string | null;
  created_at: string;
  /** Officer only; null for aicte_viewer. */
  evidence?: Record<string, unknown> | null;
  student_id?: number | null;
  enrolment_id?: number | null;
  program_id?: number | null;
  assigned_to?: string | null;
  notes?: { author: string; note: string; created_at?: string }[] | null;
}

export interface FlagDetail extends Flag {
  history: { from?: string; to?: string; actor?: string; reason?: string; at: string }[];
  related_flags: { id: number; type: FlagType; severity: Severity }[];
  students: { student_id: number; apaar_masked: string; name_masked: string; is_minor: boolean }[];
}

export interface FlagPage extends Page<Flag> {
  facets: {
    by_type: Record<string, Suppressible>;
    by_severity: Record<string, Suppressible>;
    by_status: Record<string, Suppressible>;
  };
}

export interface AicteInstitutionProfile {
  institution: { id: number; aicte_permanent_id: string; name: string; state: string; region: string; type: string };
  reporting: { uploads: number; last_upload_at?: string | null; students_reported: number; avg_quality_score?: number | null };
  seat_matrix_summary: SeatMatrix["totals"];
  flags: Flag[];
  upload_timeline: { upload_id: number; filename: string; created_at: string; rows_ok: number; rows_error: number; quality_score?: number | null }[];
}

export interface Trends {
  dimension: string;
  academic_years: string[];
  series: { key: string; values: Record<string, Suppressible>; yoy_growth_pct?: number | null }[];
  notes: string[];
  new_admissions_only: boolean;
  csv_url: string;
}

export interface Revealed {
  student_id: number;
  apaar_id?: string | null;
  apaar_status: string;
  name?: string | null;
  dob?: string | null;
  gender?: string | null;
  category?: string | null;
  nationality_status: string;
  is_minor: boolean;
  enrolments: {
    id: number;
    institution_id: number;
    institution_name: string;
    program: string;
    mode: string;
    academic_year: string;
    year_of_study: number;
    admission_type: string;
    status: string;
    admitted_on?: string | null;
  }[];
  access_log_id: number;
  revealed_at: string;
  notice: string;
}

// ----------------------------------------------------------------- student

export interface StudentMe {
  student: {
    student_id: number;
    apaar_masked: string;
    apaar_status: ApaarStatus;
    name?: string | null;
    dob?: string | null;
    is_minor: boolean;
    nationality_status: string;
    category?: string | null;
    gender?: string | null;
  };
  enrolments: {
    id: number;
    institution_name: string;
    program: string;
    mode: string;
    academic_year: string;
    year_of_study: number;
    admission_type: string;
    status: EnrolmentStatus;
    admitted_on?: string | null;
    reported_by_upload_at?: string | null;
    version: number;
  }[];
  open_cases: { flag_id: number; type: FlagType; status: FlagStatus; created_at: string }[];
  pending_consents: number;
}

export interface AccessLogRow {
  id: number;
  at: string;
  actor_role: Role;
  actor_label: string;
  action: string;
  reason?: string | null;
  purpose?: string | null;
  target: string;
}

export interface ConsentRow {
  consent_id: number;
  status: ConsentStatus;
  verifier_name: string;
  verifier_type?: string | null;
  purpose: string;
  purpose_label: string;
  will_share: string[];
  requested_at: string;
  responded_at?: string | null;
  revoked_at?: string | null;
  expires_at?: string | null;
  parental_consent_required: boolean;
}

export interface IdCard {
  apaar_masked: string;
  name?: string | null;
  institution_name?: string | null;
  program?: string | null;
  academic_year?: string | null;
  year_of_study?: number | null;
  status?: string | null;
  is_minor: boolean;
  token: string;
  token_expires_at: string;
  qr_png_base64: string;
  verify_url: string;
}

// ----------------------------------------------------------------- verifier

export interface VerificationRequestStatus {
  request_id: number;
  status: "pending" | "approved" | "denied" | "expired" | "revoked";
  apaar_masked: string;
  purpose: string;
  requested_at: string;
  responded_at?: string | null;
  expires_at?: string | null;
  result?: { verified: boolean; program?: string | null; academic_year?: string | null } | null;
}

export interface TokenCheck {
  state: TokenState;
  verified?: boolean | null;
  program?: string | null;
  academic_year?: string | null;
  institution_name?: string | null;
  checked_at: string;
}

// ----------------------------------------------------------------- admin

export interface AdminStatus {
  counts: Record<string, number>;
  flags_by_type: Record<string, number>;
  audit: { ok: boolean; rows_checked: number; rows_total: number; first_broken_row?: Record<string, unknown> | null };
  current_academic_year: string;
  demo_mode: boolean;
}

export interface TamperResult {
  copy_rows: number;
  tampered_row_id?: number;
  detected: boolean;
  first_broken_row_id?: number | null;
  message: string;
}
