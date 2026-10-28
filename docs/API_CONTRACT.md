# API_CONTRACT.md — APAAR Student Data & Verification Platform (SIH26263)

**Status: FROZEN at Step 0.** Any change goes through this file first (edit here, note it in the changelog at the bottom, tell the frontend team).

Services:

| Service | Base URL | Notes |
|---|---|---|
| Main API | `http://localhost:8000` | FastAPI, all routers below |
| Mock APAAR registry | `http://localhost:8001` | separate FastAPI app, API-key auth |
| Web | `http://localhost:3000` | Next.js |

Interactive docs: `http://localhost:8000/docs`, `http://localhost:8001/docs`.

---

## 0. Conventions (read this first)

### 0.1 Auth

- All routes except those marked **public** require `Authorization: Bearer <jwt>`.
- JWT claims: `sub` (user id), `role`, `institution_id` (nullable), `student_id` (nullable), `exp`.
- Every route is wrapped in `require_role(...)` (CLAUDE.md §5.4). Roles: `institution`, `aicte_viewer`, `aicte_officer`, `student`, `verifier`, `admin`.
- **Tenant isolation:** for `institution` users, `institution_id` is read from the JWT only. `/institution/*` routes take no institution id in path/query/body — ever (CLAUDE.md §5.5).
- `admin` is a demo operator, **not** a superuser: it does not get read access to student data routes.

### 0.2 Masking (default everywhere)

| Field | Shape |
|---|---|
| `apaar_masked` | `"XXXX-XXXX-1234"` |
| `name_masked` | `"R***** S."` |
| `dob_year` | `2006` (year only; full DOB is vault-only) |
| contacts | never returned in any form — only `*_hash` exists in the DB, and hashes are **never** returned over the API |

