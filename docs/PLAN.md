# PLAN.md — Build order checklist (SIH26263)

Mirrors `docs/BUILD_PROMPTS.md` Steps 0–20. Tick boxes as we go. Definition of done for every step (CLAUDE.md §10): code follows the rules → tests added and `make test` passes → `make dev` still starts → a short report of what changed, how to try it, what's left.

**Commit after every step:** `git add -A && git commit -m "Step N: <name>"`

**Parallelism:** Steps 1–13 are backend/data (A, B, C). Steps 14–19 are frontend (D, E) and can start once Step 2 is done, working against `docs/API_CONTRACT.md` (frozen).

Legend: ☐ not started · ◐ in progress · ☑ done

---

## Step 0 — Kickoff & API contract  ☑

- [x] Read `CLAUDE.md` in full
- [x] 10-bullet project summary confirmed back to the team
- [x] `docs/API_CONTRACT.md` — every endpoint per router + registry, with role, request/response examples, pagination and filters
- [x] `docs/PLAN.md` — this checklist
- [ ] Open questions in §"Open questions" below answered by the team
- **Check:** frontend people agree the contract is usable → then it is **frozen** (changes go through the contract file + changelog)

## Step 1 — Monorepo scaffold  ☑

- [x] `/api` FastAPI app: `/health`, `pydantic-settings` config from env, SQLAlchemy 2.0 engine/session, `DATABASE_URL` default `sqlite:///./apaar.db`, `requirements.txt`
- [x] `/registry` separate FastAPI app with `/health` on port 8001
- [x] `/datagen` package with `__main__.py`
- [x] `/web` Next.js App Router + TS + Tailwind + shadcn/ui, one placeholder page
- [x] `.env.example` (`HMAC_KEY`, `VAULT_KEY`, `JWT_SECRET`, `DATABASE_URL`, `REGISTRY_URL`, `REGISTRY_API_KEY`) + key-generation script
- [x] `Makefile`: `setup`, `dev` (api + registry + web), `test`, `seed` (placeholder), `reset`
- [x] `.gitignore` (venv, node_modules, .env, *.db), `README.md` setup steps
- **Check:** `make setup`, `make dev`; all three health endpoints respond (3000, 8000/health, 8001/health)

## Step 2 — Data model, crypto, audit  ☑

- [x] SQLAlchemy models for every table in CLAUDE.md §7, indexed on `apaar_hash`, `phone_hash`, `guardian_phone_hash`, `email_hash`, `institution_id`, `academic_year`
- [x] `app/core/crypto.py`: `hmac_hash()` (HMAC-SHA256 + normalisation: strip, lowercase emails, phones → last 10 digits), Fernet vault encrypt/decrypt, `mask_apaar()`, `mask_name()`
- [x] `app/core/audit.py`: append-only hash chain (`prev_hash`, `hash = sha256(prev_hash + canonical_json(row))`) + `verify_chain()`
- [x] `app/core/access_log.py`: `log_access(actor, role, action, target, reason)`
- [x] DB init on startup (`create_all` is fine)
- [x] Tests: keyed + deterministic hashing, masking, vault round-trip, valid chain passes, tampered row detected
- **Check:** `make test` passes · **Gate:** frontend (Step 14) can start after this

## Step 3 — Auth, RBAC, tenant isolation  ☑

- [x] `users` table (role, optional `institution_id` / `student_id`), bcrypt via passlib
- [x] `POST /auth/login` → JWT with `user_id`, `role`, `institution_id`, `student_id`; `GET /auth/me`
- [x] `GET /auth/demo-users` (demo-mode only) for the one-click role switcher
- [x] `app/core/security.py`: `get_current_user`, `require_role(*roles)` — on **every** route except login/health/public token check
- [x] Tenant-scope helper/dependency so routers cannot forget to filter by the JWT's `institution_id`
- [x] `suppress_small_counts(dict, role)` → `"<5"` for `aicte_viewer`
- [x] Tests: wrong role → 403; institution user passing another institution's id in the URL still cannot read it; suppression works
- **Check:** manual 403 with an institution token on an AICTE route

## Step 4 — Mock APAAR registry  ☑

