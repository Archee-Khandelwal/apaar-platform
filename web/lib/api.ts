/**
 * Typed API client for docs/API_CONTRACT.md.
 *
 * The JWT lives in memory. It is mirrored into sessionStorage so a page refresh does
 * not log the demo operator out, and every sessionStorage access is wrapped in
 * try/catch because it throws in private windows and when site data is blocked.
 */
import type {
  AccessLogRow,
  AdminStatus,
  AicteInstitutionProfile,
  ApiErrorBody,
  ConsentRow,
  AdminUser,
  BulkUploadReport,
  CaseFile,
  ReviewPage,
  DocumentOverviewPage,
  DocumentRules,
  DocumentSummary,
  StudentChecklist,
  DemoUser,
  PasswordReset,
  Flag,
  FlagDetail,
  FlagPage,
  IdCard,
  InstitutionRecon,
  MasterImport,
  MasterStatus,
  ReconDetail,
  ReconPage,
  ReconSummary,
  InstitutionDashboard,
  InstitutionFlag,
  InstitutionProfile,
  InstitutionRow,
  LoginResponse,
  Overview,
  Page,
  QualityReport,
  Revealed,
  SeatMatrix,
  StudentMe,
  StudentRow,
  TokenCheck,
  DegreeCertificateList,
  DegreeCertificateOut,
  DocumentCheck,
  Trends,
  UploadCreated,
  TamperResult,
  UploadSummary,
  User,
  VerificationRequestStatus,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "apaar.token";
const USER_KEY = "apaar.user";

let token: string | null = null;
let currentUser: User | null = null;

function readStored<T>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null; // private window, blocked storage, or malformed value
  }
}

function writeStored(key: string, value: unknown) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage is a convenience, never a requirement */
  }
}

export function setSession(nextToken: string | null, nextUser: User | null) {
  token = nextToken;
  currentUser = nextUser;
  writeStored(TOKEN_KEY, nextToken);
  writeStored(USER_KEY, nextUser);
}

export function restoreSession(): { token: string | null; user: User | null } {
  if (token === null) token = readStored<string>(TOKEN_KEY);
  if (currentUser === null) currentUser = readStored<User>(USER_KEY);
  return { token, user: currentUser };
}