Raw APAAR / full name / full DOB are returned by exactly two endpoints: `POST /aicte/reveal` (officer + reason) and `GET /student/me`-family endpoints (the student's own data). Nothing else, no exceptions.

### 0.3 Small-count suppression

For role `aicte_viewer`, any count `< 5` in a breakdown is returned as the **string** `"<5"`.

Role `aicte_viewer` additionally never receives flag `evidence` internals, `notes`, `history` or `related_flags` — only `id, type, severity, status, title, explanation, institution_name, state, created_at` — and cannot reveal, change status, assign or add notes. So breakdown values are typed `number | "<5"` in the TS client (CLAUDE.md §5.9). Totals are not suppressed; cell-level breakdowns are.

### 0.4 Pagination (all list endpoints)

Query params: `page` (int, default `1`, min 1), `page_size` (int, default `25`, max `200`), `sort` (string, `field` or `-field` for descending; each endpoint lists allowed fields).

Envelope:

```json
{
  "items": [],
  "page": 1,
  "page_size": 25,
  "total": 134,
  "total_pages": 6,
  "sort": "-created_at"
}
```

### 0.5 Errors

```json
{
  "error": {
    "code": "FORBIDDEN_ROLE",
    "message": "This endpoint requires role aicte_officer.",
    "details": { "required_roles": ["aicte_officer"], "actual_role": "aicte_viewer" }
  }
}
```

Codes: `VALIDATION_ERROR` (422), `BAD_CREDENTIALS` (401), `TOKEN_EXPIRED` (401), `FORBIDDEN_ROLE` (403), `TENANT_SCOPE_VIOLATION` (403), `REASON_REQUIRED` (400), `NOT_FOUND` (404), `CONFLICT` (409), `UNSUPPORTED_FILE` (415), `FILE_TOO_LARGE` (413), `REGISTRY_UNAVAILABLE` (200 with `source_unavailable` result inside the payload — uploads never fail because the registry is down), `CERTIFICATE_NOT_ELIGIBLE` (409).

### 0.6 Shared types

```ts
type Severity = "low" | "medium" | "high" | "critical";
type FlagStatus = "open" | "under_review" | "escalated" | "dismissed" | "resolved";
type FlagType =
  | "INVALID_APAAR" | "APAAR_NOT_FOUND" | "APAAR_MISMATCH" | "DUPLICATE_IN_UPLOAD"
  | "EXCESS_INTAKE" | "CROSS_INSTITUTION_DUPLICATE" | "POSSIBLE_DUAL_DEGREE"
  | "IDENTITY_DUPLICATE" | "LATE_ADMISSION" | "STUDENT_CORRECTION";
type ApaarStatus = "provided" | "pending" | "not_applicable";
type Nationality = "indian" | "nri" | "oci" | "fn";
type AdmissionType = "regular" | "lateral" | "tfw" | "fn_pio_oci" | "pmsss" | "other_supernumerary";
type EnrolmentStatus = "admitted" | "cancelled" | "migrated" | "dropped" | "completed";
type ProgramMode = "regular" | "online";
type AcademicYear = string; // "2026-27"
type Suppressible = number | "<5";
```

Timestamps are UTC ISO-8601 with `Z` (`"2026-10-26T11:04:12Z"`). Dates are `YYYY-MM-DD`.

### 0.7 Flag object (returned by every flag-producing endpoint)

```json
{
  "id": 412,
  "type": "EXCESS_INTAKE",
  "severity": "high",
  "status": "open",
  "title": "Admissions exceed approved intake in B.Tech CSE (2026-27)",
  "explanation": "312 enrolled vs 300 approved intake -> 9 valid supernumerary seats (TFW 6/15, lateral 3/30) -> 3 excess admissions.",
  "evidence": { "program_id": 77, "academic_year": "2026-27", "approved_intake": 300, "regular_admitted": 303, "excess": 3 },
  "institution_id": 12,
  "institution_name": "Vindhyashree Institute of Technology",
  "student_id": null,
  "enrolment_id": null,
  "assigned_to": null,
  "notes": [],
  "created_at": "2026-10-26T09:12:00Z"
}
```

Institution-facing flag objects omit `institution_name`/`institution_id` of **other** institutions and carry the sanitised wording from CLAUDE.md §5.10. Every flag always has a non-empty `explanation` and structured `evidence` (CLAUDE.md §8).

---

## 1. Meta (public)

### GET /health
Role: **public**

```json
{ "status": "ok", "service": "api", "version": "0.1.0", "db": "ok", "registry": "ok", "synthetic_data": true }
```

---

## 2. `/auth` — routers/auth.py

### POST /auth/login
Role: **public**

Request:
```json
{ "username": "vit_admin", "password": "<from demo_credentials.csv>" }
```

Response `200`:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 28800,
  "user": {
    "id": 7,
    "username": "vit_admin",
    "display_name": "Vindhyashree Institute — Data Cell",
    "role": "institution",
    "institution_id": 12,
    "student_id": null,
    "must_change_password": false
  }
}
```
Errors: `401 BAD_CREDENTIALS` (same code for an unknown user and a wrong password); `429 TOO_MANY_ATTEMPTS` with `details.retry_after_seconds` after 5 failures per account or 20 per client within 15 minutes (`LOGIN_*` settings). Successes and failures are written to the audit chain (`login`, `login_failed`, `login_throttled`); the password never is.

The JWT carries `ver`, the account's token version. A password change or admin reset bumps it, so every earlier token fails with `401 TOKEN_REVOKED`. After an admin reset `must_change_password` is true and every role route answers `403 PASSWORD_CHANGE_REQUIRED` until the password is changed.

### POST /auth/change-password
Role: any authenticated (including an account that must change its password)

Request: `{ "current_password": "…", "new_password": "…" }` — at least 10 characters, three of lower/upper/digit/symbol, not containing the username, not the current one.

Response `200`: `{ "status": "changed", "access_token": "<new JWT>", "expires_in": 28800 }`

Errors: `400 BAD_CREDENTIALS` (wrong current password; counts toward the throttle), `400 WEAK_PASSWORD` with `details.problems`, `429 TOO_MANY_ATTEMPTS`.

### GET /auth/me
Role: any authenticated

```json
{ "id": 7, "username": "vit_admin", "display_name": "Vindhyashree Institute — Data Cell", "role": "institution", "institution_id": 12, "student_id": null }
```

### GET /auth/demo-users
Role: **public** (demo only; documented as such and disabled when `DEMO_MODE=false`). Returns account names and labels only — **never passwords**, which exist in plain text only in the gitignored `demo_credentials.csv` written at seed time.

```json
{
  "demo_mode": true,
  "users": [
    { "username": "aicte_officer1", "role": "aicte_officer", "label": "AICTE Officer (full powers)" },
    { "username": "aicte_viewer1", "role": "aicte_viewer", "label": "AICTE Analyst (aggregates only)" },
    { "username": "vit_admin", "role": "institution", "label": "Vindhyashree Institute of Technology" },
    { "username": "student_demo1", "role": "student", "label": "Student — APAAR registry mismatch" },
    { "username": "verifier_demo", "role": "verifier", "label": "Employer — Nilgiri Softworks" },
    { "username": "admin", "role": "admin", "label": "Demo operator" }
  ]
}
```

---

## 3. `/institution` — routers/institution.py

All routes: role `institution`. Scope comes from the JWT.

### GET /institution/me
```json
{
  "id": 12,
  "aicte_permanent_id": "1-4432219876",
  "name": "Vindhyashree Institute of Technology",
  "state": "Madhya Pradesh",
  "region": "Central",
  "type": "private_unaided",
  "programs": [
    { "id": 77, "course": "B.Tech", "branch": "Computer Science and Engineering", "level": "UG", "mode": "regular" },
    { "id": 78, "course": "MBA", "branch": "General", "level": "PG", "mode": "online" }
  ]
}
```

### GET /institution/dashboard
Query: `academic_year` (default: current)
```json
{
  "academic_year": "2026-27",
  "students_reported": 1842,
  "open_flags": { "low": 3, "medium": 2, "high": 1, "critical": 0 },
  "latest_quality_score": 87,
  "quality_trend": [ { "upload_id": 31, "created_at": "2026-10-20T06:11:00Z", "quality_score": 72 }, { "upload_id": 44, "created_at": "2026-10-26T09:02:00Z", "quality_score": 87 } ],
  "seat_matrix_summary": { "programs": 5, "approved_intake_total": 1080, "admitted_total": 1102, "excess_total": 3 },
  "last_upload_at": "2026-10-26T09:02:00Z"
}
```

### GET /institution/template
Returns `text/csv` (`Content-Disposition: attachment; filename="apaar_upload_template.csv"`), header row = canonical fields:
`apaar_id,apaar_status,student_name,gender,dob,category,nationality_status,phone,email,guardian_phone,course,branch,program_mode,academic_year,year_of_study,admission_type,admission_date,status`

### POST /institution/uploads
`multipart/form-data`: `file` (.xlsx/.xls/.csv, max 10 MB), optional `academic_year`.

Response `201` — parsed, **not yet validated**, state `pending_mapping`:
```json
{
  "upload_id": 44,
  "filename": "admissions_oct.xlsx",
  "state": "pending_mapping",
  "rows_total": 1842,
  "blank_rows_skipped": 7,
  "detected_sheet": "Sheet1",
  "proposed_mapping": [
    { "source_column": "Stu. Nm", "field": "student_name", "confidence": 0.93, "sample_values": ["Rahul Sharma", "Aisha Khan"] },
    { "source_column": "APAAR No.", "field": "apaar_id", "confidence": 0.97, "sample_values": ["1234-5678-1234"] },
    { "source_column": "D.O.B", "field": "dob", "confidence": 0.91, "sample_values": ["12/03/2006", "2006-07-19"] },
    { "source_column": "Adm Dt", "field": "admission_date", "confidence": 0.78, "sample_values": ["05-08-2026"] },
    { "source_column": "Remarks", "field": null, "confidence": 0.0, "sample_values": ["-"] }
  ],
  "unmapped_required_fields": ["academic_year"],
  "available_fields": ["apaar_id", "apaar_status", "student_name", "gender", "dob", "category", "nationality_status", "phone", "email", "guardian_phone", "course", "branch", "program_mode", "academic_year", "year_of_study", "admission_type", "admission_date", "status"]
}
```

### POST /institution/uploads/{upload_id}/confirm-mapping
Runs validation, stores valid rows, recomputes the seat matrix and detectors.

Request:
```json
{
  "mapping": { "Stu. Nm": "student_name", "APAAR No.": "apaar_id", "D.O.B": "dob", "Adm Dt": "admission_date", "Remarks": null },
  "defaults": { "academic_year": "2026-27", "admission_type": "regular", "program_mode": "regular" }
}
```

Response `200` = the quality report (same shape as `GET /institution/uploads/{id}`):
```json
{
  "upload_id": 44,
  "state": "completed",
  "quality_score": 87,
  "rows_total": 1842,
  "rows_ok": 1803,
  "rows_error": 39,
  "rows_warning": 112,
  "registry_check": { "match": 1740, "mismatch": 9, "not_found": 12, "skipped_not_applicable": 37, "source_unavailable": 5 },
  "flags_created": [ { "id": 412, "type": "EXCESS_INTAKE", "severity": "high" }, { "id": 413, "type": "LATE_ADMISSION", "severity": "medium" } ],
  "issues": [
    { "row": 18, "severity": "error", "field": "apaar_id", "code": "INVALID_APAAR", "value_masked": "XXXX-XXXX-12", "message": "APAAR ID must be exactly 12 digits (found 10).", "fix_suggestion": "Re-check the APAAR ID on the student's APAAR card and re-upload this row." },
    { "row": 204, "severity": "error", "field": "apaar_status", "code": "NOT_APPLICABLE_NOT_ALLOWED", "message": "apaar_status 'not_applicable' is only valid for foreign national / OCI students.", "fix_suggestion": "Set nationality_status to fn or oci, or provide the APAAR ID." },
    { "row": 611, "severity": "warning", "field": "admission_date", "code": "LATE_ADMISSION", "message": "Admission date 2026-11-02 is after the 2026-27 cutoff (2026-09-30).", "fix_suggestion": "Attach approval for the late admission or correct the date." }
  ],
  "errors_csv_url": "/institution/uploads/44/errors.csv",
  "created_at": "2026-10-26T09:02:00Z"
}
```
Note: `issues` is capped at 200 entries in the response; the CSV has all of them.

### GET /institution/uploads
Query: `state` (`pending_mapping|validating|completed|failed`), `academic_year`, `date_from`, `date_to`, pagination (`sort`: `created_at`, `quality_score`, `rows_total`).

```json
{
  "items": [ { "id": 44, "filename": "admissions_oct.xlsx", "state": "completed", "rows_total": 1842, "rows_ok": 1803, "rows_error": 39, "quality_score": 87, "created_at": "2026-10-26T09:02:00Z" } ],
  "page": 1, "page_size": 25, "total": 4, "total_pages": 1, "sort": "-created_at"
}
```

### GET /institution/uploads/{upload_id}
Same object as `confirm-mapping` response, plus `column_mapping`.

### GET /institution/uploads/{upload_id}/errors.csv
`text/csv`: `row,severity,field,code,message,fix_suggestion`.

### GET /institution/seat-matrix
Query: `academic_year` (required), `program_id` (optional)

```json
{
  "academic_year": "2026-27",
  "rule_set": "APH_2026_27_v1",
  "programs": [
    {
      "program_id": 77, "course": "B.Tech", "branch": "Computer Science and Engineering", "mode": "regular",
      "approved_intake": 300,
      "regular_admitted": 303,
      "supernumerary": [
        { "admission_type": "tfw", "admitted": 6, "cap": 15, "cap_basis": "5% of approved intake", "valid": 6, "excess": 0 },
        { "admission_type": "lateral", "admitted": 33, "cap": 30, "cap_basis": "10% of approved intake + vacant year-1 seats", "valid": 30, "excess": 3 },
        { "admission_type": "fn_pio_oci", "admitted": 2, "cap": 45, "cap_basis": "15% of approved intake", "valid": 2, "excess": 0 }
      ],
      "total_admitted": 344,
      "valid_supernumerary": 38,
      "excess": 6,
      "explanation": "303 regular admissions vs 300 approved intake -> 3 excess regular. Supernumerary: TFW 6/15 ok, lateral 33/30 -> 3 excess, FN/PIO/OCI 2/45 ok. Total excess = 6.",
      "flag_id": 412
    }
  ],
  "totals": { "approved_intake": 1080, "regular_admitted": 1046, "valid_supernumerary": 59, "excess": 6 }
}
```

### GET /institution/students
Query: `q` (matches masked name prefix / last 4 of APAAR), `program_id`, `academic_year`, `year_of_study`, `admission_type`, `apaar_status`, `status`, `has_flags` (bool), pagination (`sort`: `created_at`, `name_masked`, `academic_year`).

```json
{
  "items": [
    {
      "student_id": 9931, "apaar_masked": "XXXX-XXXX-1234", "apaar_status": "provided", "name_masked": "R***** S.",
      "gender": "M", "category": "OBC-NCL", "nationality_status": "indian", "dob_year": 2006, "is_minor": false,
      "enrolment": { "id": 20114, "program_id": 77, "course": "B.Tech", "branch": "Computer Science and Engineering", "academic_year": "2026-27", "year_of_study": 1, "admission_type": "regular", "status": "admitted", "admitted_on": "2026-08-05", "version": 1 },
      "flag_count": 1
    }
  ],
  "page": 1, "page_size": 25, "total": 1842, "total_pages": 74, "sort": "name_masked"
}
```

### PATCH /institution/enrolments/{enrolment_id}/status
Versioned status change (own institution only).

Request:
```json
{ "status": "cancelled", "reason": "Admission cancelled on student request; fee refunded.", "effective_date": "2026-09-12" }
```
Response:
```json
{ "enrolment_id": 20114, "status": "cancelled", "version": 2, "previous_status": "admitted", "changed_at": "2026-10-26T11:20:00Z", "audit_log_id": 8812 }
```
`reason` min 10 chars → else `400 REASON_REQUIRED`.

### GET /institution/flags
Query: `type`, `severity`, `status`, `academic_year`, `program_id`, pagination (`sort`: `created_at`, `severity`).

Cross-institution flags are sanitised (CLAUDE.md §5.10 — the other college is never named):
```json
{
  "items": [
    {
      "id": 501, "type": "CROSS_INSTITUTION_DUPLICATE", "severity": "high", "status": "open",
      "title": "Possible duplicate enrolment",
      "explanation": "Possible duplicate enrolment — contact AICTE.",
      "evidence": { "student_id": 9931, "apaar_masked": "XXXX-XXXX-1234", "academic_year": "2026-27", "your_program": "B.Tech CSE (regular)" },
      "student_id": 9931, "enrolment_id": 20114, "created_at": "2026-10-26T09:13:00Z"
    }
  ],
  "page": 1, "page_size": 25, "total": 6, "total_pages": 1, "sort": "-severity"
}
```

### PATCH /institution/flags/{flag_id}
Institutions may only move their own flags to `under_review` or `resolved` (and add a note). Escalate/dismiss is AICTE-only.

Request:
```json
{ "status": "resolved", "note": "Row corrected and re-uploaded in upload #44." }
```
Response: the updated flag object + `"audit_log_id": 8815`.

---

## 4. `/aicte` — routers/aicte.py

Roles: `aicte_viewer` **and** `aicte_officer` unless stated. Viewer responses are aggregated/masked and suppressed (`<5`); only the officer gets flag `evidence` detail, case actions and reveal.

### GET /aicte/overview
Roles: viewer, officer. Query: `academic_year` (default current), `state` (optional)

```json
{
  "academic_year": "2026-27",
  "kpis": {
    "institutions_total": 40,
    "institutions_reporting": 37,
    "institutions_non_reporting": 3,
    "students_reported": 15214,
    "total_excess_seats": 128,
    "open_flags": { "low": 41, "medium": 62, "high": 23, "critical": 4 },
    "avg_data_quality": 84
  },
  "flags_by_type": [ { "type": "EXCESS_INTAKE", "count": 9, "max_severity": "high" }, { "type": "CROSS_INSTITUTION_DUPLICATE", "count": 2, "max_severity": "high" }, { "type": "POSSIBLE_DUAL_DEGREE", "count": 10, "max_severity": "low" } ],
  "by_state": [
    { "state": "Madhya Pradesh", "institutions": 6, "students_reported": 2411, "open_flags": 17, "excess_seats": 31 },
    { "state": "Goa", "institutions": 2, "students_reported": 318, "open_flags": "<5", "excess_seats": 0 }
  ],
  "suppression_applied": true,
  "generated_at": "2026-10-26T11:30:00Z"
}
```
(`suppression_applied: true` only for `aicte_viewer`; cells below 5 become `"<5"`.)

### GET /aicte/institutions
Roles: viewer, officer. Query: `q` (name / AICTE permanent id), `state`, `region`, `type`, `reporting` (`yes|no`), `academic_year`, `has_flag_type`, pagination (`sort`: `open_flags_total` (default, descending), `name`, `students_reported`, `excess_seats`).

```json
{
  "items": [
    { "id": 12, "aicte_permanent_id": "1-4432219876", "name": "Vindhyashree Institute of Technology", "state": "Madhya Pradesh", "region": "Central", "type": "private_unaided", "students_reported": 1842, "open_flags": { "low": 1, "medium": 2, "high": 2, "critical": 0 }, "open_flags_total": 5, "excess_seats": 6, "last_upload_at": "2026-10-26T09:02:00Z" }
  ],
  "page": 1, "page_size": 25, "total": 40, "total_pages": 2, "sort": "-open_flags_total"
}
```

### GET /aicte/institutions/{institution_id}
Roles: viewer, officer. Query: `academic_year`

```json
{
  "institution": { "id": 12, "aicte_permanent_id": "1-4432219876", "name": "Vindhyashree Institute of Technology", "state": "Madhya Pradesh", "region": "Central", "type": "private_unaided" },
  "reporting": { "uploads": 4, "last_upload_at": "2026-10-26T09:02:00Z", "students_reported": 1842, "avg_quality_score": 83 },
  "seat_matrix_summary": { "approved_intake": 1080, "regular_admitted": 1046, "valid_supernumerary": 59, "excess": 6 },
  "flags": [ { "id": 412, "type": "EXCESS_INTAKE", "severity": "high", "status": "open", "title": "Admissions exceed approved intake in B.Tech CSE (2026-27)", "created_at": "2026-10-26T09:12:00Z" } ],
  "upload_timeline": [ { "upload_id": 31, "created_at": "2026-10-20T06:11:00Z", "rows_ok": 980, "quality_score": 72 } ]
}
```

### GET /aicte/institutions/{institution_id}/seat-matrix
Roles: viewer, officer. Query: `academic_year` (required). Same body as `GET /institution/seat-matrix`.

### GET /aicte/flags
Roles: viewer (no `evidence`, masked), officer (full). Query: `type` (repeatable), `severity` (repeatable), `status` (repeatable), `state`, `institution_id`, `academic_year`, `assigned_to`, `cluster_id`, `student_id`, `created_from`, `created_to`, `q` (title/explanation search), pagination (`sort`: `created_at`, `severity`, `institution_name`).

```json
{
  "items": [ { "id": 412, "type": "EXCESS_INTAKE", "severity": "high", "status": "open", "title": "Admissions exceed approved intake in B.Tech CSE (2026-27)", "explanation": "312 enrolled vs 300 approved intake -> 9 valid supernumerary -> 3 excess.", "evidence": { "program_id": 77, "approved_intake": 300, "regular_admitted": 303, "excess": 6 }, "institution_id": 12, "institution_name": "Vindhyashree Institute of Technology", "state": "Madhya Pradesh", "student_id": null, "enrolment_id": null, "cluster_id": null, "assigned_to": null, "notes": [], "created_at": "2026-10-26T09:12:00Z" } ],
  "page": 1, "page_size": 25, "total": 130, "total_pages": 6, "sort": "-severity",
  "facets": { "by_type": { "EXCESS_INTAKE": 9, "CROSS_INSTITUTION_DUPLICATE": 2 }, "by_severity": { "high": 23, "critical": 4 }, "by_status": { "open": 101, "under_review": 22 } }
}
```

### GET /aicte/flags/{flag_id}
Roles: viewer (masked, no evidence internals), officer (full). Full flag object plus:
```json
{
  "id": 501, "type": "CROSS_INSTITUTION_DUPLICATE", "severity": "high", "status": "under_review",
  "title": "Same APAAR ID enrolled full-time at two institutions (2026-27)",
  "explanation": "APAAR XXXX-XXXX-1234 has active full-time regular enrolments at Vindhyashree Institute of Technology (B.Tech CSE, year 1) and Kharapur Technical Institute (B.Tech ECE, year 1) in 2026-27. Neither programme is online/ODL, so this is not a permitted dual degree.",
  "evidence": { "apaar_masked": "XXXX-XXXX-1234", "sides": [ { "institution_id": 12, "institution_name": "Vindhyashree Institute of Technology", "program": "B.Tech CSE", "mode": "regular", "year_of_study": 1, "admitted_on": "2026-08-05" }, { "institution_id": 29, "institution_name": "Kharapur Technical Institute", "program": "B.Tech ECE", "mode": "regular", "year_of_study": 1, "admitted_on": "2026-08-11" } ], "classification_reason": "both_full_time_regular" },
  "related_flags": [ { "id": 502, "type": "CROSS_INSTITUTION_DUPLICATE", "severity": "high" } ],
  "students": [ { "student_id": 9931, "apaar_masked": "XXXX-XXXX-1234", "name_masked": "R***** S.", "is_minor": false } ],
  "notes": [ { "author": "aicte_officer1", "note": "Called institution data cell; awaiting response.", "created_at": "2026-10-26T10:40:00Z" } ],
  "assigned_to": "aicte_officer1",
  "history": [ { "from": "open", "to": "under_review", "actor": "aicte_officer1", "at": "2026-10-26T10:38:00Z", "audit_log_id": 8820 } ]
}
```

### PATCH /aicte/flags/{flag_id}
Role: `aicte_officer`. Case management; every change is audit-logged.

Request (any subset):
```json
{ "status": "escalated", "assigned_to": "aicte_officer2", "note": "Escalating for physical inspection.", "reason": "Two full-time regular enrolments confirmed by both institutions." }
```
Response: the updated flag object + `{ "audit_log_id": 8821 }`.

### POST /aicte/reveal
Role: `aicte_officer` only. `reason` min 10 chars (else `400 REASON_REQUIRED`). Writes to the access log.

Request:
```json
{ "student_id": 9931, "reason": "Verifying duplicate enrolment case #501 with both institutions." }
```
Response:
```json
{
  "student_id": 9931,
  "apaar_id": "123456781234",
  "name": "Rahul Sharma",
  "dob": "2006-03-12",
  "nationality_status": "indian",
  "is_minor": false,
  "enrolments": [ { "id": 20114, "institution_name": "Vindhyashree Institute of Technology", "program": "B.Tech CSE", "mode": "regular", "academic_year": "2026-27", "year_of_study": 1, "admission_type": "regular", "status": "admitted" } ],
  "access_log_id": 4471,
  "revealed_at": "2026-10-26T11:42:00Z",
  "notice": "This access has been logged and is visible to the student."
}
```
Contacts are **never** returned, even on reveal.

### GET /aicte/reports/trends
Roles: viewer (suppressed), officer. Query: `dimension` (`state|branch|category|gender|year`, repeatable), `academic_year` (repeatable, default both seeded years), `state`, `institution_id`
```json
{
  "dimension": "branch",
  "series": [
    { "key": "Computer Science and Engineering", "values": { "2025-26": 4120, "2026-27": 4788 }, "yoy_growth_pct": 16.2 },
    { "key": "Civil Engineering", "values": { "2025-26": 980, "2026-27": 712 }, "yoy_growth_pct": -27.3 }
  ],
  "notes": ["Counts are of active enrolments (status = admitted or completed)."],
  "csv_url": "/aicte/reports/trends.csv?dimension=branch"
}
```

### GET /aicte/reports/trends.csv
Roles: viewer, officer. Same filters; returns `text/csv`.

---

## 5. `/student` — routers/student.py

Role: `student`. `student_id` comes from the JWT only — no student id in any path/query.

### GET /student/me
```json
{
  "student": { "student_id": 9931, "apaar_masked": "XXXX-XXXX-1234", "apaar_status": "provided", "name": "Rahul Sharma", "dob": "2006-03-12", "is_minor": false, "nationality_status": "indian", "category": "OBC-NCL", "gender": "M" },
  "enrolments": [
    { "id": 20114, "institution_name": "Vindhyashree Institute of Technology", "program": "B.Tech — Computer Science and Engineering", "mode": "regular", "academic_year": "2026-27", "year_of_study": 1, "admission_type": "regular", "status": "admitted", "admitted_on": "2026-08-05", "reported_by_upload_at": "2026-10-26T09:02:00Z", "version": 1 },
    { "id": 20115, "institution_name": "Kharapur Technical Institute", "program": "B.Tech — Electronics and Communication", "mode": "regular", "academic_year": "2026-27", "year_of_study": 1, "admission_type": "regular", "status": "admitted", "admitted_on": "2026-08-11", "version": 1 }
  ],
  "open_cases": [ { "flag_id": 502, "type": "STUDENT_CORRECTION", "status": "open", "created_at": "2026-10-26T10:05:00Z" } ],
  "pending_consents": 1
}
```
A student sees their own raw name/DOB/APAAR-masked; `apaar_id` in full is available only on the ID card endpoint.

### POST /student/corrections
Goes to the institution's flag inbox.

Request:
```json
{ "enrolment_id": 20114, "field": "category", "current_value_masked": "OBC-NCL", "correct_value": "EWS", "note": "Category changed after fresh certificate issued in July 2026." }
```
```json
{ "correction_id": 118, "status": "sent_to_institution", "institution_name": "Vindhyashree Institute of Technology", "created_at": "2026-10-26T10:10:00Z", "audit_log_id": 8842 }
```

### GET /student/corrections
Query: `status`, pagination. Items: `{ correction_id, enrolment_id, field, correct_value, status: sent_to_institution|accepted|rejected, response_note, created_at }`.

### GET /student/access-log
"Who accessed my data." Query: `action`, `date_from`, `date_to`, pagination (`sort`: `created_at`).
```json
{
  "items": [
    { "id": 4471, "at": "2026-10-26T11:42:00Z", "actor_role": "aicte_officer", "actor_label": "AICTE Officer", "action": "reveal_student_details", "reason": "Verifying duplicate enrolment case #501 with both institutions.", "target": "student:9931" },
    { "id": 4480, "at": "2026-10-26T11:48:00Z", "actor_role": "aicte_viewer", "actor_label": "AICTE Analyst", "action": "view_flag_detail", "reason": null, "target": "flag:412" }
  ],
  "page": 1, "page_size": 25, "total": 2, "total_pages": 1, "sort": "-created_at"
}
```
Actor identity is shown as a role label, not a username.

### GET /student/consents
Query: `status` (`pending|approved|denied|revoked|expired`), pagination
```json
{
  "items": [
    { "consent_id": 88, "status": "pending", "verifier_name": "Nilgiri Softworks Pvt Ltd", "verifier_type": "employer", "purpose": "employment_verification", "purpose_label": "Employment background verification", "will_share": ["verified yes/no", "programme", "academic year"], "requested_at": "2026-10-26T10:20:00Z", "expires_at": "2026-10-29T10:20:00Z", "parental_consent_required": false }
  ],
  "page": 1, "page_size": 25, "total": 1, "total_pages": 1, "sort": "-requested_at"
}
```

### POST /student/consents/{consent_id}/approve
Request: `{ "validity_minutes": 15 }` (optional; default from config)
```json
{ "consent_id": 88, "status": "approved", "approved_at": "2026-10-26T10:25:00Z", "expires_at": "2026-10-26T10:40:00Z", "shared_fields": ["verified", "program", "academic_year"], "audit_log_id": 8850 }
```

### POST /student/consents/{consent_id}/deny
Request: `{ "reason": "I did not apply to this employer." }` (optional)
```json
{ "consent_id": 88, "status": "denied", "denied_at": "2026-10-26T10:26:00Z", "audit_log_id": 8851 }
```

### POST /student/consents/{consent_id}/revoke
```json
{ "consent_id": 88, "status": "revoked", "revoked_at": "2026-10-26T10:30:00Z", "tokens_invalidated": 1, "audit_log_id": 8852 }
```

### GET /student/id-card
```json
{
  "apaar_masked": "XXXX-XXXX-1234",
  "name": "Rahul Sharma",
  "institution_name": "Vindhyashree Institute of Technology",
  "program": "B.Tech — Computer Science and Engineering",
  "academic_year": "2026-27",
  "year_of_study": 1,
  "status": "admitted",
  "is_minor": false,
  "token": "v1.9931.1761480000.a3f9c2...",
  "token_expires_at": "2026-10-26T12:05:00Z",
  "qr_png_base64": "iVBORw0KGgoAAAANSUhEUgAA...",
  "verify_url": "http://localhost:3000/verify?token=v1.9931.1761480000.a3f9c2..."
}
```

---

## 6. `/verifier` + public token check — routers/verifier.py

### GET /verifier/purposes
Role: `verifier`. Fixed list, used by the request form.
```json
{ "purposes": [ { "value": "employment_verification", "label": "Employment background verification" }, { "value": "higher_education_admission", "label": "Admission to higher education" }, { "value": "scholarship", "label": "Scholarship / fee waiver check" }, { "value": "regulatory_audit", "label": "Regulatory audit" } ] }
```

### POST /verifier/requests
Role: `verifier`. The raw APAAR is hashed on receipt and never stored raw.

Request:
```json
{ "apaar": "123456781234", "purpose": "employment_verification", "note": "Offer stage check for candidate ref #4471" }
```
Response `201`:
```json
{
  "request_id": 455,
  "status": "pending",
  "apaar_masked": "XXXX-XXXX-1234",
  "consent_id": 88,
  "notification": "mock_otp_sent",
  "parental_consent_required": false,
  "requested_at": "2026-10-26T10:20:00Z",
  "expires_at": "2026-10-29T10:20:00Z",
  "message": "The student has been asked for consent. No data is shared until they approve."
}
```
If the APAAR is unknown, the response is identical in shape with `status: "pending"` and resolves to `verified: false` later — we never leak existence of an APAAR before consent. Minors: `parental_consent_required: true` and `message` says "parental consent required".

### GET /verifier/requests/{request_id}
Role: `verifier` (own requests only). Status ∈ `pending | approved | denied | expired | revoked`. Reading an approved result writes to that student's access log.

Pending:
```json
{ "request_id": 455, "status": "pending", "apaar_masked": "XXXX-XXXX-1234", "purpose": "employment_verification", "requested_at": "2026-10-26T10:20:00Z", "result": null }
```
Approved — **minimal response only** (CLAUDE.md §5.11):
```json
{
  "request_id": 455,
  "status": "approved",
  "apaar_masked": "XXXX-XXXX-1234",
  "purpose": "employment_verification",
  "result": { "verified": true, "program": "B.Tech — Computer Science and Engineering", "academic_year": "2026-27" },
  "responded_at": "2026-10-26T10:25:00Z",
  "expires_at": "2026-10-26T10:40:00Z"
}
```
Denied / expired / revoked: `{ "request_id": 455, "status": "denied" | "expired" | "revoked", "result": null }`. No name, no DOB, no institution-side detail, no flags, ever. `revoked` appears when the student withdraws a consent they had already approved: the result is removed and any issued token stops working immediately.

### GET /verifier/requests
Role: `verifier`. Query: `status`, `date_from`, `date_to`, pagination. Items are the summary form of the object above.

### GET /verify/token/{token}
Role: **public** (QR scan page). Validates HMAC signature + expiry + consent not revoked.
```json
{
  "state": "genuine",
  "verified": true,
  "program": "B.Tech — Computer Science and Engineering",
  "academic_year": "2026-27",
  "institution_name": "Vindhyashree Institute of Technology",
  "checked_at": "2026-10-26T12:01:00Z"
}
```
`state` ∈ `genuine | expired | revoked | invalid`. For anything other than `genuine`, only `{ "state": "...", "checked_at": "..." }` is returned. Every check is audit-logged; checks against a student token also write to that student's access log.

---

## 7. `/admin` — routers/admin.py

Role: `admin` only. Demo tooling, no student-data reads.

### POST /admin/reseed
Request: `{ "seed": 42, "institutions": 40, "students": 15000, "years": ["2025-26", "2026-27"] }` (all optional)
```json
{
  "status": "ok",
  "seed": 42,
  "duration_ms": 41290,
  "counts": { "institutions": 40, "programs": 186, "students": 15000, "enrolments": 26104, "uploads": 41, "flags": 134 },
  "ground_truth_path": "datagen/ground_truth.json",
  "detectors_run": true
}
```

### GET /admin/audit/verify
```json
{ "ok": true, "rows_checked": 8861, "first_broken_row": null, "checked_at": "2026-10-26T12:10:00Z" }
```
Broken chain:
```json
{ "ok": false, "rows_checked": 8861, "first_broken_row": { "id": 4412, "expected_hash": "9f2c...", "stored_hash": "11ab...", "action": "flag_status_change", "created_at": "2026-10-24T08:00:00Z" }, "checked_at": "2026-10-26T12:10:00Z" }
```

### POST /admin/audit/tamper-test
Tampers one row in a **copy** of the audit table and shows that the chain check catches it. Never mutates the real log.
```json
{ "copy_rows": 8861, "tampered_row_id": 4412, "detected": true, "first_broken_row_id": 4412, "message": "Tamper detected at row 4412 — the stored hash no longer matches sha256(prev_hash + canonical_json(row))." }
```

### GET /admin/users
Role: admin. Query: `q` (username), `role`, pagination. Student accounts show `display_name: "Student account"` — no name or APAAR.

```json
{ "items": [ { "id": 7, "username": "vit_admin", "role": "institution", "display_name": "Vindhyashree Institute — Data Cell", "institution_id": 12, "is_active": true, "must_change_password": false, "last_login_at": "2026-10-28T09:12:00", "password_changed_at": "2026-10-28T08:00:00" } ], "page": 1, "page_size": 25, "total": 54, "total_pages": 3, "sort": null }
```

### POST /admin/users/{user_id}/reset-password
Role: admin. Issues a one-time temporary password, shown only in this response; sets `must_change_password`, ends all the account's sessions, writes `password_reset` to the audit chain (without the password).

```json
{ "user_id": 7, "username": "vit_admin", "temporary_password": "Kx7m-Q2pf-9Rtz", "must_change_password": true, "audit_log_id": 4512 }
```

---

## 7a. Documents — routers/documents.py

Files are accepted only as PDF, JPEG or PNG **by content** (first bytes), up to `limits.max_file_mb` in `document_checklist.yaml` (5 MB). PDFs carrying `/JavaScript`, `/JS`, `/Launch`, `/EmbeddedFile` or `/RichMedia` are refused (`415 UNSAFE_FILE`). Each file is stored Fernet-encrypted with its plaintext SHA-256; every read re-hashes it and answers `409 DOCUMENT_TAMPERED` (and raises a `DOCUMENT_TAMPERED` flag) on a mismatch. Every read writes the access log (`view_document`).

| Route | Role | Notes |
|---|---|---|
| `GET /institution/documents/rules` | institution | Document types, checklist rules, limits |
| `GET /institution/documents` | institution | One row per enrolled student: `counts` (missing/uploaded/verified/rejected), `status`, `missing`; query `status`, `q`, `academic_year`, pagination; `totals` across all students |
| `GET /institution/students/{student_id}/documents` | institution | The student's checklist: each required `doc_type` with `status` and the current document. 404 for a student not enrolled at this institution |
| `POST /institution/students/{student_id}/documents` | institution | multipart `file` + `doc_type`. `201` with the document summary. Errors: `400 NOT_REQUIRED` / `UNKNOWN_DOCUMENT_TYPE`, `413 FILE_TOO_LARGE`, `415 UNSUPPORTED_FILE` / `UNSAFE_FILE` |
| `POST /institution/documents/bulk` | institution | multipart `file` = ZIP of `<APAAR or student id>_<doc_type>.<ext>` (or `<key>/<doc_type>.<ext>`). Per-file report `stored / rejected / skipped` with reasons. `400 TOO_MANY_FILES`, `413 FILE_TOO_LARGE` (checked from the headers before expanding) |
| `GET /institution/documents/{document_id}/file` | institution (own only) | The file; `X-Content-SHA256` header |
| `POST /aicte/documents/{document_id}/file` | aicte_officer | Body `{ "reason": "≥10 chars" }`; the reason is access-logged and visible to the student |
| `GET /student/documents` | student | Own current documents with status |
| `GET /student/documents/{document_id}/file` | student (own only) | |

Document summary:
```json
{ "id": 91, "doc_type": "class12_marksheet", "original_filename": "marks.pdf", "content_type": "application/pdf", "size_bytes": 18233, "sha256": "9f2c…", "uploaded_at": "2026-10-28T10:02:00", "uploaded_by": "vit_admin", "upload_channel": "single", "verification_status": "needs_review", "issuer_status": "verified", "integrity_ok": true, "reasons": [ { "code": "NAME_MISMATCH", "message": "…", "severity": "warning" } ], "review_decision": null, "review_reason": null }
```

### Verification and officer review (Phase 5)

Every stored document is checked at once: text extraction (PDF text layer, else Tesseract OCR, plus QR via pyzbar), data match against the submitted record (name fuzzy ≥ 90, DOB exact), issuer check (mock Issuer & DigiLocker registry), and tamper checks (upload hash, PDF metadata edited after the issue date). It ends `auto_verified`, `needs_review` or `rejected`, with `reasons[]` (`code`, `message`, `severity` info|warning|error). Codes: `VERIFIED_WITH_ISSUER`, `DATA_MATCHED`, `NOT_AT_ISSUER`, `ISSUER_UNAVAILABLE`, `ISSUER_MISMATCH`, `ISSUER_REVOKED`, `NO_REFERENCE`, `UNREADABLE`, `NAME_MISMATCH`, `NAME_NOT_FOUND`, `DOB_MISMATCH`, `HOLDER_MISMATCH`, `WRONG_DOCUMENT_TYPE`, `EDITED_AFTER_ISSUE`, `STORAGE_TAMPERED`. The name and DOB read from a document are stored vault-encrypted.

| Route | Role | Notes |
|---|---|---|
| `GET /aicte/documents/review` | aicte_officer | Masked queue. Query `status` (`needs_review` default, `rejected`, `auto_verified`, `verified`, `pending`, `all`), `institution_id`, `doc_type`, pagination; `counts` per status |
| `POST /aicte/documents/{id}/case` | aicte_officer | Body `{ "reason" }` (≥ 10 chars, access-logged as `view_document_case`). Returns submitted vs read values field by field, extracted facts, the issuer's answer, tamper checks and any decision |
| `POST /aicte/documents/{id}/decision` | aicte_officer | Body `{ "decision": "approve" | "reject", "reason" }`. Writes `document_review_decision` to the audit chain. `409 CANNOT_DECIDE` when approving a document that failed its integrity check |
| `POST /aicte/documents/{id}/recheck` | aicte_officer | Runs every check again (e.g. after the issuer was unavailable) |

---

## 8b. Mock Issuer & DigiLocker registry (port 8002) — `/issuer`

API-key auth (`X-API-Key` = `ISSUER_API_KEY`). Production-shaped: replacing it with real issuer / DigiLocker APIs means replacing `api/app/services/issuer_client.py`.

`POST /documents/verify` — `{ "reference_no", "doc_type", "sha256", "holder_name", "holder_dob", "facts": { "roll_no", "year", "marks_obtained", "marks_total" } }` →
```json
{ "reference_no": "SSE-2026-123456", "status": "verified", "matched_by": "hash", "issuer_name": "Kaveri Senior Secondary Board", "doc_type": "class12_marksheet", "issued_on": "2026-06-10", "doc_type_match": true, "holder_name_match": true, "holder_dob_match": true, "differing_facts": [], "checked_at": "2026-10-28T10:00:00Z", "source": "mock_issuer_registry_v1" }
```
`status`: `verified` (identical file by SHA-256, or every compared fact matches — a re-scan), `mismatch` (reference exists, contents differ; `differing_facts` names them), `not_found`, `revoked`. When the service does not answer the API records `unavailable` and sends the document to an officer.

`GET /documents/{reference_no}` — what a QR scan resolves to: issuer, type, issue date, status. No holder data.

---

## 8. Mock APAAR registry (port 8001) — `/registry`

Production-shaped stand-in for the real APAAR/ABC API. Auth: `X-API-Key: <REGISTRY_API_KEY>` on every route except `/health`. Artificial 20–50 ms latency.

### GET /health
Role: **public** → `{ "status": "ok", "service": "registry", "issued_count": 15214 }`

### POST /verify
Request:
```json
{ "apaar": "123456781234", "name": "Rahul Sharma", "dob": "2006-03-12", "consent_token": null }
```
Response:
```json
{ "apaar_masked": "XXXX-XXXX-1234", "status": "match", "name_similarity": 100, "dob_match": true, "checked_at": "2026-10-26T09:01:58Z", "source": "mock_apaar_registry_v1" }
```
`status` ∈ `match | mismatch | not_found | consent_required`. Name match uses rapidfuzz ≥ 90; DOB must be exact.

### POST /verify/batch
Max 500 records per call.
```json
{ "records": [ { "ref": "row-18", "apaar": "123456781234", "name": "Rahul Sharma", "dob": "2006-03-12" } ] }
```
```json
{ "checked_at": "2026-10-26T09:02:00Z", "results": [ { "ref": "row-18", "apaar_masked": "XXXX-XXXX-1234", "status": "match", "name_similarity": 100, "dob_match": true } ], "count": 1 }
```

### POST /registry/apaar/bulk
Seeding hook used by `/datagen` (API key required; registry-local only).
```json
{ "records": [ { "apaar": "123456781234", "name": "Rahul Sharma", "dob": "2006-03-12" } ] }
```
→ `{ "inserted": 1, "skipped_existing": 0, "issued_count": 15215 }`

### Client-side contract (main API → registry)

`app/services/registry_client.py` returns a typed result; if the registry is down or times out (default 3 s, 1 retry), the result is:
```json
{ "status": "source_unavailable", "message": "APAAR registry did not respond; rows stored and marked for re-check.", "checked_at": "2026-10-26T09:02:00Z" }
```
Uploads must never fail because of this. Rows are stored with `registry_status: "source_unavailable"` and no `APAAR_NOT_FOUND`/`APAAR_MISMATCH` flag is raised for them.

---

## 9. Route → role matrix (quick reference)

| Route | institution | aicte_viewer | aicte_officer | student | verifier | admin |
|---|---|---|---|---|---|---|
| `POST /auth/login`, `GET /auth/demo-users`, `GET /health`, `GET /verify/token/{t}`, `GET /verify/document/{t}` | public | public | public | public | public | public |
| `GET /auth/me`, `POST /auth/change-password` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `GET /auth/me` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/institution/*` | ✓ (own only) | — | — | — | — | — |
| `/aicte/overview`, `/institutions*`, `/reports/*` | — | ✓ (masked + `<5`) | ✓ | — | — | — |
| `GET /aicte/flags`, `GET /aicte/flags/{id}` | — | ✓ (masked fields only: type, severity, institution, state, status, counts — no `evidence`/`notes`/`history`) | ✓ (full) | — | — | — |
| `PATCH /aicte/flags/{id}`, `POST /aicte/reveal` | — | — | ✓ | — | — | — |
| `/student/*` | — | — | — | ✓ (own only) | — | — |
| `/verifier/*` | — | — | — | — | ✓ (own only) | — |
| `/admin/*` | — | — | — | — | — | ✓ |