- [x] Registry SQLite DB of issued APAARs (apaar, name, dob) + `POST /registry/apaar/bulk` seeding hook
- [x] `POST /verify` → `match | mismatch | not_found | consent_required` (rapidfuzz ≥ 90 on name, exact DOB)
- [x] `POST /verify/batch` (≤ 500 records)
- [x] API-key auth (`X-API-Key`) + artificial 20–50 ms latency
- [x] `app/services/registry_client.py`: typed client, timeout + retry, `source_unavailable` result
- [x] README note: same shape as the real APAAR/ABC API would be
- [x] Tests: match, mismatch, not_found, registry-down
- **Check:** stop the registry → main API reports "source unavailable", does not crash

## Step 5 — Synthetic data generator with fraud scenarios  ☐

- [ ] 40 clearly fictional institutions across ~10 states, 3–6 programs each, some online/ODL
- [ ] Approved intake per program per year with supernumerary caps from `api/app/rules/intake_rules.yaml`
- [ ] ~15,000 students across `2025-26` and `2026-27`; Faker `en_IN`; realistic gender/category/nationality mix; ~2% FN/OCI with `apaar_status = not_applicable`; some minors
- [ ] Contacts only as HMAC hashes (same crypto module); raw APAAR/name/DOB → vault; every issued APAAR also inserted into the registry
- [ ] Labelled scenarios + `datagen/ground_truth.json`:
  - [ ] A `EXCESS_INTAKE` — 3 institutions over intake after valid supernumerary (one by just 3 seats)
  - [ ] B `GHOST_CLUSTER` — 2 institutions, clusters of 25–35 students on 2–3 guardian phones
  - [ ] C `CROSS_INSTITUTION_DUPLICATE` — 15 students, two full-time regular programs, same year
  - [ ] D `POSSIBLE_DUAL_DEGREE` (legit) — 10 students, one regular + one online
  - [ ] E `INVALID_APAAR` / `APAAR_NOT_FOUND` / `APAAR_MISMATCH` — ~1% of records
  - [ ] F `LATE_ADMISSION` — ~40 post-cutoff admissions at 2 institutions
  - [ ] G `SEQUENTIAL_APAAR` — one institution with a run of 20 near-consecutive IDs
  - [ ] H `LAST_MINUTE_BULK` — one institution, 60% of records in the final 6 hours
  - [ ] I `PHANTOM_PROGRESSION` — year-2 regulars with no year-1 record (not lateral) + students vanishing without a status
  - [ ] J `IDENTITY_DUPLICATE` — 8 people with two APAARs (same name + DOB + guardian phone)
  - [ ] One clean "model" institution (compliance-certificate demo)
- [ ] `/samples`: 3 messy Excel files (weird headers, mixed date formats, blank rows, errors); one triggers scenario A
- [ ] `make seed` / `make reset` wired; deterministic `--seed`
- **Check:** `make reset` runs; spot-check `ground_truth.json` counts

## Step 6 — Upload pipeline & validation  ☐

- [ ] `POST /institution/uploads` (multipart Excel/CSV, pandas/openpyxl, skip blank rows)
- [ ] Column mapping with rapidfuzz + synonym dictionary, confidence per column, state `pending_mapping`
- [ ] `POST /institution/uploads/{id}/confirm-mapping` → runs validation
- [ ] Row validation: required fields, APAAR format, `apaar_status` rules (`not_applicable` only FN/OCI), multi-format date parsing, DOB plausibility, admission window (else `LATE_ADMISSION`), in-upload duplicates, batch registry check
- [ ] Valid rows stored (hashes + vault, never raw contacts); invalid rows reported, not stored
- [ ] Quality report: score 0–100, counts, per-row errors/warnings each with a fix suggestion
- [ ] `GET /institution/uploads`, `GET /institution/uploads/{id}`, errors CSV, `GET /institution/template`
- [ ] Every upload writes to the audit log
- [ ] Tests on `/samples` files + an all-garbage file that must not crash
- [ ] Synchronous but batched: 5,000 rows finishes in reasonable time
- **Check:** upload a sample file via `http://localhost:8000/docs`

## Step 7 — Intake compliance engine  ☐

- [ ] `intake_rules.yaml`: versioned `rule_set: APH_2026_27_v1`, which admission types count within intake, cap per supernumerary category (% of intake), lateral-entry rules (year 2, cap + vacant year-1 seats), every number with `# VERIFY against AICTE Approval Process Handbook 2026-27`
- [ ] `compute_seat_matrix(program, year)` → intake, regular admitted, per-bucket admitted vs cap, valid supernumerary, excess, step-by-step explanation
- [ ] Runs after every upload confirmation and after seeding; creates/updates `EXCESS_INTAKE` with the seat matrix as evidence
- [ ] `GET /institution/seat-matrix` (own only), `GET /aicte/institutions/{id}/seat-matrix`
- [ ] Unit tests: exactly at intake (no flag), over by regular, over only via a supernumerary bucket, lateral entry not counted in year 1
- **Check:** scenario A from `ground_truth.json` detected exactly

