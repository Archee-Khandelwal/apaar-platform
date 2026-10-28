"""FastAPI application entrypoint for the main API (port 8000)."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine, init_db
from app.core.errors import install_error_handlers
from app.routers import auth as auth_router
from app.routers import documents as documents_router
from app.routers import admin as admin_router
from app.routers import aicte as aicte_router
from app.routers import institution as institution_router
from app.routers import student as student_router
from app.routers import verifier as verifier_router
from app.services.registry_client import RegistryClient

logger = logging.getLogger("apaar.api")

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=(
        "APAAR ID-based student data management and verification platform (SIH26263). "
        "Prototype — all data is synthetic."
    ),
)

install_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_url, "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    missing = settings.missing_secrets
    if missing:
        logger.warning(
            "Missing secrets: %s — run `make keys` (python scripts/gen_keys.py) before seeding.",
            ", ".join(missing),
        )
    init_db()


app.include_router(auth_router.router)
app.include_router(institution_router.router)
app.include_router(documents_router.router)
app.include_router(aicte_router.router)
app.include_router(student_router.router)
app.include_router(verifier_router.router)
app.include_router(admin_router.router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    """Public health check (CLAUDE.md section 5 rule 4 exempts login and health from RBAC)."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("DB health check failed")
        db_status = f"error: {type(exc).__name__}"

    # A down registry degrades the API but never breaks it (Step 4).
    registry_status = RegistryClient(timeout=1.0, retries=0).health().get("status", "unavailable")

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "service": "api",
        "version": settings.version,
        "db": db_status,
        "registry": registry_status,
        "synthetic_data": True,
        "missing_secrets": settings.missing_secrets,
    }
