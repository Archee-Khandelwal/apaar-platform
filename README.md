# APAAR Student Data & Verification Platform

**Smart India Hackathon 2026 · Problem statement SIH26263 (AICTE)**
"Development of an APAAR ID-Based Student Data Management and Verification Platform for AICTE-Approved Institutions."

> **Prototype — all data is synthetic.** Every institution, student, APAAR ID and the APAAR
> registry itself is invented. There is no connection to any real APAAR / ABC system.

AICTE today largely receives *counts* of enrolled students. This platform takes **student-level**
records keyed on the 12-digit APAAR ID, validates them against a registry, detects duplicate,
invalid and excess admissions with explainable rules, gives AICTE a national view, lets students
see what was reported about them and ask for corrections, and lets employers verify a student
**only with that student's consent**.

---

## Quick start

```bash
make setup      # venv + python deps + .env secrets + npm install   (once)
make demo       # reset the data, then start all three services
```

Or step by step:

```bash
make reset      # wipe and regenerate ~15,000 synthetic students, then run every detector
make dev        # api :8000, mock registry :8001, web :3000
```

| What | URL |
|---|---|
| Web app | http://localhost:3000 |
| API docs (interactive) | http://localhost:8000/docs |
| API health | http://localhost:8000/health |
| Mock registry health | http://localhost:8001/health |

Every account has its own password. After a reset they are in `demo_credentials.csv` at the repo root (gitignored); the login page lists the accounts, and you type the password.

## Windows commands (no make)

From the repo root in PowerShell, once:

```powershell
python scripts/tasks.py setup
```

Reset and reseed the data (stop the API first, or this drops the tables in place instead):

```powershell
python scripts/tasks.py reset
```

Start each service in its own PowerShell window (all from the repo root):

```powershell
# 1. Mock APAAR registry  :8001
$env:PYTHONPATH = "$PWD\api;$PWD"; .\.venv\Scripts\python.exe -m uvicorn registry.app.main:app --port 8001

# 2. Issuer & DigiLocker registry  :8002
$env:PYTHONPATH = "$PWD\api;$PWD"; .\.venv\Scripts\python.exe -m uvicorn issuer.app.main:app --port 8002

# 3. API  :8000
$env:PYTHONPATH = "$PWD\api;$PWD"; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# 4. Web app  :3000
cd web; npm run dev
```

`python scripts/tasks.py dev` starts all four in one window instead.

---

## Make targets

| Target | What it does |
|---|---|
| `make setup` | Creates `.venv`, installs `api/requirements.txt`, generates `.env` secrets, installs web packages |
| `make keys` | (Re)generates `HMAC_KEY`, `VAULT_KEY`, `JWT_SECRET`, `REGISTRY_API_KEY` into `.env` |
| `make demo` | `reset` then `dev` — one command to a demo-ready stack |
| `make dev` | Runs all three services together (Ctrl+C stops them all) |
| `make dev-api` / `make dev-registry` / `make dev-web` | Run one service on its own |
| `make test` | pytest |
| `make reset` | Delete the databases, regenerate synthetic data, run every detector |
| `make eval` | Score every detector against `datagen/ground_truth.json` → `docs/EVALUATION.md` |
| `make eval-robust` | Score a **second, perturbed** dataset the detectors were not tuned on → `docs/EVALUATION_ROBUST.md` |

### Checking the UI

With the stack running, `cd web && npm run screenshots` signs in as each demo role and
saves a full-page screenshot of every page into `web/screenshots/<role>/<page>--<width>.png`
at 1440px and 768px (and 390px for the login and student pages). It prints any console or
network error it saw, so a broken page shows up as a file you can look at rather than a
bug someone finds during the demo. Pass role names to narrow it, e.g.
`npm run screenshots -- student aicte_officer`.

---

## Demo accounts

| Username | Role | What it shows |
|---|---|---|
| `aicte_officer1` | AICTE Officer | Everything: flag evidence, reveal with a reason, case management |
| `aicte_viewer1` | AICTE Analyst | The same screens with masked rows and counts below 5 shown as `<5` |
| `kolhanpur32_admin` | Institution | The college used for the live upload in the script below |
| `narmadapuri25_admin` | Institution | A college that is 25 seats over its approved intake |
| `meghdoot40_admin` | Institution | The clean model college — no findings at all |
| `student_mismatch` | Student | Reported name/DOB does not match the APAAR registry |
| `student_duplicate` | Student | Reported by two institutions at once |
| `student_dual` | Student | A legitimate dual degree (regular + online) |
| `student_minor` | Student | Under 18, so verification needs parental consent |
| `student_fn` | Student | Foreign national, `apaar_status = not_applicable` |
| `student_pending` | Student | Has a verifier request waiting |
| `student_revoked` | Student | Withdrew a consent earlier |
| `verifier_demo` | Verifier | Employer asking to verify a student |
| `admin` | Admin | Reseed, verify the audit chain |

