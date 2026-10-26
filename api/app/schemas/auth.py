"""Auth request/response schemas."""
from __future__ import annotations

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


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class DemoUser(BaseModel):
    username: str
    password: str
    role: str
    label: str


class DemoUsersResponse(BaseModel):
    demo_mode: bool
    users: list[DemoUser]
