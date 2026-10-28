# CLAUDE.md — APAAR Student Data & Verification Platform (SIH26263)

This file gives you (Claude Code) the full context for this repository. Read it before every task.

## 1. What we are building

A working prototype for **Smart India Hackathon 2026, problem statement SIH26263 (AICTE)**:
"Development of an APAAR ID-Based Student Data Management and Verification Platform for AICTE-Approved Institutions."

Today AICTE mostly receives *counts* of enrolled students, not student-level records. This platform:
- lets AICTE-approved institutions upload student-level data keyed on **APAAR ID** (the national 12-digit academic ID),
- automatically validates it and detects fraud (excess admissions, ghost students, duplicate enrolment across institutions),
- gives AICTE an explainable, risk-ranked national view,
- lets students see and dispute what was reported about them,
- lets employers/regulators verify a student **only with the student's consent**.

It is a hackathon prototype: it must run reliably on one laptop, be demoable in 5 minutes, and look polished.
**All data is synthetic.** There is no real APAAR API; we use a mock registry service with a production-shaped API.

## 2. Users and roles

| Role | Who | Can do |
|---|---|---|
| `institution` | College admin | Upload data, see ONLY their own institution's students, flags, seat matrix |
| `aicte_viewer` | AICTE analyst | Aggregates and masked rows only |
| `aicte_officer` | AICTE officer | Flag details, reveal full student details after entering a reason, manage cases |
| `student` | Student | See own records, confirm/dispute enrolment, see who accessed their data, manage consent |
| `verifier` | Employer / regulator | Request verification; receives minimal response only after student consent |
| `admin` | Demo operator | Reseed database, load demo scenarios, verify audit chain |

## 3. Tech stack (do not change without asking)

- **Backend:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0, SQLite by default (`DATABASE_URL` env var allows Postgres later)
- **Data:** pandas, openpyxl, rapidfuzz, PyYAML, Faker (`en_IN` locale)
- **Security:** PyJWT, passlib[bcrypt], `cryptography` (Fernet) for the encrypted vault, `hmac` + `hashlib` (HMAC-SHA256)
- **Other:** qrcode, pytest, httpx (tests)
- **Mock APAAR registry:** separate small FastAPI app
- **Frontend:** Next.js (App Router) + TypeScript, Tailwind CSS, shadcn/ui, TanStack Query, Recharts
- **Ports:** API `8000`, registry `8001`, web `3000`

## 4. Repository layout

```
/api            FastAPI backend (main app)
  /app
    /core       config, db, security (JWT, RBAC), crypto (HMAC, vault), audit
    /models     SQLAlchemy models
    /schemas    Pydantic schemas
    /routers    institution.py, aicte.py, student.py, verifier.py, admin.py, auth.py
    /services   upload.py, validation.py, intake.py, duplicates.py, heuristics.py,
                detectors.py, flags.py, cases.py, consent.py, tokens.py
    /rules      intake_rules.yaml
  /tests
/registry       Mock APAAR registry (FastAPI)
/datagen        Synthetic data generator + ground_truth.json + evaluate.py
/web            Next.js frontend
/samples        Messy sample Excel/CSV files for demo uploads
Makefile        make setup | make seed | make dev | make test | make reset
.env.example
README.md
```

## 5. NON-NEGOTIABLE privacy & security rules

These are part of the product, not optional extras. Never violate them, even to save time.

1. **Never store raw phone numbers, emails or guardian phone numbers.** Store only `HMAC-SHA256(HMAC_KEY, normalized_value)`. Matching is done on hashes.
2. **Raw APAAR ID, full name and DOB live only in an encrypted `vault` table** (Fernet, key from env). Main tables use `apaar_hash = HMAC-SHA256(HMAC_KEY, apaar)`.
   Use HMAC, never plain `sha256(secret + value)` — APAAR is only 12 digits and is brute-forceable.
3. **Keys come from environment variables** (`HMAC_KEY`, `VAULT_KEY`, `JWT_SECRET`). Provide `.env.example`; never commit `.env`.
4. **RBAC on every route** via a single `require_role(...)` dependency. No route without it (except login and health).
5. **Tenant isolation:** for `institution` users, `institution_id` comes ONLY from the JWT, never from request params. A college can never fetch another college's rows.
6. **Masking by default:** APAAR shown as `XXXX-XXXX-1234`, names as `R***** S.` Full details are only returned via the reveal endpoint, for `aicte_officer`, with a mandatory reason.
7. **Access log:** every detail view / reveal writes `(actor, role, action, target, reason, timestamp)`.
8. **Audit log is hash-chained:** each row stores `prev_hash` and `hash = sha256(prev_hash + canonical_json(row))`.
9. **Small-count suppression:** for `aicte_viewer`, any count below 5 in a breakdown is returned as `"<5"`.
10. **Cross-institution duplicate alerts shown to a college must NOT name the other college.** Text: "Possible duplicate enrolment — contact AICTE."
11. **Verifier responses are minimal:** `verified: true/false`, program, year. Nothing else.
12. **Minors:** students under 18 have `is_minor = true`; verification for them is marked "parental consent required".
13. **Fictional data only.** Institution names must be clearly invented. Never use real college names, especially in fraud scenarios. The UI shows a banner: "Prototype — all data is synthetic."