export function getToken() {
  return token;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Query = Record<string, string | number | boolean | undefined | null | (string | number)[]>;

function queryString(query?: Query): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((item) => params.append(key, String(item)));
    else params.append(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

async function request<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    query?: Query;
    raw?: boolean;
    blob?: boolean;
    form?: FormData;
  } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(`${API_URL}${path}${queryString(options.query)}`, {
    method: options.method ?? "GET",
    headers,
    body: options.form ?? (options.body !== undefined ? JSON.stringify(options.body) : undefined),
  });

  if (!response.ok) {
    let code = `HTTP_${response.status}`;
    let message = response.statusText || "Request failed";
    let details: Record<string, unknown> | undefined;
    try {
      const body = (await response.json()) as ApiErrorBody;
      if (body?.error) {
        code = body.error.code;
        message = body.error.message;
        details = body.error.details;
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, code, message, details);
  }

  if (options.blob) return (await response.blob()) as unknown as T;
  if (options.raw) return (await response.text()) as unknown as T;
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Build a download URL that carries the bearer token via fetch, not the address bar. */
export async function download(path: string, filename: string, query?: Query) {
  const text = await request<string>(path, { raw: true, query });
  const blob = new Blob([text], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/** Open a binary response (a PDF or an image) in a new tab, without the token in the URL. */
export async function openFile(path: string, init?: { method?: string; body?: unknown }) {
  const blob = await request<Blob>(path, { blob: true, method: init?.method, body: init?.body });
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** Fetch a binary response as an object URL, for showing a document inline. */
export async function fileUrl(path: string, init?: { method?: string; body?: unknown }) {
  const blob = await request<Blob>(path, { blob: true, method: init?.method, body: init?.body });
  return { url: URL.createObjectURL(blob), type: blob.type };
}

export const api = {
  // ----------------------------------------------------------------- auth
  health: () => request<{ status: string; registry: string; synthetic_data: boolean }>("/health"),
  login: (username: string, password: string) =>
    request<LoginResponse>("/auth/login", { method: "POST", body: { username, password } }),
  me: () => request<User>("/auth/me"),
  demoUsers: () => request<{ demo_mode: boolean; users: DemoUser[] }>("/auth/demo-users"),
  changePassword: (current_password: string, new_password: string) =>
    request<{ status: string; access_token: string; expires_in: number }>("/auth/change-password", {
      method: "POST",
      body: { current_password, new_password },
    }),

  // ----------------------------------------------------------------- institution
  institutionMe: () => request<InstitutionProfile>("/institution/me"),
  documentRules: () => request<DocumentRules>("/institution/documents/rules"),
  documentsOverview: (query?: Query) => request<DocumentOverviewPage>("/institution/documents", { query }),
  studentChecklist: (studentId: number) =>
    request<StudentChecklist>(`/institution/students/${studentId}/documents`),
  uploadDocument: (studentId: number, docType: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    form.append("doc_type", docType);
    return request<DocumentSummary>(`/institution/students/${studentId}/documents`, {
      method: "POST",
      form,
    });
  },
  uploadDocumentsZip: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<BulkUploadReport>("/institution/documents/bulk", { method: "POST", form });
  },
  institutionRecon: (query?: Query) => request<InstitutionRecon>("/institution/reconciliation", { query }),
  institutionDashboard: (academic_year?: string) =>
    request<InstitutionDashboard>("/institution/dashboard", { query: { academic_year } }),
  createUpload: (file: File, academicYear?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (academicYear) form.append("academic_year", academicYear);
    return request<UploadCreated>("/institution/uploads", { method: "POST", form });
  },
  confirmMapping: (
    uploadId: number,
    mapping: Record<string, string | null>,
    defaults: Record<string, string> = {},
  ) =>
    request<QualityReport>(`/institution/uploads/${uploadId}/confirm-mapping`, {
      method: "POST",
      body: { mapping, defaults },
    }),
  uploads: (query?: Query) => request<Page<UploadSummary>>("/institution/uploads", { query }),
  upload: (uploadId: number) => request<QualityReport>(`/institution/uploads/${uploadId}`),
  seatMatrix: (academic_year: string) =>
    request<SeatMatrix>("/institution/seat-matrix", { query: { academic_year } }),
  institutionFlags: (query?: Query) =>
    request<Page<InstitutionFlag>>("/institution/flags", { query }),
  updateInstitutionFlag: (flagId: number, body: { status?: string; note?: string }) =>
    request<InstitutionFlag>(`/institution/flags/${flagId}`, { method: "PATCH", body }),
  students: (query?: Query) => request<Page<StudentRow>>("/institution/students", { query }),
  changeEnrolmentStatus: (
    enrolmentId: number,
    body: { status: string; reason: string; effective_date?: string },
  ) =>
    request<{ enrolment_id: number; status: string; version: number }>(
      `/institution/enrolments/${enrolmentId}/status`,
      { method: "PATCH", body },
    ),

  // ----------------------------------------------------------------- aicte
  overview: (query?: Query) => request<Overview>("/aicte/overview", { query }),
  institutions: (query?: Query) => request<Page<InstitutionRow>>("/aicte/institutions", { query }),
  institution: (id: number, academic_year?: string) =>
    request<AicteInstitutionProfile>(`/aicte/institutions/${id}`, { query: { academic_year } }),
  institutionSeatMatrix: (id: number, academic_year: string) =>
    request<SeatMatrix>(`/aicte/institutions/${id}/seat-matrix`, { query: { academic_year } }),
  flags: (query?: Query) => request<FlagPage>("/aicte/flags", { query }),
  flag: (id: number) => request<FlagDetail>(`/aicte/flags/${id}`),
  updateFlag: (
    id: number,
    body: { status?: string; assigned_to?: string; note?: string; reason?: string },
  ) => request<{ flag: Flag; audit_log_id?: number }>(`/aicte/flags/${id}`, { method: "PATCH", body }),
  reveal: (student_id: number, reason: string) =>
    request<Revealed>("/aicte/reveal", { method: "POST", body: { student_id, reason } }),
  reviewQueue: (query?: Query) => request<ReviewPage>("/aicte/documents/review", { query }),
  documentCase: (id: number, reason: string) =>
    request<CaseFile>(`/aicte/documents/${id}/case`, { method: "POST", body: { reason } }),
  documentDecision: (id: number, decision: "approve" | "reject", reason: string) =>
    request<{ verification_status: string }>(`/aicte/documents/${id}/decision`, {
      method: "POST",
      body: { decision, reason },
    }),
  recheckDocument: (id: number) => request<DocumentSummary>(`/aicte/documents/${id}/recheck`, { method: "POST" }),
  trends: (query?: Query) => request<Trends>("/aicte/reports/trends", { query }),
  reconSummary: (query?: Query) => request<ReconSummary>("/aicte/reconciliation/summary", { query }),
  reconRecords: (query?: Query) => request<ReconPage>("/aicte/reconciliation/records", { query }),
  reconRecord: (enrolmentId: number) => request<ReconDetail>(`/aicte/reconciliation/records/${enrolmentId}`),
  masterStatus: () => request<MasterStatus>("/aicte/master"),
  masterTemplate: (kind: "institutions" | "programmes") =>
    request<string>(`/aicte/master/template/${kind}`, { raw: true }),
  masterImport: (kind: "institutions" | "programmes", file: File) => {
    const form = new FormData();
    form.append("kind", kind);
    form.append("file", file);
    return request<MasterImport>("/aicte/master/import", { method: "POST", form });
  },

  // ----------------------------------------------------------------- student
  studentMe: () => request<StudentMe>("/student/me"),
  requestCorrection: (body: {
    enrolment_id?: number;
    field: string;
    correct_value: string;
    note?: string;
  }) => request<{ correction_id: number; status: string }>("/student/corrections", { method: "POST", body }),
  corrections: () => request<Page<{ correction_id: number; field: string; correct_value: string; status: string; institution_name: string; created_at: string }>>("/student/corrections"),
  studentAccessLog: (query?: Query) => request<Page<AccessLogRow>>("/student/access-log", { query }),
  consents: (query?: Query) => request<Page<ConsentRow>>("/student/consents", { query }),
  approveConsent: (id: number) =>
    request<{ status: string; shared_fields: string[]; expires_at: string }>(
      `/student/consents/${id}/approve`,
      { method: "POST", body: {} },
    ),
  denyConsent: (id: number, reason?: string) =>
    request<{ status: string }>(`/student/consents/${id}/deny`, { method: "POST", body: { reason } }),
  revokeConsent: (id: number) =>
    request<{ status: string; tokens_invalidated: number }>(`/student/consents/${id}/revoke`, {
      method: "POST",
    }),
  idCard: () => request<IdCard>("/student/id-card"),
  myDocuments: () =>
    request<{
      items: { id: number; doc_type: string; label: string; institution_name: string; uploaded_at: string; status: string }[];
    }>("/student/documents"),

  // ----------------------------------------------------------------- verifier
  purposes: () => request<{ purposes: { value: string; label: string }[] }>("/verifier/purposes"),
  createVerification: (body: { apaar: string; purpose: string; note?: string }) =>
    request<VerificationRequestStatus & { message: string; parental_consent_required: boolean }>(
      "/verifier/requests",
      { method: "POST", body },
    ),
  verificationRequests: (query?: Query) =>
    request<Page<VerificationRequestStatus>>("/verifier/requests", { query }),
  verificationRequest: (id: number) =>
    request<VerificationRequestStatus>(`/verifier/requests/${id}`),

  // ----------------------------------------------------------------- admin
  adminStatus: () => request<AdminStatus>("/admin/status"),
  reseed: (body?: { seed?: number; institutions?: number; students?: number }) =>
    request<{ status: string; seed: number; duration_ms: number; counts: Record<string, number> }>(
      "/admin/reseed",
      { method: "POST", body: body ?? {} },
    ),
  verifyAudit: () =>
    request<{ ok: boolean; rows_checked: number; rows_total: number; first_broken_row?: unknown; checked_at: string }>(
      "/admin/audit/verify",
    ),
  tamperTest: () => request<TamperResult>("/admin/audit/tamper-test", { method: "POST" }),
  adminUsers: (query?: Query) => request<Page<AdminUser>>("/admin/users", { query }),
  resetPassword: (userId: number) =>
    request<PasswordReset>(`/admin/users/${userId}/reset-password`, { method: "POST" }),

  // public
  degreeCertificates: () => request<DegreeCertificateList>("/institution/degree-certificates"),
  issueDegreeCertificate: (enrolment_id: number) =>
    request<DegreeCertificateOut>("/institution/degree-certificates", { method: "POST", body: { enrolment_id } }),
  openDegreeCertificate: (serial: string) =>
    openFile(`/institution/degree-certificates/${encodeURIComponent(serial)}?format=pdf`),
  checkDocument: (token: string) => request<DocumentCheck>(`/verify/document/${encodeURIComponent(token)}`),
  checkToken: (token: string) => request<TokenCheck>(`/verify/token/${encodeURIComponent(token)}`),
};

export type Api = typeof api;
