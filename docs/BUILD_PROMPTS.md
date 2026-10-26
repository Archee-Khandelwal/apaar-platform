# Claude Code Build Prompts — SIH26263 Prototype

## How to use this file

1. Create an empty folder (e.g. `apaar-platform`), run `git init`, and put `CLAUDE.md` in the root.
2. Open Claude Code in that folder.
3. Paste the prompts below **one at a time, in order**. Don't paste several at once.
4. For each prompt: let Claude Code **plan first**, read the plan, then approve. After it finishes, try the "Check" yourself, then commit:
   `git add -A && git commit -m "Step N: <name>"`
5. If something breaks, say exactly what you saw (error text, what you clicked) and ask it to fix that before moving on.
6. Team split: Steps 1–13 are backend/data (people A, B, C). Steps 14–19 are frontend (D, E) — they can start Step 14 in parallel once Step 2 is done, using the API contract in Step 0.

---

## Step 0 — Kickoff & API contract

```
Read CLAUDE.md fully. Do not write application code yet.

1. Summarise the project back to me in 10 bullet points so I can confirm you understood it.
2. Write docs/API_CONTRACT.md: every REST endpoint we will need (grouped by router: auth, institution, aicte, student, verifier, admin, plus the registry service), with method, path, required role, request body and response JSON shape (example JSON for each). Include pagination and filter params for list endpoints.
3. Write docs/PLAN.md: the build order as a checklist matching the steps I'll give you.

Keep responses masked by default as per the privacy rules. Ask me if anything in CLAUDE.md is ambiguous.
```

**Check:** the API contract makes sense to the frontend people. Freeze it — changes later go through this file.

---

## Step 1 — Monorepo scaffold

```
Scaffold the monorepo exactly as in CLAUDE.md section 4.

- /api: FastAPI app with /health, config loaded from env (pydantic-settings), SQLAlchemy 2.0 engine/session with DATABASE_URL defaulting to sqlite:///./apaar.db, requirements.txt.
- /registry: separate FastAPI app with /health on port 8001.
- /datagen: empty package with a __main__.
- /web: Next.js App Router + TypeScript + Tailwind + shadcn/ui initialised, one placeholder page.
- .env.example with HMAC_KEY, VAULT_KEY, JWT_SECRET, DATABASE_URL, REGISTRY_URL; a script to generate secure random keys into .env.
- Makefile targets: setup (venv + pip + npm install), dev (runs api, registry and web together), test (pytest), seed (placeholder), reset (delete db + reseed).
- .gitignore (venv, node_modules, .env, *.db).
- README.md with setup steps.

Check that `make setup` and `make dev` work and all three /health endpoints respond.
```

**Check:** `make dev` → open http://localhost:3000, http://localhost:8000/health, http://localhost:8001/health.

---

## Step 2 — Data model, crypto, audit

```
Implement the core backend foundation.

1. SQLAlchemy models for every table in CLAUDE.md section 7, with sensible indexes (apaar_hash, phone_hash, guardian_phone_hash, email_hash, institution_id, academic_year).
2. app/core/crypto.py:
   - hmac_hash(value: str) -> str using HMAC-SHA256 with HMAC_KEY, after normalisation (strip spaces, lowercase emails, phone numbers normalised to last 10 digits).
   - Vault encrypt/decrypt with Fernet using VAULT_KEY.
   - mask_apaar("123456781234") -> "XXXX-XXXX-1234"; mask_name("Rahul Sharma") -> "R**** S."
3. app/core/audit.py: append-only hash-chained audit log (prev_hash, hash = sha256(prev_hash + canonical JSON)), plus verify_chain() that returns ok / first broken row.
4. app/core/access_log.py: log_access(actor, role, action, target, reason).
5. DB init on startup (create_all is fine for the prototype).
6. Pytest tests for hashing (deterministic, keyed), masking, vault round-trip, audit chain (valid chain passes, a tampered row is detected).

Follow the privacy rules in CLAUDE.md section 5 strictly.
```

**Check:** `make test` passes.

---

## Step 3 — Auth, RBAC, tenant isolation

