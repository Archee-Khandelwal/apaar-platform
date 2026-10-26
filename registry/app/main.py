"""Mock APAAR registry (port 8001).

Production-shaped stand-in for the real APAAR / ABC registry API. Same request and
response shapes we would use against the real service — see README.
"""
from __future__ import annotations

from fastapi import FastAPI

from registry.app.config import registry_settings

app = FastAPI(
    title="Mock APAAR Registry",
    version=registry_settings.version,
    description="Synthetic APAAR registry for the SIH26263 prototype. All data is synthetic.",
)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "registry", "version": registry_settings.version}
