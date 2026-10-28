"""Authentication, RBAC and tenant isolation (CLAUDE.md section 5 rules 4, 5 and 9).

Every route in this application is wrapped in ``require_role(...)`` — the only exceptions
are ``/health``, ``/auth/login``, ``/auth/demo-users`` and the public document checks.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.models.core import User
from app.models.enums import ROLES

ALGORITHM = "HS256"
SMALL_COUNT_THRESHOLD = 5
SUPPRESSED = "<5"

_pwd_context = CryptContext(
    schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=settings.bcrypt_rounds
)
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(password, password_hash)
    except ValueError:  # pragma: no cover - malformed hash
        return False


def _jwt_secret() -> str:
    if not settings.jwt_secret or settings.jwt_secret.startswith("replace-me"):
        raise RuntimeError("JWT_SECRET is not set — run `make keys`.")
    return settings.jwt_secret


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated caller. ``institution_id`` / ``student_id`` come from the JWT only."""

    id: int
    username: str
    role: str
    institution_id: int | None = None
    student_id: int | None = None
    display_name: str = ""
    must_change_password: bool = False

    @property
    def is_aicte(self) -> bool:
        return self.role in ("aicte_viewer", "aicte_officer")


def create_access_token(user: User, expires_minutes: int | None = None) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    ttl = timedelta(minutes=expires_minutes or settings.jwt_expire_minutes)
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "user_id": user.id,
        "username": user.username,
        "role": user.role,
        "institution_id": user.institution_id,
        "student_id": user.student_id,
        "ver": user.token_version or 1,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=ALGORITHM), int(ttl.total_seconds())


def _unauthorized(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": {"code": code, "message": message}},
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> CurrentUser:
    if credentials is None or not credentials.credentials:
        raise _unauthorized("NOT_AUTHENTICATED", "Missing bearer token.")
    try:
        payload = jwt.decode(credentials.credentials, _jwt_secret(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("TOKEN_EXPIRED", "Session expired — please log in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise _unauthorized("INVALID_TOKEN", "Token signature is not valid.") from exc

    user = db.execute(select(User).where(User.id == int(payload["user_id"]))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise _unauthorized("INVALID_TOKEN", "This account no longer exists or is disabled.")
    if user.role != payload.get("role"):
        # The token's role no longer matches the account; refuse rather than trust the token.
        raise _unauthorized("INVALID_TOKEN", "Token role does not match the account.")
    if payload.get("ver") != (user.token_version or 1):
        # Issued before the last password change or reset.
        raise _unauthorized("TOKEN_REVOKED", "Your password was changed — please log in again.")

    return CurrentUser(
        id=user.id,
        username=user.username,
        role=user.role,
        institution_id=user.institution_id,
        student_id=user.student_id,
        display_name=user.display_name or user.username,
        must_change_password=bool(user.must_change_password),
    )


def require_role(*roles: str):
    """Dependency factory. Usage: ``user: CurrentUser = Depends(require_role("institution"))``."""
    unknown = [role for role in roles if role not in ROLES]
    if unknown:
        raise ValueError(f"Unknown role(s) in require_role: {unknown}")

    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.must_change_password:
            # After an admin reset, the temporary password only unlocks the change form.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "PASSWORD_CHANGE_REQUIRED",
                        "message": "Set a new password before continuing.",
                    }
                },
            )
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "FORBIDDEN_ROLE",
                        "message": f"This endpoint requires role {' or '.join(roles)}.",
                        "details": {"required_roles": list(roles), "actual_role": user.role},
                    }
                },
            )
        return user

    return dependency


# --------------------------------------------------------------------------- tenant isolation


def require_institution_scope(
    user: CurrentUser = Depends(require_role("institution")),
) -> int:
    """The ONLY way an institution route may learn its institution_id.

    Routers depend on this instead of accepting an id from the path, query or body, so
    a college can never read another college's rows (CLAUDE.md section 5 rule 5).
    """
    if user.institution_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "TENANT_SCOPE_VIOLATION",
                    "message": "This account is not linked to an institution.",
                }
            },
        )
    return user.institution_id


def assert_owned_by_institution(institution_id: int, row_institution_id: int | None) -> None:
    """Guard for single-row fetches: 404, not 403, so we don't confirm the row exists."""
    if row_institution_id != institution_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "No such record for this institution."}},
        )


# --------------------------------------------------------------------------- suppression


def suppress_small_counts(
    data: dict[str, Any] | list[Any],
    role: str,
    *,
    keep_keys: tuple[str, ...] = (),
) -> Any:
    """Turn counts below 5 into ``"<5"`` for ``aicte_viewer`` (CLAUDE.md section 5 rule 9).

    Applies recursively to dicts and lists. ``keep_keys`` names keys whose numeric values
    are identifiers or totals rather than cell counts, and are therefore left alone.
    """
    if role != "aicte_viewer":
        return data

    protected = set(keep_keys) | {
        "id",
        "institution_id",
        "student_id",
        "program_id",
        "flag_id",
        "enrolment_id",
        "upload_id",
        "page",
        "page_size",
        "total",
        "total_pages",
        "rank",
        "limit",
        "score",
        "year_of_study",
        "version",
        "dob_year",
    }

    def walk(node: Any, key: str | None = None) -> Any:
        if isinstance(node, dict):
            return {k: walk(v, k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(item, key) for item in node]
        if (
            isinstance(node, int)
            and not isinstance(node, bool)
            and key is not None
            and key not in protected
            and 0 < node < SMALL_COUNT_THRESHOLD
        ):
            return SUPPRESSED
        return node

    return walk(data)