```
Implement authentication and authorisation.

1. users table with role and optional institution_id / student_id.
2. POST /auth/login (username + password, bcrypt) returning a JWT containing user_id, role, institution_id, student_id.
3. GET /auth/demo-users (admin-free, demo only) listing demo accounts so the frontend role switcher can log in with one click. Seed one user per role, plus one institution user per institution later in seeding.
4. app/core/security.py: get_current_user dependency and require_role(*roles) dependency.
5. Tenant isolation helper: for role=institution, every query must be filtered by the JWT's institution_id. Write it as a reusable dependency/helper so routers cannot forget it.
6. Small-count suppression helper suppress_small_counts(dict, role) that turns counts < 5 into "<5" for aicte_viewer.
7. Tests: wrong role gets 403; an institution user cannot read another institution's data even if they pass a different id in the URL; suppression works.
```

**Check:** tests pass; try a 403 manually with an institution token on an AICTE route.

---

## Step 4 — Mock APAAR registry

```
Build the mock APAAR registry in /registry as a separate FastAPI service.

- Its own SQLite DB of "issued" APAAR IDs: apaar (12 digits), name, dob.
- POST /verify {apaar, name, dob, consent_token} -> {status: "match" | "mismatch" | "not_found" | "consent_required", checked_at}. Name comparison uses rapidfuzz (>= 90 similarity counts as match); DOB exact.
- POST /verify/batch for up to 500 records (the main API uses this during uploads).
- Simple API-key auth between the main API and the registry (key in env).
- Artificial 20–50 ms latency to feel realistic.
- In the main API, app/services/registry_client.py with a typed client, timeout handling and a clear "source unavailable" result if the registry is down (uploads must not crash).
- Document in README that this mock has the same shape we would use for the real APAAR/ABC API.
- Tests for match, mismatch, not_found, and registry-down behaviour.
```

**Check:** stop the registry and confirm the main API reports "source unavailable" instead of crashing.

---

## Step 5 — Synthetic data generator with fraud scenarios

```
Build the synthetic data generator in /datagen. This is critical: every detection feature is demonstrated and measured on this data.

Generate (configurable via CLI args, defaults below):
- 40 clearly FICTIONAL institutions across ~10 Indian states (invent names from made-up word combinations; never real college names). Each has 3–6 programs (B.Tech branches, MBA, MCA), a few online/ODL programs at some institutions.
- Approved intake per program per year, with supernumerary caps from api/app/rules/intake_rules.yaml.
- ~15,000 students across 2 academic years (2025-26 and 2026-27) so year-to-year progression can be checked. Faker en_IN names, realistic gender/category/nationality mix, ~2% FN/OCI with apaar_status not_applicable, some students under 18.
- Contacts stored ONLY as HMAC hashes (use the same crypto module as the API). Raw APAAR/name/DOB go to the vault table.
- Every issued APAAR is also inserted into the mock registry DB.

Inject these labelled scenarios and write datagen/ground_truth.json listing every injected case (type, institution, students involved):
A. EXCESS_INTAKE: 3 institutions over intake after valid supernumerary seats are excluded (one by just 3 seats).
B. GHOST_CLUSTER: 2 institutions, each with a cluster of 25–35 students sharing 2–3 guardian phone numbers.
C. CROSS_INSTITUTION_DUPLICATE (fraud): 15 students with the same APAAR in two full-time regular programs in the same year.
D. POSSIBLE_DUAL_DEGREE (legit): 10 students with one regular + one online enrolment.
E. INVALID_APAAR / APAAR_NOT_FOUND / APAAR_MISMATCH: ~1% of records.
F. LATE_ADMISSION: ~40 admissions after the cutoff at 2 institutions.
G. SEQUENTIAL_APAAR: one institution with a run of 20 near-consecutive APAAR IDs.
H. LAST_MINUTE_BULK: one institution with 60% of its records created in the final 6 hours before the deadline.
I. PHANTOM_PROGRESSION: year-2 regular students with no year-1 record (not lateral entry), plus some students who disappear without a dropout status.
J. IDENTITY_DUPLICATE: 8 people with two different APAAR IDs (same name + DOB + guardian phone).
Also: one "clean" model institution with no issues (for the compliance certificate demo).

Also create /samples with 3 messy Excel files for live demo uploads: weird column headers ("Stu. Nm", "APAAR No.", "D.O.B", "Adm Dt"), mixed date formats, some blank rows and errors. One of them should trigger scenario A when uploaded.

Wire `make seed` and `make reset` to this generator. Make it deterministic with a --seed argument.
```

