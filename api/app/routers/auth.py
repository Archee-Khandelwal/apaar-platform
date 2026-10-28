"""Authentication routes. ``/auth/login`` and ``/auth/demo-users`` are the documented
public exceptions to RBAC (CLAUDE.md section 5 rule 4)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import api_error
from app.core.ratelimit import login_throttle
from app.core.security import CurrentUser, create_access_token, get_current_user, verify_password
from app.models.core import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    DemoUser,
    DemoUsersResponse,
    LoginRequest,
    LoginResponse,
    UserOut,
)
from app.services.users import password_problems, set_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    username = payload.username.strip()
    client = _client(request)

    wait = login_throttle.retry_after(username, client)
    if wait:
        log_audit(
            db, actor=username[:64], role="anonymous", action="login_throttled",
            target=f"username:{username[:64]}", payload={"retry_after_seconds": wait},
        )
        db.commit()
        raise api_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "TOO_MANY_ATTEMPTS",
            f"Too many failed sign-in attempts. Try again in {wait} seconds.",
            {"retry_after_seconds": wait},
        )

    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        login_throttle.record_failure(username, client)
        # The attempted name is recorded so repeated guessing is visible; the password never is.
        log_audit(
            db, actor=username[:64], role="anonymous", action="login_failed",
            target=f"username:{username[:64]}",
        )
        db.commit()
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, "BAD_CREDENTIALS", "Username or password is incorrect."
        )

    login_throttle.record_success(username)
    user.last_login_at = datetime.utcnow()
    token, expires_in = create_access_token(user)
    log_audit(db, actor=user.username, role=user.role, action="login", target=f"user:{user.id}")
    db.commit()

    return LoginResponse(access_token=token, expires_in=expires_in, user=_user_out(user))


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name or user.username,
        role=user.role,
        institution_id=user.institution_id,
        student_id=user.student_id,
        must_change_password=bool(user.must_change_password),
    )


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser = Depends(get_current_user)) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        institution_id=user.institution_id,
        student_id=user.student_id,
        must_change_password=user.must_change_password,
    )


@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChangePasswordResponse:
    """Any signed-in user may change their own password. Every other session ends."""
    user = db.get(User, current.id)
    if user is None:  # pragma: no cover - get_current_user already checked
        raise api_error(status.HTTP_401_UNAUTHORIZED, "INVALID_TOKEN", "Unknown account.")

    client = _client(request)
    if login_throttle.retry_after(user.username, client):
        raise api_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "TOO_MANY_ATTEMPTS",
            "Too many wrong passwords. Try again later.",
        )
    if not verify_password(payload.current_password, user.password_hash):
        # A stolen token must not be enough to take over the account.
        login_throttle.record_failure(user.username, client)
        raise api_error(
            status.HTTP_400_BAD_REQUEST, "BAD_CREDENTIALS", "Your current password is incorrect."
        )
    if payload.new_password == payload.current_password:
        raise api_error(
            status.HTTP_400_BAD_REQUEST, "WEAK_PASSWORD", "Choose a password you have not just used."
        )
    problems = password_problems(payload.new_password, username=user.username)
    if problems:
        raise api_error(
            status.HTTP_400_BAD_REQUEST, "WEAK_PASSWORD", " ".join(problems), {"problems": problems}
        )

    set_password(user, payload.new_password)
    log_audit(
        db, actor=user.username, role=user.role, action="password_changed", target=f"user:{user.id}"
    )
    db.commit()
    token, expires_in = create_access_token(user)
    return ChangePasswordResponse(status="changed", access_token=token, expires_in=expires_in)


@router.get("/demo-users", response_model=DemoUsersResponse)
def demo_users(db: Session = Depends(get_db)) -> DemoUsersResponse:
    """Account names for the demo sign-in screen. Never passwords: those are only in the
    gitignored ``demo_credentials.csv``. Disabled when DEMO_MODE=false."""
    if not settings.demo_mode:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Demo mode is disabled on this deployment."
        )

    rows = db.execute(
        select(User).where(User.demo_label.is_not(None), User.is_active.is_(True)).order_by(User.id)
    ).scalars()
    return DemoUsersResponse(
        demo_mode=True,
        users=[
            DemoUser(
                username=row.username,
                role=row.role,
                label=row.demo_label or row.display_name or row.username,
            )
            for row in rows
        ],
    )