## Step 8 — Duplicate & identity detection  ☐

- [ ] `CROSS_INSTITUTION_DUPLICATE`: same `apaar_hash`, active enrolments at 2+ institutions in the same year
- [ ] One program `mode = online` → `POSSIBLE_DUAL_DEGREE` (low, informational); both full-time regular → `CROSS_INSTITUTION_DUPLICATE` (high)
- [ ] `IDENTITY_DUPLICATE`: different `apaar_hash`, same normalised name (decrypted only inside the service, never returned) + same DOB + same `guardian_phone_hash`
- [ ] College-facing flags never name the other institution (CLAUDE.md §5.10); officer view shows both sides
- [ ] Evidence JSON: masked APAARs, institution ids, programs, years, classification reason
- [ ] Tests + scenarios C, D, J classified correctly (**D must not be flagged as fraud**)

## Step 9 — Ghost-student graph detector (headline)  ☐

- [ ] networkx graph: student nodes + attribute nodes (`guardian_phone_hash`, `phone_hash`, `email_hash`), edges student→attribute
- [ ] Connected components; `GHOST_CLUSTER` on abnormal density (configurable, e.g. ≥ 8 students sharing ≤ 3 guardian contacts, or one contact across institutions); normal siblings (2–3) ignored
- [ ] Cluster score (size, attribute-to-student ratio, institutions involved) drives severity
- [ ] `GET /aicte/graph/clusters` (masked summaries) and `GET /aicte/graph/clusters/{id}` (Cytoscape JSON, labels masked, attributes as "Guardian contact #1")
- [ ] Every cluster view writes to the access log
- [ ] Tests + both scenario-B clusters found, no false positives on sibling pairs

## Step 10 — Heuristic detectors  ☐

- [ ] `SEQUENTIAL_APAAR`: per institution-year, runs of ≥ 10 near-consecutive IDs (raw sort inside the service only); evidence = run length + masked first/last
- [ ] `LATE_ADMISSION`: aggregate per institution (count, % of admissions)
- [ ] `LAST_MINUTE_BULK`: share of records created within N hours of the deadline over threshold
- [ ] `PHANTOM_PROGRESSION`: year-2 regulars with no year-1 enrolment (excluding lateral); year-1 students vanishing in year 2 with no `cancelled|migrated|dropped`
- [ ] `run_all_detectors()` single entry point, **idempotent**, called by reseed and upload confirmation
- [ ] Tests + scenarios F, G, H, I detected

## Step 11 — Risk score, anomaly model, shortlist, evaluation  ☐

- [ ] IsolationForest per institution-year on: fill ratio, % missing/invalid APAAR, % late admissions, YoY growth, distance of category/gender mix from state average, % records created in the last 6 hours → `STATISTICAL_ANOMALY` with top contributing features vs state median as explanation
- [ ] Risk score 0–100 per institution: weighted open flags (type × severity) + anomaly score; weights in a config dict; **always** top 3 reasons in plain English
- [ ] `GET /aicte/risk`, `GET /aicte/inspection-shortlist?limit=10` (+ CSV)
- [ ] `datagen/evaluate.py`: precision/recall/F1 per scenario type vs `ground_truth.json` + summary table → `docs/EVALUATION.md`; report misses honestly, don't tune on the eval
- [ ] `make eval`
- **Check:** `make reset && make eval` — record the numbers for the pitch

## Step 12 — Flags, cases, reveal, AICTE APIs  ☐

- [ ] `GET /aicte/overview` (national KPIs + state breakdown, suppression for viewer)
- [ ] `GET /aicte/institutions` (search/filter by state, risk), `GET /aicte/institutions/{id}` (profile, seat matrix, flags, risk reasons)
- [ ] `GET /aicte/flags` (filters + pagination), `GET /aicte/flags/{id}`, `PATCH /aicte/flags/{id}` (status, assignment, notes) — every change audit-logged
- [ ] `POST /aicte/reveal` (officer only, reason ≥ 10 chars, access-logged; everything else stays masked)
- [ ] `GET /aicte/non-reporting`, `POST /aicte/remind/{id}` (mocked, logged)
- [ ] `GET /aicte/reports/trends` + CSV export
- [ ] Institution side: `GET /institution/flags` (own only, rule-10 wording), `PATCH /institution/enrolments/{id}/status` (versioned, with reason), `GET /institution/compliance-certificate` (only with no open high/critical)
- [ ] Tests: RBAC on every new route, reveal requires a reason, suppression