**Check:** `make reset` runs; open `ground_truth.json` and spot-check counts.

---

## Step 6 — Upload pipeline & validation

```
Implement the institution upload pipeline (app/services/upload.py, validation.py) and routes in routers/institution.py.

1. POST /institution/uploads (multipart Excel/CSV). Parse with pandas/openpyxl. Skip fully blank rows.
2. Column mapping: map incoming headers to canonical fields using rapidfuzz plus a synonym dictionary (e.g. "stu nm", "student name", "name of student" -> name). Return the proposed mapping with confidence per column; the upload stays in "pending_mapping" state.
3. POST /institution/uploads/{id}/confirm-mapping accepts the (possibly edited) mapping and runs validation.
4. Row validation: required fields, APAAR format, apaar_status rules (not_applicable only for FN/OCI), date parsing in multiple formats, DOB plausibility, admission date inside the configured window (else LATE_ADMISSION flag), duplicates within the upload, batch registry check (match/mismatch/not_found/source unavailable).
5. Valid rows are stored (hashes + vault, never raw contacts); invalid rows are reported, not stored.
6. Quality report: score 0–100, counts, and per-row errors/warnings with a human-readable fix suggestion each.
7. GET /institution/uploads and /institution/uploads/{id}.
8. GET /institution/template returns a downloadable CSV template.
9. Every upload writes to the audit log.
10. Tests using the files in /samples, including an all-garbage file that must not crash.

Keep it synchronous (no Celery) but make sure a 5,000-row file finishes in a reasonable time — batch DB writes and registry calls.
```

**Check:** upload a file from `/samples` via the interactive API docs at http://localhost:8000/docs.

---

## Step 7 — Intake compliance engine

```
Implement the intake compliance engine (app/services/intake.py) driven by api/app/rules/intake_rules.yaml.

1. intake_rules.yaml: versioned rule set (e.g. rule_set: APH_2026_27_v1) listing which admission types count within intake and the cap for each supernumerary category (as % of intake), lateral entry rules (year 2, cap + vacant year-1 seats). Every number gets a "# VERIFY against AICTE Approval Process Handbook 2026-27" comment.
2. compute_seat_matrix(program, year) returns: approved intake, regular admitted, each supernumerary bucket (admitted vs cap), valid supernumerary, excess, and a step-by-step explanation string, e.g. "312 enrolled vs 300 intake -> 9 valid supernumerary -> 3 excess".
3. Run after every upload confirmation and after seeding; create/update EXCESS_INTAKE flags with evidence = the full seat matrix.
4. GET /institution/seat-matrix (own institution only) and GET /aicte/institutions/{id}/seat-matrix.
5. Unit tests with hand-calculated cases: exactly at intake (no flag), over by regular seats, over only because a supernumerary bucket exceeds its cap, lateral entry not counted in year 1.
6. Confirm scenario A from ground_truth.json is detected exactly.
```

---

## Step 8 — Duplicate & identity detection

```
Implement app/services/duplicates.py.

1. CROSS_INSTITUTION_DUPLICATE: same apaar_hash with active enrolments at 2+ institutions in the same academic year.
   - If at least one program has mode=online -> POSSIBLE_DUAL_DEGREE (severity low, status informational).
   - If both are full-time regular -> CROSS_INSTITUTION_DUPLICATE (severity high).
2. IDENTITY_DUPLICATE: different apaar_hash but same normalised name (decrypted only inside the service, never returned), same DOB and same guardian_phone_hash.
3. Flags for colleges must never reveal the other institution (CLAUDE.md rule 10). The AICTE officer view shows both sides.
4. Evidence JSON: masked APAARs, institution ids, programs, years, and the reason for the classification.
5. Tests, plus a check that scenarios C, D and J from ground_truth.json are classified correctly (D must NOT be flagged as fraud).
```

---

## Step 9 — Ghost-student graph detector

