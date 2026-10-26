"""Authentication routes. ``/auth/login`` and ``/auth/demo-users`` are the documented
public exceptions to RBAC (CLAUDE.md section 5 rule 4)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_audit
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import api_error
from app.core.security import CurrentUser, create_access_token, get_current_user, verify_password
from app.models.core import User
from app.schemas.auth import DemoUser, DemoUsersResponse, LoginRequest, LoginResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.execute(
        select(User).where(User.username == payload.username.strip())
    ).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise api_error(
            status.HTTP_401_UNAUTHORIZED, "BAD_CREDENTIALS", "Username or password is incorrect."
        )

    token, expires_in = create_access_token(user)
    log_audit(db, actor=user.username, role=user.role, action="login", target=f"user:{user.id}")
    db.commit()

    return LoginResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserOut(
            id=user.id,
            username=user.username,
            display_name=user.display_name or user.username,
            role=user.role,
            institution_id=user.institution_id,
            student_id=user.student_id,
        ),
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
    )


@router.get("/demo-users", response_model=DemoUsersResponse)
def demo_users(db: Session = Depends(get_db)) -> DemoUsersResponse:
    """Demo-only convenience for the one-click role switcher. Disabled when DEMO_MODE=false."""
    if not settings.demo_mode:
        raise api_error(
            status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Demo mode is disabled on this deployment."
        )

    rows = db.execute(
        select(User).where(User.demo_password.is_not(None), User.is_active.is_(True)).order_by(User.id)
    ).scalars()
    return DemoUsersResponse(
        demo_mode=True,
        users=[
            DemoUser(
                username=row.username,
                password=row.demo_password or "",
                role=row.role,
                label=row.demo_label or row.display_name or row.username,
            )
            for row in rows
        ],
    )
