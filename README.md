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

Every demo password is `demo1234`, and the login page lists the accounts with one-click sign-in.

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

## Five-minute demo script

Run `make demo` first, then open http://localhost:3000 and follow this exactly. The numbers below
come from seed 42; `make reset` reproduces them.

### 0 · Thirty seconds of framing (no clicking)

> "AICTE receives counts today. A college can report 300 students in a programme approved for 120,
> and nothing contradicts it. This platform takes student-level records keyed on APAAR ID, so the
> arithmetic can be checked — and so the student can see what was said about them."

### 1 · A messy upload becomes a finding (90 seconds)

1. Sign in as **`kolhanpur32_admin`** (Institution → *Kolhanpur College of Engineering*).
2. **Upload data** → drop `samples/sample_1_excess_intake.xlsx`.
3. Stop on the **mapping screen**. Point out that the file's headers are `Stu. Nm`, `APAAR No.`,
   `D.O.B`, `Adm Dt` — nothing matches our field names — and the platform has proposed a mapping
   with a confidence per column. `Sr. No.` and `Remarks` are correctly ignored.
4. Click **Validate and import 63 rows**.
5. On the quality report, show the score, the rejected rows *with a fix suggestion each*, and the
   **EXCESS_INTAKE** finding that appeared.
6. Go to **Seat matrix**. B.Tech Electrical Engineering was at 82 of 120 approved seats; those 63 rows
   put it **25 seats past intake**. Read the explanation line aloud — it is the arithmetic, in
   words, including which supernumerary seats were allowed and why.

> If you want to show it twice: upload the same file again. Every row comes back as
> *already reported*, the seat count does not move, and the finding stays at 25 — not 50.

### 2 · The national view (45 seconds)

7. Switch role (top right) to **`aicte_officer1`**.
8. **National overview**: 40 institutions, roughly 15,500 students reported for 2026-27, open
   findings by severity, total excess seats, and the state-wise chart.
9. **Flag queue**: filter to `critical`. Every row has a plain-English explanation; click one to
   see the evidence behind it.

### 3 · Verification, with consent (45 seconds)

10. Switch role to **`verifier_demo`**. Enter the APAAR ID of `student_pending`
    (sign in as that student first to copy it, or use any 12 digits to show the pending state) and
    a purpose. The response is **pending** — nothing is shared.
11. Switch to **`student_pending`** → **Consent manager**. It shows who asked, why, and exactly
    what would be shared: *verified yes/no, programme, academic year*. Approve it.
12. Back as **`verifier_demo`**: the result appears, and it is only those three facts.
13. Switch to the student again and **withdraw consent**. The verifier's result disappears and any
    issued QR token stops working immediately — show it on the public **/verify** page.

### 4 · Close on integrity (30 seconds)

14. Switch role to **`admin`** → **Run the tamper test**. One row is edited in a *copy* of the
    audit log, and the chain reports exactly which row broke. The real log is untouched, and
    **Verify the chain** still passes.

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

## Privacy and security, in one page

These are product requirements, not extras (CLAUDE.md section 5), and the tests enforce them:

| Rule | How it is implemented |
|---|---|
| No raw contact details | Phone, email and guardian phone exist only as `HMAC-SHA256(HMAC_KEY, normalised_value)`. Matching happens on the hashes; nothing in the API ever returns one |
| Raw identifiers encrypted | APAAR ID, full name and DOB live only in a Fernet-encrypted `vault` table; main tables hold `apaar_hash` and masked values |
| Keyed, not salted | An APAAR ID is 12 digits, so a plain digest is brute-forceable in seconds. We use a keyed HMAC |
| Secrets from the environment | `HMAC_KEY`, `VAULT_KEY`, `JWT_SECRET`, `REGISTRY_API_KEY` come from `.env`, which is gitignored. `make keys` generates real ones |
| RBAC everywhere | Every route carries `require_role(...)`; only `/health`, `/auth/login`, `/auth/demo-users` and the public token check are open |
| Tenant isolation | For an institution user, `institution_id` comes from the JWT alone. Passing another institution's id returns 404, not 403 |
| Masked by default | `XXXX-XXXX-1234` and `R***** S.` everywhere. Full details only via `POST /aicte/reveal`, officer only, with a mandatory reason |
| Access log | Every reveal and case-file view is logged with actor, role, action, target, reason and time — and the student can read their own entries |
| Hash-chained audit log | Each row stores `prev_hash` and `hash = sha256(prev_hash + canonical_json(row))`. `make test` includes tamper, delete and re-hash attempts |
| Small-count suppression | For `aicte_viewer`, any breakdown count below 5 is returned as `"<5"` |
| Colleges never learn about each other | A cross-institution finding shown to an institution reads "Possible duplicate enrolment — contact AICTE" and names no one |
| Verifier minimalism | A verifier gets `verified`, programme and academic year. Nothing else, ever |
| Minors | Under-18 students are marked, and verification against them says *parental consent required* |
| Synthetic data | Invented institution names only, and a banner on every page |

---

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
