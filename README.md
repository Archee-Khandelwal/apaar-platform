# APAAR Student Data & Verification Platform

**Smart India Hackathon 2026 · Problem statement SIH26263 (AICTE)**
"Development of an APAAR ID-Based Student Data Management and Verification Platform for AICTE-Approved Institutions."

> **Prototype — all data is synthetic.** Institution names, students, APAAR IDs and the APAAR registry
> itself are invented. There is no connection to any real APAAR / ABC system.

AICTE today largely receives *counts* of enrolled students. This platform takes **student-level**
records keyed on the 12-digit APAAR ID, validates them against a registry, detects fraud with
explainable rules and graph analysis, gives AICTE a risk-ranked national view, lets students see and
dispute what was reported about them, and lets employers verify a student **only with the student's
consent**.

## Quick start

```bash
make setup      # venv + python deps + .env secrets + npm install
make reset      # create the database and seed synthetic data
make dev        # api :8000, mock registry :8001, web :3000
```

Then open:

| What | URL |
|---|---|
| Web app | http://localhost:3000 |
| API docs (interactive) | http://localhost:8000/docs |
| API health | http://localhost:8000/health |
| Mock registry health | http://localhost:8001/health |

## Make targets

| Target | What it does |
|---|---|
| `make setup` | Creates `.venv`, installs `api/requirements.txt`, generates `.env` secrets, installs `web` npm packages |
| `make keys` | (Re)generates `HMAC_KEY`, `VAULT_KEY`, `JWT_SECRET`, `REGISTRY_API_KEY` into `.env` |
| `make dev` | Runs all three services together (Ctrl+C stops them all) |
| `make dev-api` / `make dev-registry` / `make dev-web` | Run one service on its own |
| `make test` | pytest |
| `make seed` | Generate synthetic data |
| `make reset` | Delete the databases and reseed from scratch |
| `make eval` | Score detections against `datagen/ground_truth.json` |

## Repository layout

```
/api        FastAPI backend (core, models, schemas, routers, services, rules)
/registry   Mock APAAR registry — a separate FastAPI service on port 8001
/datagen    Synthetic data generator, ground_truth.json, evaluate.py
/web        Next.js (App Router) + TypeScript + Tailwind frontend
/samples    Deliberately messy Excel/CSV files for live demo uploads
/docs       API_CONTRACT.md (frozen), PLAN.md (build checklist), EVALUATION.md
/scripts    gen_keys.py, dev.sh
```

## Secrets

`HMAC_KEY`, `VAULT_KEY`, `JWT_SECRET` and `REGISTRY_API_KEY` are read from the environment (or `.env`)
and are never committed — `.env` is gitignored and `.env.example` holds placeholders only.
Run `make keys` to generate real ones. The API logs a warning at startup if any are missing.

Why this matters: contact details are stored only as `HMAC-SHA256(HMAC_KEY, normalised_value)`, and raw
APAAR ID / name / DOB live only in a Fernet-encrypted vault table. An APAAR ID is 12 digits, so a plain
salted hash would be brute-forceable in seconds — a keyed HMAC is not.

## Mock APAAR registry

There is no public APAAR/ABC verification API, so `/registry` is a small separate FastAPI service with
the **same shape** we would use against the real thing: `POST /verify` and `POST /verify/batch`,
API-key auth, and `match | mismatch | not_found | consent_required` statuses. Swapping in the real
registry means replacing one client module (`api/app/services/registry_client.py`) — nothing else.

## Documentation

- `docs/API_CONTRACT.md` — every endpoint, role, request/response example (frozen; changes go through this file)
- `docs/PLAN.md` — the build checklist, step by step, with the recorded Step-0 decisions
- `docs/EVALUATION.md` — precision / recall / F1 of every detector against the generated ground truth
- `CLAUDE.md` — project context, privacy rules and domain rules