```
Implement app/services/graph.py — this is our headline feature.

1. Build a networkx graph: student nodes and attribute nodes (guardian_phone_hash, phone_hash, email_hash). Edges connect a student to each of their attribute values.
2. Find connected components. Flag GHOST_CLUSTER when a component has an abnormal number of students linked through shared attributes (configurable thresholds, e.g. >= 8 students sharing <= 3 guardian contacts, or one contact shared across students at different institutions). Ignore normal siblings (2–3 students sharing a guardian).
3. Score each cluster (size, attributes-to-students ratio, number of institutions involved) and make severity depend on the score.
4. GET /aicte/graph/clusters: list of clusters with summary (masked), score, institutions involved.
5. GET /aicte/graph/clusters/{id}: Cytoscape-ready JSON {nodes:[{data:{id,label,type,institution}}], edges:[{data:{source,target,attribute_type}}]}. Labels are masked; attribute nodes are shown as "Guardian contact #1" etc., never a hash or number.
6. Every cluster view writes to the access log.
7. Tests, plus confirm both scenario-B clusters are found and no false positives come from normal sibling pairs.
```

---

## Step 10 — Heuristic detectors

```
Implement app/services/heuristics.py with these detectors, each producing explainable flags with evidence:

1. SEQUENTIAL_APAAR: within one institution and year, sort raw APAARs (inside the service only) and detect runs of >= 10 IDs where consecutive gaps are tiny. Evidence: run length, masked first/last IDs.
2. LATE_ADMISSION: already raised in validation; here aggregate per institution (count, % of admissions).
3. LAST_MINUTE_BULK: share of an institution's records created within N hours before the reporting deadline exceeds a threshold.
4. PHANTOM_PROGRESSION: year-2 regular students with no year-1 enrolment (excluding lateral entry); students present in year 1 who vanish in year 2 with no cancelled/migrated/dropped status.
5. A single run_all_detectors() entry point that the admin reseed and upload confirmation call, which is idempotent (re-running doesn't duplicate flags).
6. Tests, plus confirm scenarios F, G, H, I are detected.
```

---

## Step 11 — Risk score, anomaly model, inspection shortlist, evaluation

```
Implement app/services/risk.py and datagen/evaluate.py.

1. Statistical anomaly per institution-year using scikit-learn IsolationForest on features: fill ratio, % missing/invalid APAAR, % late admissions, year-on-year growth, distance of category and gender mix from the state average, % records created in the last 6 hours. Raise STATISTICAL_ANOMALY for the most anomalous, with the top contributing features (compare each feature to the state median) as explanation.
2. Risk score 0–100 per institution: weighted sum of open flags by type and severity plus the anomaly score. Weights in a config dict. ALWAYS return the top 3 reasons in plain English.
3. GET /aicte/risk (leaderboard), GET /aicte/inspection-shortlist?limit=10 ("recommended for physical inspection" with reasons).
4. datagen/evaluate.py: compares all flags against ground_truth.json and prints precision, recall and F1 per scenario type, plus a summary table. Save results to docs/EVALUATION.md (we put these numbers on a slide). Be honest — don't tune on the evaluation in a way that hides real misses; report them.
5. Make `make eval` run it.
```

**Check:** `make reset && make eval` — note the numbers for the pitch.

---

## Step 12 — Flags, cases, reveal, AICTE APIs

```
Implement the AICTE-side APIs in routers/aicte.py.

1. GET /aicte/overview: national KPIs (institutions reporting, students, open flags by severity, total excess seats), plus state-wise breakdown. Apply small-count suppression for aicte_viewer.
2. GET /aicte/institutions (search, filter by state, risk), GET /aicte/institutions/{id} (profile, seat matrix, flags, risk reasons).
3. GET /aicte/flags with filters (type, severity, status, state, institution) and pagination; PATCH /aicte/flags/{id} for status changes, assignment to an officer and notes (case management). Every change goes to the audit log.
4. POST /aicte/reveal {student_id, reason} — aicte_officer only, reason mandatory (min 10 chars); returns decrypted details and writes to access log. Everything else stays masked.
5. GET /aicte/non-reporting: institutions with no upload for the current year; POST /aicte/remind/{institution_id} (mocked notification, logged).
6. GET /aicte/reports/trends: state/branch/category/gender trends and year-on-year enrolment; CSV export.
7. Institution side: GET /institution/flags (own only, with rule 10 wording), PATCH /institution/enrolments/{id}/status (cancel/migrate/drop with reason, versioned), GET /institution/compliance-certificate (only if no open high/critical flags; returns a simple PDF or HTML certificate).
8. Tests for RBAC on every new route, reveal requiring a reason, and suppression.
```

---

## Step 13 — Student & verifier APIs, consent, tokens

