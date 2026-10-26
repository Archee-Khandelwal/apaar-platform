"""Application configuration, loaded from environment / .env (CLAUDE.md section 5 rule 3)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = API_ROOT / "app" / "rules"
# Uploaded files are kept between the mapping and confirm steps. Gitignored.
UPLOAD_DIR = REPO_ROOT / "var" / "uploads"


class Settings(BaseSettings):
    """Every secret comes from the environment. No key is ever hardcoded."""

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Secrets — intentionally no defaults for the three that protect student data.
    hmac_key: str = ""
    vault_key: str = ""
    jwt_secret: str = ""
    registry_api_key: str = "dev-registry-key"

    # Storage
    database_url: str = "sqlite:///./apaar.db"
    registry_database_url: str = "sqlite:///./registry.db"

    # Services
    registry_url: str = "http://localhost:8001"
    api_url: str = "http://localhost:8000"
    web_url: str = "http://localhost:3000"

    # Behaviour
    demo_mode: bool = True
    current_academic_year: str = "2026-27"
    jwt_expire_minutes: int = 480
    consent_request_ttl_hours: int = 72
    verify_token_ttl_minutes: int = 15
    registry_timeout_seconds: float = 3.0
    bcrypt_rounds: int = 12  # lowered in tests for speed
    max_upload_mb: int = 10
    log_level: str = "info"

    app_name: str = "APAAR Student Data & Verification Platform"
    version: str = "0.1.0"

    @property
    def missing_secrets(self) -> list[str]:
        return [
            name
            for name, value in (
                ("HMAC_KEY", self.hmac_key),
                ("VAULT_KEY", self.vault_key),
                ("JWT_SECRET", self.jwt_secret),
            )
            if not value or value.startswith("replace-me")
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
