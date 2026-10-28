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
  /** Set after an admin reset: the only thing this session may do is change it. */
  must_change_password?: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

/** A demo account's name. Passwords are never sent; they are in demo_credentials.csv. */
export interface DemoUser {
  username: string;
  role: Role;
  label: string;
}

export interface AdminUser {
  id: number;
  username: string;
  role: Role;
  display_name: string;
  institution_id?: number | null;
  is_active: boolean;
  must_change_password: boolean;
  last_login_at?: string | null;
  password_changed_at?: string | null;
}

export interface PasswordReset {
  user_id: number;
  username: string;
  temporary_password: string;
  must_change_password: boolean;
  audit_log_id: number;
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

// ----------------------------------------------------------------- documents

export type ChecklistStatus = "missing" | "uploaded" | "verified" | "rejected";
export type VerificationStatus = "pending" | "auto_verified" | "needs_review" | "rejected" | "verified";

export interface DocumentReason {
  code: string;
  message: string;
  severity?: "info" | "warning" | "error";
}

export interface DocumentSummary {
  id: number;
  doc_type: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  uploaded_at: string;
  uploaded_by?: string | null;
  upload_channel: string;
  verification_status: VerificationStatus;
  issuer_status: string;
  integrity_ok: boolean;
  reasons: DocumentReason[];
  review_decision?: string | null;
  review_reason?: string | null;
}

export interface StudentChecklist {
  student_id: number;
  apaar_masked: string;
  name_masked: string;
  nationality_status: string;
  category?: string | null;
  admission_type: string;
  academic_year: string;
  items: { doc_type: string; label: string; status: ChecklistStatus; document?: DocumentSummary | null }[];
  counts: Record<ChecklistStatus, number>;
  complete: boolean;
}

export interface DocumentOverviewRow {
  student_id: number;
  apaar_masked: string;
  name_masked: string;
  admission_type: string;
  nationality_status: string;
  required: number;
  counts: Record<ChecklistStatus, number>;
  status: ChecklistStatus;
  missing: string[];
}

export interface DocumentOverviewPage extends Page<DocumentOverviewRow> {
  totals: Record<ChecklistStatus, number>;
}

export interface DocumentRules {
  checklist_set: string;
  document_types: { doc_type: string; label: string; issuer_kind?: string | null }[];
  required: Record<string, unknown>;
  limits: { max_file_mb?: number; zip_max_files?: number; zip_max_total_mb?: number };
}

export interface BulkUploadReport {
  files: number;
  stored: number;
  rejected: number;
  skipped: number;
  results: {
    file: string;
    status: "stored" | "rejected" | "skipped";
    reason?: string | null;
    doc_type?: string | null;
    student_id?: number | null;
    document_id?: number | null;
  }[];
}

export interface ReviewRow {
  document_id: number;
  doc_type: string;
  label: string;
  verification_status: VerificationStatus;
  issuer_status: string;
  issuer_label: string;
  reasons: DocumentReason[];
  student_id: number;
  apaar_masked: string;
  name_masked: string;
  institution_id: number;
  institution_name: string;
  uploaded_at: string;
}

export interface ReviewPage extends Page<ReviewRow> {
  counts: Record<string, number>;
}

export interface CaseFile {
  document_id: number;
  doc_type: string;
  label: string;
  content_type: string;
  sha256: string;
  uploaded_at: string;
  uploaded_by?: string | null;
  verification_status: VerificationStatus;
  reasons: DocumentReason[];
  student: { student_id: number; apaar_masked: string; apaar?: string | null; is_minor: boolean; nationality_status: string };
  institution?: { id: number; name: string } | null;
  comparison: { field: string; submitted?: string | null; on_document?: string | null; match?: boolean | null; detail?: number | null }[];
  extracted: Record<string, unknown>;
  issuer: { status: string; label: string; issuer_name?: string; matched_by?: string; reference_no?: string; issued_on?: string; differing_facts?: string[] };
  tamper: { integrity_ok?: boolean; metadata?: { producer?: string; created?: string; modified?: string }; edited_after_issue?: string | null };
  integrity_ok: boolean;
  review: { decision?: string | null; reason?: string | null; by?: string | null; at?: string | null };
}

// ------------------------------------------------------------------ reconciliation (Phase 6)

export type ReconStatus = "confirmed" | "needs_review" | "rejected";
export type CheckResult = "pass" | "review" | "fail";

export interface ReconProblem {
  check: string;
  label: string;
  result: "review" | "fail";
  message: string;
  fix?: string | null;
}

export interface ReconRow {
  enrolment_id: number;
  student_id: number;
  apaar_masked: string;
  name_masked: string;
  institution_id: number;
  institution_name: string;
  program_id: number;
  programme: string;
  academic_year: string;
  year_of_study: number;
  admission_type: string;
  overall: ReconStatus;
  problems: ReconProblem[];
}

export interface ReconPage extends Page<ReconRow> {
  programmes: { program_id: number; label: string }[];
}

export interface ReconCounts {
  confirmed: Suppressible;
  needs_review: Suppressible;
  rejected: Suppressible;
  records: Suppressible;
}

export interface ReconInstitutionRow extends ReconCounts {
  institution_id: number;
  name: string;
  state: string;
  aicte_permanent_id: string;
}

export interface ReconSummary {
  academic_year: string;
  totals: ReconCounts;
  items: ReconInstitutionRow[];
}

export interface ReconCheck {
  check: string;
  label: string;
  result: CheckResult;
  message: string;
  fix?: string | null;
}

export interface ReconDetail extends ReconRow {
  submitted: Record<string, string | number | boolean | null>;
  apaar: { apaar_status: string; registry_status: string | null; result: string };
  master: {
    institution_status: string | null;
    institution_reference: string | null;
    programme_status: string | null;
    approved_intake: number | null;
    supernumerary_caps: Record<string, number>;
  };
  documents: { doc_type: string; label: string; status: string; issuer_status: string | null; document_id: number | null }[];
  checks: ReconCheck[];
  computed_at: string;
}

export interface InstitutionRecon {
  academic_year: string;
  counts: Record<ReconStatus, number>;
  records: number;
  to_fix: { check: string; label: string; result: string; fix?: string | null; example: string; records: number }[];
  items: ReconRow[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface MasterImport {
  id: number;
  kind: string;
  filename: string;
  rows_total: number;
  rows_ok: number;
  rows_error: number;
  issues: { row: number; message: string }[];
  actor: string;
  created_at: string;
}

export interface MasterStatus {
  approvals: Record<string, number>;
  programme_records: Record<string, number>;
  imports: MasterImport[];
}