```
Implement routers/student.py and routers/verifier.py with app/services/consent.py and tokens.py.

Student:
1. GET /student/me: own enrolments (what the college reported), masked appropriately.
2. POST /student/enrolments/{id}/confirm and /dispute {reason}. A dispute creates a STUDENT_DISPUTE flag (critical) visible to AICTE and the institution.
3. POST /student/corrections {field, correct_value, note} -> goes to the institution's flag inbox.
4. GET /student/access-log: the access log filtered to this student ("who accessed my data").
5. GET /student/consents, POST /student/consents/{id}/approve | deny | revoke.
6. GET /student/id-card: masked APAAR + student ID + QR containing a signed token.

Verifier:
7. POST /verifier/requests {apaar, purpose} (purpose required, from a fixed list) -> creates a pending consent for the student (mock OTP/notification). Minors are marked "parental consent required".
8. GET /verifier/requests/{id}: pending | approved | denied | expired. When approved, return the MINIMAL response only: verified true/false, program, year.
9. Tokens: HMAC-signed, with expiry (default 15 minutes) and the consent id. GET /verify/token/{token} validates signature + expiry + consent not revoked; returns genuine / expired / revoked / invalid.
10. Everything is written to the audit log and access log.
11. Tests: verifier gets nothing before approval; denied and expired paths; revoked consent invalidates the token; tampered token fails.
```

**Backend milestone:** run `make reset && make test && make eval`. Everything should pass before heavy frontend integration.

---

## Step 14 — Frontend foundation

```
Build the frontend foundation in /web.

1. Typed API client in web/lib/api.ts generated from docs/API_CONTRACT.md, using fetch + TanStack Query, with the JWT stored in memory (and sessionStorage wrapped in try/catch).
2. Login page plus a "Demo role switcher" (top bar dropdown) that logs in as any demo user from /auth/demo-users with one click.
3. App shell: sidebar navigation that changes per role (Institution, AICTE, Student, Verifier, Admin), top bar with role badge, and a permanent banner "Prototype — all data is synthetic".
4. Shared components: MaskedApaar, MaskedName, SeverityBadge (low=slate, medium=amber, high=orange, critical=red), StatCard, DataTable (sorting, filtering, pagination), EmptyState, LoadingSkeleton, ExplanationPanel (renders a flag's explanation + evidence nicely), RevealButton (opens a modal requiring a reason).
5. Clean, professional government-dashboard look: neutral palette with one accent colour, good spacing, responsive down to tablet width.
6. Route guards so a role can't open another role's pages.
```

---

## Step 15 — Institution portal

```
Build the institution portal pages.

1. Dashboard: data quality score trend, open flags count, seat matrix summary, upload CTA.
2. Upload flow: drag-and-drop -> column mapping screen (show each incoming header, the proposed field, confidence, and a dropdown to change it) -> confirm -> quality report card (score dial, error/warning lists with fix suggestions, downloadable error CSV).
3. Seat matrix page: per program, a stacked bar of intake vs regular vs each supernumerary bucket vs excess, with the plain-English explanation underneath.
4. Flag inbox: own flags only (duplicate wording per CLAUDE.md rule 10), with a "mark resolved / correct & resubmit" action.
5. Students list (masked) with status update action (cancel/migrate/drop with reason).
6. Upload history and compliance certificate download (button disabled with a reason if not eligible).
7. Template download.
```

---

## Step 16 — AICTE dashboard

```
Build the AICTE portal pages.

1. National overview: KPI StatCards, state-wise bar chart (Recharts), flags by type and severity, total excess seats. For aicte_viewer, show "<5" values gracefully.
2. Flag queue: DataTable with filters (type, severity, status, state), ExplanationPanel drawer on row click, actions (review, escalate, dismiss, assign, add note).
3. Institution drill-down page: profile, risk score gauge with top 3 reasons, seat matrix, flags, timeline of uploads.
4. Risk leaderboard and an "Inspection shortlist" page (top 10 with reasons, exportable).
5. Non-reporting institutions page with a "send reminder" action.
6. Reports page: trends charts + CSV export.
7. Reveal: on any student row, RevealButton (officer only) -> reason modal -> shows details, and a toast "This access has been logged".
```

---

## Step 17 — Ghost-cluster graph view (headline screen)

