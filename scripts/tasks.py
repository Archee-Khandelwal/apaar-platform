"""Cross-platform task runner: the Makefile's targets for machines without ``make``.

    python scripts/tasks.py setup        # venv, Python + web dependencies, .env secrets
    python scripts/tasks.py reset        # wipe and reseed (works while the API is running)
    python scripts/tasks.py dev          # api 8000, registries 8001/8002, web 3000
    python scripts/tasks.py test         # pytest
    python scripts/tasks.py eval         # score detectors and documents -> docs/EVALUATION.md
    python scripts/tasks.py eval-robust  # the perturbed dataset -> docs/EVALUATION_ROBUST.md
    python scripts/tasks.py screenshots  # needs `dev` running in another terminal

Run it with any Python 3.11+; it uses the project's ``.venv`` for everything else.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
WINDOWS = os.name == "nt"
PYTHON = VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")
NPM = "npm.cmd" if WINDOWS else "npm"
DATABASES = ("apaar.db", "registry.db", "issuer.db")


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "api"), str(ROOT)])
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _run(*args: str | Path, cwd: Path = ROOT) -> int:
    print("$", " ".join(str(arg) for arg in args), flush=True)
    return subprocess.call([str(arg) for arg in args], cwd=cwd, env=_env())


def _need_venv() -> None:
    if not PYTHON.exists():
        sys.exit("No virtualenv found. Run: python scripts/tasks.py setup")


def setup() -> int:
    if not PYTHON.exists():
        _run(sys.executable, "-m", "venv", VENV)
    _run(PYTHON, "-m", "pip", "install", "--quiet", "--upgrade", "pip")
    if _run(PYTHON, "-m", "pip", "install", "--quiet", "-r", ROOT / "api" / "requirements.txt"):
        return 1
    _run(PYTHON, ROOT / "scripts" / "gen_keys.py")
    if shutil.which(NPM):
        _run(NPM, "install", "--no-fund", "--no-audit", cwd=ROOT / "web")
    else:
        print("npm not found — install Node.js 20+ to run the web app.")
    print("\nSetup complete. Next: python scripts/tasks.py reset, then python scripts/tasks.py dev")
    return 0


def keys() -> int:
    _need_venv()
    return _run(PYTHON, ROOT / "scripts" / "gen_keys.py")


def reset() -> int:
    """Delete the databases if nothing holds them; otherwise drop every table in place."""
    _need_venv()
    locked = False
    for name in DATABASES:
        for suffix in ("", "-wal", "-shm"):
            path = ROOT / f"{name}{suffix}"
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                locked = True
    args = ["-m", "datagen", "--seed", "42"]
    if locked:
        print("A database is open (is the API running?) — dropping its tables in place instead.")
        args.append("--fresh")
    code = _run(PYTHON, *args)
    if code == 0:
        print("Database reset and reseeded. Demo passwords: demo_credentials.csv")
    return code


def seed() -> int:
    _need_venv()
    return _run(PYTHON, "-m", "datagen", "--seed", "42")


def test() -> int:
    _need_venv()
    return _run(PYTHON, "-m", "pytest", *sys.argv[2:])


def eval_() -> int:
    _need_venv()
    return _run(PYTHON, "-m", "datagen.evaluate")


def eval_robust() -> int:
    _need_venv()
    return _run(PYTHON, "-m", "datagen.robust", "--seed", "2026") or _run(PYTHON, "-m", "datagen.evaluate", "--robust")


def screenshots() -> int:
    return _run(NPM, "run", "screenshots", "--", *sys.argv[2:], cwd=ROOT / "web")


def dev() -> int:
    """All four services in one terminal. Ctrl+C stops them all."""
    _need_venv()
    if not (ROOT / ".env").exists():
        sys.exit("No .env found. Run: python scripts/tasks.py keys")
    services = [
        ("APAAR registry  http://localhost:8001", [PYTHON, "-m", "uvicorn", "registry.app.main:app", "--port", "8001", "--log-level", "warning"], ROOT),
        ("Issuer registry http://localhost:8002", [PYTHON, "-m", "uvicorn", "issuer.app.main:app", "--port", "8002", "--log-level", "warning"], ROOT),
        ("API             http://localhost:8000/docs", [PYTHON, "-m", "uvicorn", "app.main:app", "--port", "8000", "--reload", "--log-level", "warning"], ROOT),
    ]
    if (ROOT / "web" / "node_modules").exists():
        services.append(("Web             http://localhost:3000", [NPM, "run", "dev"], ROOT / "web"))
    else:
        print("web/node_modules missing — skipping the web app. Run setup first.")

    processes: list[subprocess.Popen] = []
    try:
        for label, command, cwd in services:
            print(f"Starting {label}", flush=True)
            processes.append(subprocess.Popen([str(part) for part in command], cwd=cwd, env=_env()))
        print("\nAll services starting. Press Ctrl+C to stop.\n", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        print("A service stopped; shutting the others down.")
        return 1
    except KeyboardInterrupt:
        print("\nStopping services...")
        return 0
    finally:
        for process in processes:
            if process.poll() is None:
                if WINDOWS:
                    subprocess.call(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    process.send_signal(signal.SIGINT)
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                process.kill()


TASKS = {
    "setup": setup,
    "keys": keys,
    "reset": reset,
    "seed": seed,
    "dev": dev,
    "test": test,
    "eval": eval_,
    "eval-robust": eval_robust,
    "screenshots": screenshots,
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in TASKS:
        print(__doc__)
        return 2
    return TASKS[sys.argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main())
