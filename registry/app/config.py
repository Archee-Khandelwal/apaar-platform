"""Mock APAAR registry configuration."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class RegistrySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(REPO_ROOT / ".env"), extra="ignore")

    registry_database_url: str = "sqlite:///./registry.db"
    registry_api_key: str = "dev-registry-key"
    registry_latency_min_ms: int = 20
    registry_latency_max_ms: int = 50
    name_match_threshold: int = 90
    version: str = "0.1.0"


@lru_cache
def get_registry_settings() -> RegistrySettings:
    return RegistrySettings()


registry_settings = get_registry_settings()
