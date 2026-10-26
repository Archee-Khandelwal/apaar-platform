#!/usr/bin/env bash
# Run the API (8000), the mock registry (8001) and the web app (3000) together.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
VENV="$ROOT/.venv"
export PYTHONPATH="$ROOT/api:$ROOT"

if [[ ! -x "$VENV/bin/uvicorn" ]]; then
  echo "No virtualenv found. Run 'make setup' first." >&2
  exit 1
fi
if [[ ! -f "$ROOT/.env" ]]; then
  echo "No .env found. Run 'make keys' first." >&2
  exit 1
fi

pids=()
cleanup() {
  echo ""
  echo "Stopping services..."
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting mock APAAR registry on http://localhost:8001 ..."
"$VENV/bin/uvicorn" registry.app.main:app --port 8001 --reload --log-level warning &
pids+=($!)

echo "Starting API on http://localhost:8000 (docs at /docs) ..."
"$VENV/bin/uvicorn" app.main:app --port 8000 --reload --log-level warning &
pids+=($!)

if [[ -d "$ROOT/web/node_modules" ]]; then
  echo "Starting web on http://localhost:3000 ..."
  (cd "$ROOT/web" && npm run dev) &
  pids+=($!)
else
  echo "web/node_modules missing — skipping web. Run 'make setup' to install it." >&2
fi

echo ""
echo "All services starting. Press Ctrl+C to stop."
wait
