"""Auth request/response schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    institution_id: int | None = None
    student_id: int | None = None
    must_change_password: bool = False


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class DemoUser(BaseModel):
    """A demo account's name and label. Passwords never leave the server: they are only
    in the gitignored ``demo_credentials.csv`` written at seed time."""

    username: str
    role: str
    label: str


class DemoUsersResponse(BaseModel):
    demo_mode: bool
    users: list[DemoUser]


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class ChangePasswordResponse(BaseModel):
    status: str
    # A fresh token, because the change logs out every earlier session.
    access_token: str
    expires_in: int


class AdminUserRow(BaseModel):
    id: int
    username: str
    role: str
    display_name: str
    institution_id: int | None = None
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None = None
    password_changed_at: datetime | None = None


class AdminUserPage(BaseModel):
    items: list[AdminUserRow]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort: str | None = None


class PasswordResetResponse(BaseModel):
    user_id: int
    username: str
    # Shown once, to the admin who reset it. It is never stored in plain text.
    temporary_password: str
    must_change_password: bool
    audit_log_id: int