## Step 13 — Student & verifier APIs, consent, tokens  ☐

- [ ] `GET /student/me`
- [ ] `POST /student/enrolments/{id}/confirm` and `/dispute` (dispute → `STUDENT_DISPUTE`, critical, visible to AICTE + institution)
- [ ] `POST /student/corrections` → institution flag inbox
- [ ] `GET /student/access-log` ("who accessed my data")
- [ ] `GET /student/consents`, `POST /student/consents/{id}/approve|deny|revoke`
- [ ] `GET /student/id-card` (masked APAAR + QR with a signed token)
- [ ] `POST /verifier/requests` (purpose from a fixed list; mock OTP; minors → "parental consent required")
- [ ] `GET /verifier/requests/{id}` → pending/approved/denied/expired; on approval the **minimal** response only (verified, program, year)
- [ ] Tokens: HMAC-signed, 15-min default expiry, carry consent id; `GET /verify/token/{token}` → genuine / expired / revoked / invalid
- [ ] Everything audit-logged + access-logged
- [ ] Tests: nothing before approval, denied + expired paths, revoked consent invalidates the token, tampered token fails
- **Backend milestone:** `make reset && make test && make eval` all green before heavy frontend integration

## Step 14 — Frontend foundation  ☐

- [ ] `web/lib/api.ts` typed client from `docs/API_CONTRACT.md` (fetch + TanStack Query, JWT in memory, sessionStorage wrapped in try/catch)
- [ ] Login page + demo role switcher (top bar) using `/auth/demo-users`
- [ ] App shell: per-role sidebar, role badge, permanent banner "Prototype — all data is synthetic"
- [ ] Shared components: `MaskedApaar`, `MaskedName`, `SeverityBadge` (low=slate, medium=amber, high=orange, critical=red), `StatCard`, `DataTable` (sort/filter/paginate), `EmptyState`, `LoadingSkeleton`, `ExplanationPanel`, `RevealButton` (reason modal)
- [ ] Government-dashboard look: neutral palette + one accent, responsive to tablet width
- [ ] Route guards per role

## Step 15 — Institution portal  ☐

- [ ] Dashboard: quality score trend, open flags, seat matrix summary, upload CTA
- [ ] Upload flow: drag-and-drop → mapping screen (header, proposed field, confidence, override dropdown) → confirm → quality report (score dial, errors/warnings with fixes, error CSV download)
- [ ] Seat matrix page: stacked bar (intake vs regular vs each supernumerary bucket vs excess) + plain-English explanation
- [ ] Flag inbox (own only, rule-10 wording) with "mark resolved / correct & resubmit"
- [ ] Students list (masked) + status update (cancel/migrate/drop with reason)
- [ ] Upload history, compliance certificate download (disabled with a reason when ineligible), template download

## Step 16 — AICTE dashboard  ☐

- [ ] National overview: StatCards, state-wise Recharts bar, flags by type/severity, total excess seats; `"<5"` rendered gracefully for viewers
- [ ] Flag queue: DataTable + filters, `ExplanationPanel` drawer, actions (review, escalate, dismiss, assign, note)
- [ ] Institution drill-down: profile, risk gauge + top 3 reasons, seat matrix, flags, upload timeline
- [ ] Risk leaderboard + inspection shortlist (top 10 with reasons, exportable)
- [ ] Non-reporting page with "send reminder"
- [ ] Reports page: trends charts + CSV export
- [ ] Reveal: `RevealButton` (officer only) → reason modal → details + toast "This access has been logged"

## Step 17 — Ghost-cluster graph view (most important screen)  ☐

- [ ] Clusters list: cards with score, students, shared contacts, institutions, severity
- [ ] Cluster detail with react-cytoscapejs: students as circles coloured by institution, shared contacts as larger accent diamonds, edges labelled by attribute type, cose force-directed layout with load animation
- [ ] Hover tooltips (masked); click a student → side panel (masked, `RevealButton` for officers)
- [ ] Legend + plain-English summary ("32 students at Institute X share only 3 guardian contacts — typical families share 1 contact per 1–3 students")
- [ ] "Compare with a normal cluster" toggle (side-by-side healthy sibling cluster)
- [ ] Smooth at ~100 nodes