---

## 10. Decisions & assumptions baked into this contract

All ten Step-0 questions are now decided — see the decision table in `docs/PLAN.md`. Notably: the admission window and reporting deadline live in `api/app/rules/reporting_calendar.yaml` (keyed by academic year), separate from `intake_rules.yaml`; there are 8 demo student accounts, not one per student.

1. `GET /auth/demo-users` is public but gated by `DEMO_MODE=true`, so the role switcher works without a chicken-and-egg login.
2. Hashes (`apaar_hash`, `phone_hash`, …) are never returned over the API, only masked values — returning a hash would allow offline guessing of a 12-digit space.
3. `admin` cannot read student data; it only reseeds and verifies the audit chain.
4. **Decided:** `aicte_viewer` lists flags with masked fields only (type, severity, institution, state, status, counts; suppression applies) and gets no `evidence`/`notes`/`history`, no reveal and no case actions. `aicte_officer` sees full detail.
5. Enrolment status changes are versioned by writing a new version row; the API returns the current version plus `version` number.
6. Consent validity (how long an approval stays usable) defaults to 72 h for the request and 15 min for an issued token, both config-driven.
7. Trends counts include `admitted` and `completed` enrolments; `cancelled|migrated|dropped` are excluded.

## 11. Changelog

| Date | Change | Who |
|---|---|---|
| 2026-10-26 | Initial frozen contract (Step 0) | Claude Code |
| 2026-10-26 | Step-0 decisions applied: viewer flag fields narrowed, role matrix split for flag list/detail, `reporting_calendar.yaml` noted, `inspection-shortlist.csv` documented | Claude Code |
| 2026-10-26 | Step 13: verifier request status gains `revoked` (a student withdrawing an approved consent is not the same as denying it); `GET /aicte/reports/trends` gains `new_admissions_only`; `GET /aicte/non-reporting` rows gain `days_to_deadline` and `reporting_deadline`; `GET /institution/compliance-certificate` gains `format=json` for an eligibility check without issuing | Claude Code |
| 2026-10-28 | Refocus: removed `/aicte/risk`, `/aicte/inspection-shortlist(.csv)`, `/aicte/non-reporting`, `/aicte/remind/{id}`, `/aicte/graph/*`, `/institution/compliance-certificate`, `/student/enrolments/{id}/confirm` and `/dispute`, `/admin/scenarios`, `/admin/load-scenario/{name}`, `/admin/run-detectors`. Flag types `GHOST_CLUSTER`, `SEQUENTIAL_APAAR`, `LAST_MINUTE_BULK`, `PHANTOM_PROGRESSION`, `STUDENT_DISPUTE`, `STATISTICAL_ANOMALY` and the flag `cluster_id` field removed; student corrections now raise `STUDENT_CORRECTION`. Institution rows lose `risk_score`/`risk_band` and gain `open_flags_total` | Claude Code |
| 2026-10-28 | Security: per-account random passwords (no `password` in `/auth/demo-users`), login throttling (`429 TOO_MANY_ATTEMPTS`), `POST /auth/change-password`, token versioning (`401 TOKEN_REVOKED`), `GET /admin/users`, `POST /admin/users/{id}/reset-password`, `403 PASSWORD_CHANGE_REQUIRED`; `user.must_change_password` added | Claude Code |
| 2026-10-28 | Documents (section 7a): checklist, single and ZIP upload, encrypted storage with SHA-256, downloads for the owning institution, officers (with a reason) and the student; `DOCUMENT_TAMPERED` flag type | Claude Code |
| 2026-10-28 | Document verification and officer review (`/aicte/documents/review`, `/case`, `/decision`, `/recheck`); mock Issuer & DigiLocker registry on port 8002 (section 8b) | Claude Code |
