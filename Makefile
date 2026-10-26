# APAAR Student Data & Verification Platform (SIH26263)
# Ports: API 8000, registry 8001, web 3000

SHELL := /bin/bash
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
UVICORN := $(VENV)/bin/uvicorn
export PYTHONPATH := api:.

.PHONY: help setup keys dev dev-api dev-registry dev-web test seed reset eval eval-robust clean

help:
	@echo "make setup   - create venv, install python + node dependencies"
	@echo "make keys    - generate HMAC_KEY / VAULT_KEY / JWT_SECRET into .env"
	@echo "make dev     - run api (8000), registry (8001) and web (3000) together"
	@echo "make test    - run pytest"
	@echo "make seed    - generate synthetic data into the database"
	@echo "make reset   - delete databases and reseed from scratch"
	@echo "make eval    - score detections against datagen/ground_truth.json"
	@echo "make eval-robust - score a second, perturbed dataset the detectors were not tuned on"

setup: $(VENV)/.installed keys
	@cd web && npm install --no-fund --no-audit
	@echo ""
	@echo "Setup complete. Next: make reset && make dev"

$(VENV)/.installed: api/requirements.txt
	@test -d $(VENV) || python3 -m venv $(VENV)
	@$(PIP) install --quiet --upgrade pip
	@$(PIP) install --quiet -r api/requirements.txt
	@touch $(VENV)/.installed

keys: $(VENV)/.installed
	@$(PY) scripts/gen_keys.py

dev:
	@bash scripts/dev.sh

dev-api:
	@$(UVICORN) app.main:app --reload --port 8000

dev-registry:
	@$(UVICORN) registry.app.main:app --reload --port 8001

dev-web:
	@cd web && npm run dev

test: $(VENV)/.installed
	@$(PYTEST)

seed: $(VENV)/.installed
	@$(PY) -m datagen --seed 42

reset: $(VENV)/.installed
	@rm -f apaar.db apaar.db-wal apaar.db-shm registry.db registry.db-wal registry.db-shm
	@$(PY) -m datagen --seed 42
	@echo "Database reset and reseeded."

eval: $(VENV)/.installed
	@$(PY) -m datagen.evaluate

# A second dataset with a different seed and perturbations the detectors were never
# tuned on. Writes its own database, so it never touches the demo data.
eval-robust: $(VENV)/.installed
	@$(PY) -m datagen.robust --seed 2026
	@$(PY) -m datagen.evaluate --robust

clean:
	@rm -rf $(VENV) web/node_modules web/.next
	@find . -name __pycache__ -type d -prune -exec rm -rf {} +
