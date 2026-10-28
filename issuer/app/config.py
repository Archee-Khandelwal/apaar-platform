"""Mock Issuer & DigiLocker registry configuration."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class IssuerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(REPO_ROOT / ".env"), extra="ignore")

    issuer_database_url: str = "sqlite:///./issuer.db"
    issuer_api_key: str = "dev-issuer-key"
    issuer_latency_min_ms: int = 20
    issuer_latency_max_ms: int = 60
    name_match_threshold: int = 90
    version: str = "0.1.0"


@lru_cache
def get_issuer_settings() -> IssuerSettings:
    return IssuerSettings()


issuer_settings = get_issuer_settings()
