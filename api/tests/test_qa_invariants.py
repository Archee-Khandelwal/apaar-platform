"""Step 20: standing QA invariants, so the Step-20 findings cannot silently regress."""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

REPO = Path(__file__).resolve().parents[2]

# Documented public routes (CLAUDE.md section 5 rule 4).
PUBLIC_PATHS = {
    "/health",
    "/auth/login",
    "/auth/demo-users",
    "/verify/token/{token}",
    "/verify/document/{token}",
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
}


def test_every_route_is_guarded_or_documented_public() -> None:
    """No route may exist without an auth dependency."""
    unguarded: list[str] = []
    checked = 0
    for route in app.routes:
        path = getattr(route, "path", "")
        endpoint = getattr(route, "endpoint", None)
        if path in PUBLIC_PATHS or endpoint is None:
            continue
        checked += 1
        source = inspect.getsource(endpoint)
        if not any(
            marker in source
            for marker in ("require_role", "require_institution_scope", "get_current_user")
        ):
            unguarded.append(f"{sorted(route.methods or [])} {path}")
    assert checked > 40, "the route scan found suspiciously few routes"
    assert unguarded == [], f"routes without an auth dependency: {unguarded}"


def test_no_response_schema_exposes_a_hash_or_a_raw_contact() -> None:
    """A hash must never leave the API (12 digits is brute-forceable from one)."""
    offenders: list[str] = []
    for path in (REPO / "api" / "app" / "schemas").glob("*.py"):
        text = path.read_text()
        for match in re.finditer(r"^\s{4}(\w*(?:hash|phone|email)\w*)\s*:", text, re.M):
            field = match.group(1)
            if field in ("email", "phone", "guardian_phone"):
                # Allowed only as an INPUT field on the upload template / correction form.
                continue
            offenders.append(f"{path.name}:{field}")
    assert offenders == [], f"schema fields that could leak a hash or contact: {offenders}"


def test_openapi_documents_the_same_public_routes() -> None:
    """A route becoming public by accident should fail here."""
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
    documented = set(schema["paths"])
    # Every documented path either needs a security dependency at call time or is public.
    assert "/auth/login" in documented
    assert "/verify/token/{token}" in documented
    for path in ("/aicte/reveal", "/student/me", "/admin/reseed"):
        assert path in documented, f"{path} is missing from the API schema"


def test_claude_md_privacy_rules_have_a_home_in_the_code() -> None:
    """Each non-negotiable rule should be traceable to a module, not just a promise."""
    expectations = {
        "api/app/core/crypto.py": ["hmac_hash", "vault_encrypt", "mask_apaar", "mask_name"],
        "api/app/core/audit.py": ["prev_hash", "verify_chain", "canonical_json"],
        "api/app/core/access_log.py": ["log_access"],
        "api/app/core/security.py": ["require_role", "require_institution_scope", "suppress_small_counts"],
        "api/app/services/flags.py": ["sanitise_for_institution", "CROSS_INSTITUTION_NOTICE"],
        "api/app/services/tokens.py": ["issue_token", "verify_token"],
    }
    for relative, symbols in expectations.items():
        text = (REPO / relative).read_text()
        for symbol in symbols:
            assert symbol in text, f"{relative} no longer defines {symbol}"


def test_the_rule_files_still_carry_their_verify_markers() -> None:
    """Every cap and date must stay marked as unverified against the real handbook."""
    for name in ("intake_rules.yaml", "reporting_calendar.yaml", "document_checklist.yaml"):
        text = (REPO / "api" / "app" / "rules" / name).read_text()
        assert "VERIFY" in text, f"{name} lost its VERIFY markers"
        assert text.count("VERIFY") >= 5, f"{name} has suspiciously few VERIFY markers"


def test_readme_documents_the_demo_and_its_limits() -> None:
    text = (REPO / "README.md").read_text()
    for marker in (
        "make demo",
        "Demo script",
        "Demo accounts",
        "Known limitations",
        "all data is synthetic",
    ):
        assert marker in text, f"README is missing '{marker}'"


def test_env_example_lists_every_secret_and_commits_none() -> None:
    text = (REPO / ".env.example").read_text()
    for key in ("HMAC_KEY", "VAULT_KEY", "JWT_SECRET", "REGISTRY_API_KEY"):
        assert key in text
        line = next(row for row in text.splitlines() if row.startswith(key))
        assert "replace-me" in line, f"{key} in .env.example must be a placeholder"
    gitignore = (REPO / ".gitignore").read_text()
    assert ".env" in gitignore
