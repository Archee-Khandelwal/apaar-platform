"""Shared pytest fixtures.

Every test run gets its own throwaway SQLite database and a fixed set of test secrets,
so tests never touch the demo database and never depend on a developer's .env.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

TEST_DB = Path(tempfile.gettempdir()) / "apaar_test.db"
TEST_REGISTRY_DB = Path(tempfile.gettempdir()) / "apaar_test_registry.db"

# Must be set before app.core.config is imported anywhere.
os.environ.setdefault("HMAC_KEY", "0" * 64)
os.environ.setdefault("VAULT_KEY", "YkxZSk1nQ2pQTnBXUXJTdFV2V3hZekFCQ0RFRkdISUo=")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-for-production")
os.environ.setdefault("REGISTRY_API_KEY", "test-registry-key")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["REGISTRY_DATABASE_URL"] = f"sqlite:///{TEST_REGISTRY_DB}"
os.environ["DEMO_MODE"] = "true"