```
Build the graph investigation view — this is the most important screen in the demo, make it impressive.

1. Clusters list page: cards showing cluster score, number of students, number of shared contacts, institutions involved, severity.
2. Cluster detail: Cytoscape.js graph (react-cytoscapejs) from /aicte/graph/clusters/{id}.
   - Student nodes as circles coloured by institution, shared-contact nodes as larger diamonds in the accent colour, edges labelled by attribute type.
   - Use a force-directed layout (cose) with a smooth animation on load.
   - Hover tooltips with masked info; clicking a student opens a side panel (masked, with RevealButton for officers).
   - A legend and a plain-English summary at the top, e.g. "32 students at Institute X share only 3 guardian contacts — typical families share 1 contact per 1–3 students."
3. A "Compare with a normal cluster" toggle that shows a small, healthy sibling cluster side by side.
4. Performs smoothly with ~100 nodes.
```

---

## Step 18 — Student & verifier portals

```
Build the student and verifier pages.

Student:
1. "Was this you?" alert card at the top of the student dashboard for unconfirmed enrolments: "You have been reported as enrolled in B.Tech CSE at <institution>, 2026-27. Is this correct?" -> Confirm / Dispute (reason). After dispute, show "AICTE has been notified" and the new case status.
2. My records page, correction request form.
3. "Who accessed my data" timeline (actor role, purpose/reason, time).
4. Consent manager: pending requests (verifier name, purpose, what will be shared) -> approve/deny; active consents -> revoke. Minor students see "parental consent required".
5. Digital ID card with QR (rendered from /student/id-card).

Verifier:
6. Request verification form (APAAR + purpose), status page that polls until approved/denied/expired, minimal result card.
7. Public "Verify a token/QR" page: paste a token or scan with the device camera; shows Genuine / Expired / Revoked / Invalid in big, clear states.

Mobile-friendly — students will use phones.
```

---

## Step 19 — Admin & demo tooling

```
Build the admin tools and demo polish.

1. Admin page: "Reset & reseed demo data" button (calls POST /admin/reseed), "Load scenario" buttons (re-inject a specific scenario A–J live), "Verify audit chain" button showing ok or the first broken row, a "tamper test" that modifies one audit row in a copy and shows detection.
2. POST /admin/reseed and /admin/load-scenario/{name}, admin role only.
3. Seed so that the demo story works in order: messy upload -> excess intake -> ghost cluster -> student dispute -> duplicate vs dual degree -> verifier consent flow.
4. Update README.md: setup, `make` commands, demo accounts, and a 5-minute demo walkthrough script with exact clicks.
5. Make sure `make reset && make dev` gives a clean, ready-to-demo state in one command.
```

---

## Step 20 — Final QA & hardening

```
Do a full end-to-end QA pass. Do not add new features.

1. Run `make reset && make test && make eval` and fix any failures.
2. Security review against CLAUDE.md section 5: search the codebase for any place raw phone/email/APAAR/name could be returned or logged, any route missing require_role, any institution query not tenant-scoped, any secret hardcoded. Fix and list everything you found.
3. Walk through the README demo script yourself via the API and check each step's data actually appears.
4. Check edge cases: empty upload, 5,000-row upload timing, registry down, expired token, revoked consent, a role trying another role's page.
5. Frontend: no console errors, loading and empty states everywhere, works at 1280px and tablet width.
6. Give me a short report: what you fixed, known limitations, and anything I should not show in the demo.
```

---

## Useful follow-up prompts

- **When something breaks:** `This error happens when I <action>: <paste error>. Find the root cause, fix it, add a test so it can't regress, and run make test.`
- **Before a mentor round:** `Give me a 2-minute walkthrough of what currently works end-to-end and which parts are still mocked or incomplete.`
- **For the PPT:** `Generate a clean architecture diagram (Mermaid) of the current system and a one-paragraph explanation of each component, for a judge audience.`
- **For judge Q&A:** `Read the codebase and list the 10 toughest questions a technical SIH judge would ask about this system, with honest answers based on what we actually built.`
- **If behind schedule:** `We have N hours left. Based on docs/PLAN.md, tell me what to cut and what to finish so the demo story still works end to end.`

## 24-hour hackathon version

If you're doing this in the 24-hour format, run Steps 0–11 for backend and 14–17 for frontend in parallel, then 13 only if time allows (otherwise skip to 18 with just the student dispute page), then 19–20. In Step 5, reduce to 20 institutions and ~6,000 students, and drop scenarios H and I if short on time.