Any of the 40 institution accounts works; they are named `<invented-word><id>_admin`.
Account names change when you reseed with a different seed — the login page always lists the
current ones.

---

## Demo script

Reset the data first (see *Windows commands* below), then open http://localhost:3000. Passwords are in
`demo_credentials.csv`. Nav labels below are the sidebar entries.

1. **College login, and the wall between colleges.** Sign in as `kolhanpur32_admin`. Open **Students**
   and **Seat matrix**: only Kolhanpur's programmes appear. Change the URL to another college's id
   (for example `/institution/documents/<another college's student id>`) and it returns *not found* —
   the institution comes from the login token, never from the request.
2. **Upload data.** **Upload data** → `samples/sample_1_excess_intake.xlsx` → confirm the proposed
   column mapping → validate. Show the quality report and the **EXCESS_INTAKE** finding, then **Seat
   matrix**: *Approved Intake* vs *Actual Student Enrolment*, with *Supernumerary Seats* (TFW, lateral,
   NRI category, FN/PIO/OCI, PMSSS) shown outside intake, each against its own cap.
3. **Upload documents.** **Documents** → bulk-upload `samples/sample_4_documents.zip`, or open one
   student's checklist and add files. Each file is OCR'd, its QR and issuer checked, and matched
   against the reported name and DOB.
4. **AICTE cross-check dashboard.** Switch role to `aicte_officer1` → **Reconciliation**. Every
   reported record is checked six ways (institution approved, programme approved, within intake,
   APAAR verified, documents verified, no duplicate) and shown *confirmed / needs review / rejected*
   with the reason.
5. **Officer reviews a mismatched document.** **Document review** → open a case whose extracted
   name or DOB differs from the record → read the side-by-side comparison → approve or reject with a
   reason. Return to **Reconciliation**: the record now reads **confirmed**.
