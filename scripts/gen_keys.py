"""Generate strong secrets into .env (never overwrites an existing .env unless --force).

Usage: python scripts/gen_keys.py [--force]
"""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"


def main() -> int:
    force = "--force" in sys.argv
    if ENV.exists() and not force:
        print(f".env already exists at {ENV} — leaving it alone (use --force to regenerate).")
        return 0

    generated = {
        "HMAC_KEY": secrets.token_hex(32),
        "VAULT_KEY": Fernet.generate_key().decode(),
        "JWT_SECRET": secrets.token_hex(32),
        "REGISTRY_API_KEY": secrets.token_hex(16),
    }

    lines: list[str] = []
    for line in EXAMPLE.read_text().splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line and not line.startswith("#") else None
        if key in generated:
            lines.append(f"{key}={generated[key]}")
        else:
            lines.append(line)
    ENV.write_text("\n".join(lines) + "\n")
    print(f"Wrote {ENV} with freshly generated HMAC_KEY, VAULT_KEY, JWT_SECRET, REGISTRY_API_KEY.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