## Step 18 — Student & verifier portals  ☐

- [ ] "Was this you?" card for unconfirmed enrolments → Confirm / Dispute (reason) → "AICTE has been notified" + case status
- [ ] My records page + correction request form
- [ ] "Who accessed my data" timeline (actor role, purpose/reason, time)
- [ ] Consent manager: pending (verifier, purpose, what will be shared) → approve/deny; active → revoke; minors see "parental consent required"
- [ ] Digital ID card with QR from `/student/id-card`
- [ ] Verifier: request form (APAAR + purpose), status page polling until resolved, minimal result card
- [ ] Public "Verify a token/QR" page (paste or camera scan) → Genuine / Expired / Revoked / Invalid in big clear states
- [ ] Mobile-friendly

## Step 19 — Admin & demo tooling  ☐

- [ ] Admin page: reset & reseed, "load scenario A–J" buttons, "verify audit chain", "tamper test" (on a copy) showing detection
- [ ] `POST /admin/reseed`, `POST /admin/load-scenario/{name}` (admin only)
- [ ] Seed so the demo story runs in order: messy upload → excess intake → ghost cluster → student dispute → duplicate vs dual degree → verifier consent
- [ ] README: setup, `make` commands, demo accounts, 5-minute walkthrough with exact clicks
- [ ] `make reset && make dev` → clean demo-ready state in one command

## Step 20 — Final QA & hardening (no new features)  ☐

- [ ] `make reset && make test && make eval` all green
- [ ] Security review vs CLAUDE.md §5: any raw phone/email/APAAR/name returned or logged, any route missing `require_role`, any institution query not tenant-scoped, any hardcoded secret → fix and list
- [ ] Walk the README demo script end to end via the API; each step's data actually appears
- [ ] Edge cases: empty upload, 5,000-row timing, registry down, expired token, revoked consent, cross-role page access
- [ ] Frontend: no console errors, loading/empty states everywhere, works at 1280px and tablet
- [ ] Final report: fixes, known limitations, anything not to show in the demo

---

## If we fall behind (cut order)

24-hour format per `BUILD_PROMPTS.md`: Steps 0–11 backend and 14–17 frontend in parallel → Step 13 only if time allows (otherwise skip to 18 with just the dispute page) → 19–20. Reduce Step 5 to 20 institutions / ~6,000 students and drop scenarios H and I if short. Protect, in order: Step 9 (graph view), Step 7 (seat matrix), Step 6 (messy upload), Step 13 consent flow — that is the demo spine.

## Decisions (recorded Step 0, approved by the team)

| # | Question | Decision |
|---|---|---|
| 1 | Admission cutoff / reporting deadline location | **Separate `api/app/rules/reporting_calendar.yaml`**, keyed by academic year (`admission_window_start`, `admission_window_end`, `reporting_deadline`). Kept apart from `intake_rules.yaml` because calendar dates change more often. Both files are versioned. |
| 2 | Student logins | **8 demo students**, not one per seeded student: ghost-cluster member who disputes, cross-institution fraud victim, legitimate dual-degree student, minor, FN with `apaar_status = not_applicable`, clean normal student, student with a pending verifier request, student with a revoked consent. Login names listed in the README. |
| 3 | `aicte_viewer` and flags | Viewers **can list** flags but get masked fields only: type, severity, institution, state, status, counts — with small-count suppression. **No** `evidence` internals, no reveal, no status change / assignment / notes. Officer gets full detail. |
| 4 | Minor verification | Approvable with a `parental_consent_required: true` marker (not blocked outright). |
| 5 | Consent validity | 72 h for a pending request, 15 min for an issued token; both config-driven. |
| 6 | Compliance certificate | Printable HTML (no new PDF dependency). |
| 7 | Risk score scope | Per institution overall, computed for the current academic year. |
| 8 | Dispute effect | A `STUDENT_DISPUTE` leaves the enrolment status untouched until AICTE resolves the case. |
| 9 | Demo users endpoint | `GET /auth/demo-users` is public but gated on `DEMO_MODE=true`. |
| 10 | Unknown APAAR in a verifier request | Returns `status: pending` like any other request (never leaks whether an APAAR exists before consent). |

None of these conflicts with CLAUDE.md §5; decisions 3, 9 and 10 tighten it.
