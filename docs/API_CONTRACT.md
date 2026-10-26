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
  | "IDENTITY_DUPLICATE" | "GHOST_CLUSTER" | "SEQUENTIAL_APAAR" | "LATE_ADMISSION"
  | "LAST_MINUTE_BULK" | "PHANTOM_PROGRESSION" | "STUDENT_DISPUTE" | "STATISTICAL_ANOMALY";
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
  "cluster_id": null,
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
{ "username": "vit_admin", "password": "demo1234" }
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
    "student_id": null
  }
}
```
Errors: `401 BAD_CREDENTIALS`.

### GET /auth/me
Role: any authenticated

```json
{ "id": 7, "username": "vit_admin", "display_name": "Vindhyashree Institute — Data Cell", "role": "institution", "institution_id": 12, "student_id": null }
```

### GET /auth/demo-users
Role: **public** (demo only; documented as such and disabled when `DEMO_MODE=false`)

```json
{
  "demo_mode": true,
  "users": [
    { "username": "aicte_officer1", "password": "demo1234", "role": "aicte_officer", "label": "AICTE Officer (full powers)" },
    { "username": "aicte_viewer1", "password": "demo1234", "role": "aicte_viewer", "label": "AICTE Analyst (aggregates only)" },
    { "username": "vit_admin", "password": "demo1234", "role": "institution", "label": "Vindhyashree Institute of Technology" },
    { "username": "student_demo1", "password": "demo1234", "role": "student", "label": "Student — disputed enrolment" },
    { "username": "verifier_demo", "password": "demo1234", "role": "verifier", "label": "Employer — Nilgiri Softworks" },
    { "username": "admin", "password": "demo1234", "role": "admin", "label": "Demo operator" }
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
  "compliance_certificate_eligible": false,
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
      "flag_count": 1,
      "student_confirmation": "unconfirmed"
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
      "student_id": 9931, "enrolment_id": 20114, "cluster_id": null, "created_at": "2026-10-26T09:13:00Z"
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

### GET /institution/compliance-certificate
Query: `academic_year` (required), `format` (`html` default, `pdf` if available)

Eligible → the certificate document (`text/html` or `application/pdf`), containing institution name, academic year, students reported, "no open high/critical flags as of <timestamp>", a verification token and QR.
Not eligible → `409`:
```json
{ "error": { "code": "CERTIFICATE_NOT_ELIGIBLE", "message": "2 open high/critical flags must be resolved first.", "details": { "blocking_flags": [ { "id": 412, "type": "EXCESS_INTAKE", "severity": "high" }, { "id": 501, "type": "CROSS_INSTITUTION_DUPLICATE", "severity": "high" } ] } } }
```

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
  "flags_by_type": [ { "type": "EXCESS_INTAKE", "count": 9, "max_severity": "high" }, { "type": "GHOST_CLUSTER", "count": 2, "max_severity": "critical" }, { "type": "POSSIBLE_DUAL_DEGREE", "count": 10, "max_severity": "low" } ],
  "by_state": [
    { "state": "Madhya Pradesh", "institutions": 6, "students_reported": 2411, "open_flags": 17, "excess_seats": 31, "avg_risk": 42 },
    { "state": "Goa", "institutions": 2, "students_reported": 318, "open_flags": "<5", "excess_seats": 0, "avg_risk": 11 }
  ],
  "suppression_applied": true,
  "generated_at": "2026-10-26T11:30:00Z"
}
```
(`suppression_applied: true` only for `aicte_viewer`; cells below 5 become `"<5"`.)

### GET /aicte/institutions
Roles: viewer, officer. Query: `q` (name / AICTE permanent id), `state`, `region`, `type`, `risk_min`, `risk_max`, `reporting` (`yes|no`), `academic_year`, `has_flag_type`, pagination (`sort`: `risk_score`, `name`, `students_reported`, `excess_seats`).

```json
{
  "items": [
    { "id": 12, "aicte_permanent_id": "1-4432219876", "name": "Vindhyashree Institute of Technology", "state": "Madhya Pradesh", "region": "Central", "type": "private_unaided", "students_reported": 1842, "risk_score": 78, "open_flags": { "low": 1, "medium": 2, "high": 2, "critical": 0 }, "excess_seats": 6, "last_upload_at": "2026-10-26T09:02:00Z" }
  ],
  "page": 1, "page_size": 25, "total": 40, "total_pages": 2, "sort": "-risk_score"
}
```

### GET /aicte/institutions/{institution_id}
Roles: viewer, officer. Query: `academic_year`

```json
{
  "institution": { "id": 12, "aicte_permanent_id": "1-4432219876", "name": "Vindhyashree Institute of Technology", "state": "Madhya Pradesh", "region": "Central", "type": "private_unaided" },
  "risk": { "score": 78, "band": "high", "reasons": [ "6 excess admissions beyond approved intake and valid supernumerary seats (B.Tech CSE, 2026-27)", "One cluster of 31 students shares only 3 guardian contacts", "19% of records were created in the 6 hours before the reporting deadline (state median 3%)" ] },
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
  "facets": { "by_type": { "EXCESS_INTAKE": 9, "GHOST_CLUSTER": 2 }, "by_severity": { "high": 23, "critical": 4 }, "by_status": { "open": 101, "under_review": 22 } }
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
  "related_flags": [ { "id": 502, "type": "STUDENT_DISPUTE", "severity": "critical" } ],
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

### GET /aicte/risk
Roles: viewer, officer. Query: `state`, `academic_year`, `band` (`low|medium|high|critical`), pagination (`sort`: `risk_score`).
```json
{
  "items": [ { "institution_id": 12, "name": "Vindhyashree Institute of Technology", "state": "Madhya Pradesh", "risk_score": 78, "band": "high", "top_reasons": ["6 excess admissions...", "Ghost cluster of 31 students...", "19% of records created in the last 6 hours..."], "components": { "flags": 54, "anomaly": 24 } } ],
  "page": 1, "page_size": 25, "total": 40, "total_pages": 2, "sort": "-risk_score"
}
```

### GET /aicte/inspection-shortlist
Roles: viewer, officer. Query: `limit` (default 10, max 50), `state`
```json
{
  "generated_at": "2026-10-26T11:45:00Z",
  "academic_year": "2026-27",
  "items": [ { "rank": 1, "institution_id": 12, "name": "Vindhyashree Institute of Technology", "state": "Madhya Pradesh", "risk_score": 78, "reasons": ["6 excess admissions beyond intake", "Ghost cluster: 31 students, 3 guardian contacts", "Statistical anomaly: category mix 4.1σ from state median"], "suggested_checks": ["Physical headcount in B.Tech CSE year 1", "Verify guardian contacts for cluster #7"] } ],
  "csv_url": "/aicte/inspection-shortlist.csv"
}
```

### GET /aicte/inspection-shortlist.csv
Roles: viewer, officer. Same filters as above; returns `text/csv` (`rank,institution_id,name,state,risk_score,reasons`).

### GET /aicte/non-reporting
Roles: viewer, officer. Query: `academic_year`, `state`, pagination
```json
{
  "items": [ { "institution_id": 33, "name": "Tamravati College of Engineering", "state": "Kerala", "last_upload_at": null, "days_overdue": 26, "reminders_sent": 1, "last_reminder_at": "2026-10-20T07:00:00Z" } ],
  "page": 1, "page_size": 25, "total": 3, "total_pages": 1, "sort": "-days_overdue"
}
```

### POST /aicte/remind/{institution_id}
Role: `aicte_officer`. Mocked notification, audit-logged.
```json
{ "institution_id": 33, "channel": "email", "status": "queued_mock", "message": "Student data for 2026-27 is overdue by 26 days.", "sent_at": "2026-10-26T11:50:00Z", "audit_log_id": 8830 }
```

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

### GET /aicte/graph/clusters
Roles: viewer (masked summary), officer. Query: `min_score`, `state`, `institution_id`, `severity`, `status`, pagination (`sort`: `score`, `student_count`)
```json
{
  "items": [
    { "cluster_id": 7, "score": 91, "severity": "critical", "status": "open", "flag_id": 640, "student_count": 31, "shared_attributes": { "guardian_phone": 3, "phone": 1, "email": 0 }, "institutions": [ { "id": 12, "name": "Vindhyashree Institute of Technology", "students": 31 } ], "summary": "31 students share only 3 guardian contact numbers — typical families share one contact across 1–3 students.", "created_at": "2026-10-26T09:14:00Z" }
  ],
  "page": 1, "page_size": 25, "total": 2, "total_pages": 1, "sort": "-score"
}
```

### GET /aicte/graph/clusters/{cluster_id}
Roles: viewer (masked), officer. Cytoscape-ready; writes to the access log. Attribute nodes are labelled, never hashed values.
```json
{
  "cluster_id": 7,
  "score": 91,
  "severity": "critical",
  "summary": "31 students at Vindhyashree Institute of Technology share only 3 guardian contacts — typical families share 1 contact per 1–3 students.",
  "metrics": { "student_count": 31, "attribute_count": 4, "attributes_per_student": 0.13, "institutions_involved": 1, "max_students_per_contact": 14 },
  "legend": { "student": "Student (colour = institution)", "guardian_phone": "Shared guardian contact", "phone": "Shared student contact", "email": "Shared email" },
  "nodes": [
    { "data": { "id": "s9931", "label": "R***** S.", "type": "student", "institution": "Vindhyashree Institute of Technology", "institution_id": 12, "apaar_masked": "XXXX-XXXX-1234", "program": "B.Tech CSE", "academic_year": "2026-27", "student_id": 9931 } },
    { "data": { "id": "g1", "label": "Guardian contact #1", "type": "guardian_phone", "degree": 14 } }
  ],
  "edges": [ { "data": { "source": "s9931", "target": "g1", "attribute_type": "guardian_phone", "label": "guardian contact" } } ],
  "access_log_id": 4480
}
```

### GET /aicte/graph/clusters/{cluster_id}/normal-comparison
Roles: viewer, officer. A healthy sibling cluster in the same state, same shape as above, for the side-by-side toggle (Step 17.3).

---

## 5. `/student` — routers/student.py

Role: `student`. `student_id` comes from the JWT only — no student id in any path/query.

### GET /student/me
```json
{
  "student": { "student_id": 9931, "apaar_masked": "XXXX-XXXX-1234", "apaar_status": "provided", "name": "Rahul Sharma", "dob": "2006-03-12", "is_minor": false, "nationality_status": "indian", "category": "OBC-NCL", "gender": "M" },
  "enrolments": [
    { "id": 20114, "institution_name": "Vindhyashree Institute of Technology", "program": "B.Tech — Computer Science and Engineering", "mode": "regular", "academic_year": "2026-27", "year_of_study": 1, "admission_type": "regular", "status": "admitted", "admitted_on": "2026-08-05", "reported_by_upload_at": "2026-10-26T09:02:00Z", "confirmation": "unconfirmed", "version": 1 },
    { "id": 20115, "institution_name": "Kharapur Technical Institute", "program": "B.Tech — Electronics and Communication", "mode": "regular", "academic_year": "2026-27", "year_of_study": 1, "admission_type": "regular", "status": "admitted", "admitted_on": "2026-08-11", "confirmation": "unconfirmed", "version": 1 }
  ],
  "open_cases": [ { "flag_id": 502, "type": "STUDENT_DISPUTE", "status": "under_review", "created_at": "2026-10-26T10:05:00Z" } ],
  "pending_consents": 1
}
```
A student sees their own raw name/DOB/APAAR-masked; `apaar_id` in full is available only on the ID card endpoint.

### POST /student/enrolments/{enrolment_id}/confirm
Request: `{}` (optional `{ "note": "Yes, this is my college." }`)
```json
{ "enrolment_id": 20114, "confirmation": "confirmed", "confirmed_at": "2026-10-26T10:02:00Z", "audit_log_id": 8840 }
```

### POST /student/enrolments/{enrolment_id}/dispute
Creates a `STUDENT_DISPUTE` flag (severity `critical`) visible to AICTE and that institution.

Request:
```json
{ "reason": "I never applied to or joined this institution.", "category": "not_my_enrolment" }
```
`category` ∈ `not_my_enrolment | wrong_program | wrong_year | already_cancelled | other`; `reason` min 10 chars.
```json
{
  "enrolment_id": 20115,
  "confirmation": "disputed",
  "flag": { "id": 502, "type": "STUDENT_DISPUTE", "severity": "critical", "status": "open", "title": "Student disputes reported enrolment", "explanation": "The student states they never enrolled in B.Tech ECE at Kharapur Technical Institute for 2026-27. Reported by the institution in upload #52." },
  "message": "AICTE has been notified. You can track this case here.",
  "audit_log_id": 8841
}
```

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
    { "id": 4480, "at": "2026-10-26T11:48:00Z", "actor_role": "aicte_viewer", "actor_label": "AICTE Analyst", "action": "view_cluster", "reason": null, "target": "cluster:7" }
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
Role: `verifier` (own requests only).

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
Denied / expired: `{ "request_id": 455, "status": "denied" | "expired", "result": null }`. No name, no DOB, no institution-side detail, no flags, ever.

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

### GET /admin/scenarios
```json
{ "scenarios": [ { "name": "A_excess_intake", "label": "Excess admissions beyond intake", "flag_types": ["EXCESS_INTAKE"] }, { "name": "B_ghost_cluster", "label": "Ghost student cluster", "flag_types": ["GHOST_CLUSTER"] }, { "name": "C_cross_institution_duplicate", "label": "Same APAAR, two full-time colleges", "flag_types": ["CROSS_INSTITUTION_DUPLICATE"] }, { "name": "D_dual_degree", "label": "Legitimate dual degree (must NOT be fraud)", "flag_types": ["POSSIBLE_DUAL_DEGREE"] } ] }
```

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

### POST /admin/load-scenario/{name}
```json
{ "scenario": "B_ghost_cluster", "status": "injected", "institution_id": 12, "students_added": 31, "flags_created": [ { "id": 641, "type": "GHOST_CLUSTER", "severity": "critical" } ], "ground_truth_updated": true }
```

### POST /admin/run-detectors
Idempotent re-run of `run_all_detectors()`.
```json
{ "status": "ok", "duration_ms": 6120, "flags_created": 4, "flags_updated": 11, "flags_unchanged": 119 }
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
| `POST /auth/login`, `GET /auth/demo-users`, `GET /health`, `GET /verify/token/{t}` | public | public | public | public | public | public |
| `GET /auth/me` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/institution/*` | ✓ (own only) | — | — | — | — | — |
| `/aicte/overview`, `/institutions*`, `/risk`, `/inspection-shortlist`, `/non-reporting`, `/reports/*`, `/graph/*` | — | ✓ (masked + `<5`) | ✓ | — | — | — |
| `GET /aicte/flags`, `GET /aicte/flags/{id}` | — | ✓ (masked fields only: type, severity, institution, state, status, counts — no `evidence`/`notes`/`history`) | ✓ (full) | — | — | — |
| `PATCH /aicte/flags/{id}`, `POST /aicte/reveal`, `POST /aicte/remind/{id}` | — | — | ✓ | — | — | — |
| `/student/*` | — | — | — | ✓ (own only) | — | — |
| `/verifier/*` | — | — | — | — | ✓ (own only) | — |
| `/admin/*` | — | — | — | — | — | ✓ |

---

## 10. Decisions & assumptions baked into this contract

All ten Step-0 questions are now decided — see the decision table in `docs/PLAN.md`. Notably: the admission window and reporting deadline live in `api/app/rules/reporting_calendar.yaml` (keyed by academic year), separate from `intake_rules.yaml`; there are 8 demo student accounts, not one per student.

1. `GET /auth/demo-users` is public but gated by `DEMO_MODE=true`, so the role switcher works without a chicken-and-egg login.
2. Hashes (`apaar_hash`, `phone_hash`, …) are never returned over the API, only masked values — returning a hash would allow offline guessing of a 12-digit space.
3. `admin` cannot read student data; it only reseeds, loads scenarios and verifies the audit chain.
4. **Decided:** `aicte_viewer` lists flags with masked fields only (type, severity, institution, state, status, counts; suppression applies) and gets no `evidence`/`notes`/`history`, no reveal and no case actions. `aicte_officer` sees full detail.
5. Enrolment status changes are versioned by writing a new version row; the API returns the current version plus `version` number.
6. Consent validity (how long an approval stays usable) defaults to 72 h for the request and 15 min for an issued token, both config-driven.
7. The compliance certificate is HTML by default (printable) — `format=pdf` only if we add a renderer without a new heavy dependency.
8. Trends counts include `admitted` and `completed` enrolments; `cancelled|migrated|dropped` are excluded.

## 11. Changelog

| Date | Change | Who |
|---|---|---|
| 2026-10-26 | Initial frozen contract (Step 0) | Claude Code |
| 2026-10-26 | Step-0 decisions applied: viewer flag fields narrowed, role matrix split for flag list/detail, `reporting_calendar.yaml` noted, `inspection-shortlist.csv` documented | Claude Code |