## 6. Domain rules (get these right — this is our edge)

- **APAAR ID:** 12 digits. Validation = format check + mock registry lookup (match / mismatch / not_found).
- **Students without APAAR:** foreign nationals (FN), some OCI/NRI students may not have one. Field `apaar_status` ∈ `provided | pending | not_applicable`. `not_applicable` is valid ONLY for FN/OCI and is not an error.
- **Approved intake vs supernumerary seats:** supernumerary seats (e.g. Tuition Fee Waiver, lateral entry, foreign national / PIO / OCI quotas, PMSSS etc.) are OUTSIDE approved intake, up to configured caps. Excess = regular admissions beyond intake + supernumerary admissions beyond their caps. All caps live in `api/app/rules/intake_rules.yaml` and are marked `# VERIFY against AICTE Approval Process Handbook 2026-27`. Never hardcode them.
- **Lateral entry:** joins in year 2; must not be counted against year-1 intake.
- **Dual degree is legal:** the same APAAR at two institutions is "possible dual degree" (not fraud) when at least one enrolment is online/ODL mode. Two full-time regular enrolments in the same year = "likely fraud".
- **Student status lifecycle:** `admitted | cancelled | migrated | dropped | completed`, with versioned history.
- **Academic year format:** `2026-27`. Admission cutoff date is configurable per year.

## 7. Data model (core tables)

- `institutions` (id, aicte_permanent_id, name, state, region, type)
- `programs` (id, institution_id, course, branch, level, mode: regular|online)
- `approved_intake` (program_id, academic_year, intake, supernumerary caps JSON)
- `students` (id, apaar_hash, apaar_masked, apaar_status, name_masked, gender, category, nationality_status: indian|nri|oci|fn, dob_year, is_minor, phone_hash, email_hash, guardian_phone_hash)
- `vault` (student_id, apaar_enc, name_enc, dob_enc)
- `enrolments` (id, student_id, program_id, academic_year, year_of_study, admission_type: regular|lateral|tfw|fn_pio_oci|pmsss|other_supernumerary, status, admitted_on, created_at, upload_id, version)
- `uploads` (id, institution_id, filename, rows_total, rows_ok, rows_error, quality_score, column_mapping JSON, created_at)
- `flags` (id, type, severity, institution_id, student_id nullable, enrolment_id nullable, title, explanation, evidence JSON, status: open|under_review|escalated|dismissed|resolved, assigned_to, notes JSON, created_at)
- `access_log`, `audit_log` (hash-chained), `consents`, `verification_requests`, `users`

## 8. Flag types (use exactly these)

`INVALID_APAAR, APAAR_NOT_FOUND, APAAR_MISMATCH, DUPLICATE_IN_UPLOAD, EXCESS_INTAKE, CROSS_INSTITUTION_DUPLICATE, POSSIBLE_DUAL_DEGREE, IDENTITY_DUPLICATE, LATE_ADMISSION, STUDENT_CORRECTION`

Each maps to a PS requirement 3 validation (duplicate records, invalid/missing APAAR, excess intake, data inconsistencies, cross-institution duplicates). `STUDENT_CORRECTION` is a low-severity request from a student to fix a field in their own record.

Severity: `low | medium | high | critical`.
**Every flag must have a human-readable `explanation` and structured `evidence`.** No unexplained flags — explainability is a core judging point.

## 9. Coding conventions

- Small, focused modules. Business logic lives in `/services`, never in routers.
- Type hints everywhere; Pydantic schemas for all request/response bodies.
- Every service gets pytest tests. Run `make test` after every change and fix failures before finishing.
- Don't add dependencies beyond the stack above without asking.
- Don't refactor modules outside the current task.
- Frontend: typed API client in `web/lib/api.ts`; one component per file; shadcn/ui components; consistent severity colours (low=slate, medium=amber, high=orange, critical=red).
- Keep the app working at the end of every step. Commit after every step.

## 10. Definition of done for any task

1. Code written and follows the rules above.
2. Tests added and `make test` passes.
3. App still starts with `make dev`.
4. You report: what changed, how to try it, and anything left undone.