6. **Employer verification with consent.** Switch role to `verifier_demo` → request verification of
   `student_pending` (APAAR ID visible from that student's **My records**). Result: *pending*. As
   `student_pending` → **Consents**, approve. Back as the verifier: only *verified*, programme and
   year. Withdraw consent and the result and any QR token stop working.
7. **Degree certificate.** As the institution → **Degree certificates** → *Issue certificate* for a
   completed student. The PDF prints the APAAR ID beside the student ID and a QR. Scan it (or open
   its `/verify?doc=…` link, no login): **Genuine**, with the masked claims. Revoke it and the same
   link reads **Revoked**.

### Things worth saying if asked

- **Dual degree is legal.** `student_dual` has one regular and one online enrolment and is recorded
  as *possible dual degree*, severity low, never as fraud. `student_duplicate` has two full-time
  regular enrolments and *is* flagged. That distinction is in `app/services/duplicates.py`.
- **Foreign nationals.** `student_fn` has no APAAR ID at all. `apaar_status = not_applicable` is
  valid for FN/OCI students and is not an error.
- **Minors.** `student_minor` is under 18, so a verification request against them is marked
  *parental consent required*.
- **Accuracy.** `make eval` prints precision/recall/F1 per scenario and writes `docs/EVALUATION.md`.
  `make eval-robust` scores a second dataset with perturbations the detectors were never tuned on,
  and `docs/EVALUATION_ROBUST.md` diagnoses every miss. Read the caveat in both before quoting a
  number.

---

## Security

Security is one of the three things this platform is about, so every control below is
enforced in code **and proved by a named test** (`api/tests/…`). Run `make test` (or the
Windows command in *Quick start*) to re-prove all of them.

| Control | How it works | Proved by |
|---|---|---|
| Unique password per account | Every institution (and every other demo account) gets its own random 12-character password at seed time. Only a bcrypt hash is stored. The plain passwords are written once to `demo_credentials.csv`, which is gitignored and never served by the API | `test_security.py::test_each_institution_gets_its_own_random_password`, `::test_credentials_are_written_only_to_a_gitignored_file`, `::test_no_route_or_schema_hands_out_a_password` |
| Login throttling | 5 failed attempts per account, or 20 per client, inside 15 minutes → `429 TOO_MANY_ATTEMPTS` with a retry time. Success clears the account's counter | `test_security.py::test_repeated_failures_lock_the_account_for_a_while`, `::test_one_client_guessing_many_accounts_is_throttled` |
| Password change | `POST /auth/change-password` needs the current password and a policy-compliant new one; it bumps a token version so **every older JWT stops working** | `test_security.py::test_changing_a_password_ends_every_other_session`, `::test_weak_passwords_are_refused` |
| Admin reset | `POST /admin/users/{id}/reset-password` issues a one-time password shown once; the account can only change it, and all its sessions end | `test_security.py::test_admin_reset_issues_a_one_time_password` |
| RBAC on every route | One `require_role(...)` dependency. An explicit route × role matrix is tested exhaustively (403 for every disallowed role, 401 with no token), and a new route without a matrix entry fails the build | `test_security.py::test_the_matrix_covers_every_route`, `::test_every_route_refuses_every_role_it_does_not_allow`, `::test_every_protected_route_refuses_a_missing_token`, `test_qa_invariants.py::test_every_route_is_guarded_or_documented_public` |
| Tenant isolation | An institution's `institution_id` comes only from its JWT. Another college's id in the URL returns 404; an `institution_id` smuggled into the query or body is ignored | `test_tenant_isolation.py` (uploads, flags, enrolments, certificates; URL, query and body attacks) |
| Hash-chained audit log | Each row stores `prev_hash` and `hash = sha256(prev_hash + canonical_json(row))`. Logins, failed logins, uploads, reveals, consent decisions and password events are recorded; the admin page verifies the chain and runs a tamper test on a copy | `test_audit.py` (tamper, delete, re-hash), `test_security.py::test_security_relevant_events_land_in_a_valid_audit_chain` |
| Documents encrypted at rest | Submitted documents are stored Fernet-encrypted with the vault key; the type is decided by the file's first bytes (PDF/JPEG/PNG only), PDFs with JavaScript or launch actions are refused, and ZIP imports are size-checked before and while expanding | `test_documents.py::test_a_pdf_upload_is_stored_encrypted_with_its_hash`, `::test_the_type_is_decided_by_content_not_the_name`, `::test_a_pdf_with_javascript_is_refused`, `::test_a_zip_bomb_is_refused_before_it_is_expanded` |
| Who may read a document | The owning institution, an AICTE officer with a written reason, or the student — every read is access-logged | `test_documents.py::test_the_owning_institution_can_download_and_it_is_logged`, `::test_an_officer_needs_a_reason_and_the_reason_is_logged`, `::test_the_student_can_read_their_own_documents_only`, `::test_another_institution_cannot_download_it` |
| Tamper-evident documents | The SHA-256 of each file is recorded at upload and re-checked on every view; a mismatch withholds the file, rejects it and raises a critical `DOCUMENT_TAMPERED` flag | `test_documents.py::test_a_file_altered_in_storage_is_withheld_and_flagged`, `::test_a_corrupted_ciphertext_is_also_caught` |
| No raw contact details | Phone, email and guardian phone exist only as `HMAC-SHA256(HMAC_KEY, normalised_value)` | `test_crypto.py::test_hmac_hash_is_keyed_not_plain_sha256`, `test_qa_invariants.py::test_no_response_schema_exposes_a_hash_or_a_raw_contact` |
| Raw identifiers encrypted | APAAR ID, full name and DOB live only in the Fernet-encrypted `vault` table | `test_crypto.py::test_vault_ciphertext_is_not_the_plaintext`, `test_student_verifier.py::test_the_raw_apaar_is_never_stored_by_a_request` |
| Secrets from the environment | `HMAC_KEY`, `VAULT_KEY`, `JWT_SECRET`, `REGISTRY_API_KEY` come from the gitignored `.env` | `test_qa_invariants.py::test_env_example_lists_every_secret_and_commits_none` |
| Masked by default, reveal with a reason | `XXXX-XXXX-1234` and `R***** S.` everywhere. Full details only via `POST /aicte/reveal`, officer only, with a mandatory reason that is access-logged | `test_aicte.py::test_reveal_demands_a_real_reason`, `::test_reveal_returns_raw_identifiers_and_logs_the_access` |
| Access log visible to the student | Every reveal and case-file view is logged with actor, role, action, target, reason and time; the student can read their own entries | `test_audit.py::test_access_log_records_actor_role_action_target_reason`, `test_student_verifier.py::test_student_sees_who_accessed_their_data_with_role_labels` |
| Small-count suppression | For `aicte_viewer`, any breakdown count below 5 is returned as `"<5"` | `test_aicte.py::test_overview_suppresses_small_counts_for_the_viewer` |
| Colleges never learn about each other | A cross-institution finding shown to a college reads "Possible duplicate enrolment — contact AICTE" | `test_duplicates.py::test_the_institution_view_never_names_the_other_college` |
| Consent and minimal verification | A verifier learns nothing until the student approves, then only `verified`, programme and year; minors are marked *parental consent required* | `test_student_verifier.py::test_verifier_learns_nothing_before_the_student_approves`, `::test_approval_gives_the_verifier_the_minimal_result_only`, `::test_a_minor_is_marked_as_needing_parental_consent` |

## Repository layout

```
/api        FastAPI backend
  /app
    /core       config, db, security (JWT + RBAC), crypto (HMAC + vault), audit, access log
    /models     SQLAlchemy models and the domain vocabularies
    /schemas    Pydantic request/response schemas
    /routers    auth, institution, aicte, student, verifier, admin
    /services   upload, validation, mapping, intake, duplicates, heuristics, flags,
                cases, consent, tokens, aggregates, documents, degree_certificate, detectors
    /rules      intake_rules.yaml, reporting_calendar.yaml  (every cap and date lives here)
  /tests      pytest suite
/registry   Mock APAAR registry — a separate FastAPI service on port 8001
/datagen    Synthetic generator, ground_truth.json, evaluate.py, robustness run
/web        Next.js (App Router) + TypeScript + Tailwind frontend
  /app        one route group per role, each behind a RoleGuard
  /components AppShell (per-role sidebar), DataTable, ExplanationPanel, ui/page.tsx primitives
  /lib        typed API client, auth, and the single navigation map in nav.tsx
  /scripts    screenshot.ts — the visual check described above
/samples    Deliberately messy Excel/CSV files for live demo uploads
/docs       API_CONTRACT.md (frozen), PLAN.md, EVALUATION.md, EVALUATION_ROBUST.md
/scripts    gen_keys.py, dev.sh
```

## How the detection works

| Finding | Rule |
|---|---|
| `EXCESS_INTAKE` | Regular admissions beyond approved intake, plus any supernumerary bucket beyond its own cap. Caps live in `intake_rules.yaml`; lateral entry joins in year 2 and never counts against year-1 intake. Severity scales with the share over intake |
| `CROSS_INSTITUTION_DUPLICATE` | One APAAR, two institutions, same year, both full-time regular |
| `POSSIBLE_DUAL_DEGREE` | The same shape with at least one online/ODL programme — legal, severity low, never presented as fraud |
| `IDENTITY_DUPLICATE` | Two APAAR IDs with the same normalised name, DOB and guardian phone. The name is decrypted only inside the service and never reaches the flag |
| `LATE_ADMISSION` | Admitted after the window in `reporting_calendar.yaml`, per row and aggregated per institution. Lateral entrants are judged against their own later window |
| `STUDENT_CORRECTION` | A student asks the reporting institution to correct one field of their record; low severity, visible to the institution and AICTE |
| `INVALID_APAAR` / `APAAR_NOT_FOUND` / `APAAR_MISMATCH` | Format check, then a batch lookup against the mock registry (rapidfuzz ≥ 90 on the name, exact DOB) |

## Mock APAAR registry

There is no public APAAR/ABC verification API, so `/registry` is a separate FastAPI service with
the **same shape** we would use against the real thing: `POST /verify`, `POST /verify/batch`
(≤ 500 records), API-key auth and `match | mismatch | not_found | consent_required`. Swapping in
the real registry means replacing one module, `api/app/services/registry_client.py`. If the
registry is down, uploads continue and the rows are marked `source_unavailable` rather than failing
— stop the registry and try an upload to see it.

## Known limitations

See the bottom of `docs/EVALUATION_ROBUST.md` for the measured ones. In short: identity matching is
exact on the normalised name, so typos and reorderings are missed; and one admission window is
applied to every programme mode, so a later online/ODL intake is flagged as late.

## Documentation

- `docs/API_CONTRACT.md` — every endpoint, role, request/response example (frozen; changes go through this file and its changelog)
- `docs/PLAN.md` — the build checklist and the recorded design decisions
- `docs/EVALUATION.md` — precision / recall / F1 per detector, with the caveat that matters
- `docs/EVALUATION_ROBUST.md` — the same on a perturbed dataset, with every miss diagnosed
- `CLAUDE.md` — project context, privacy rules and domain rules
