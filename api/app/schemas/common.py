"""Shared Pydantic schemas: pagination envelope and query params."""
from __future__ import annotations

from typing import Annotated, Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200


class Page(BaseModel, Generic[T]):
    """The list envelope from docs/API_CONTRACT.md section 0.4."""

    items: list[T]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort: str | None = None


class PageParams(BaseModel):
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    sort: str | None = None

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    sort: Annotated[str | None, Query()] = None,
) -> PageParams:
    return PageParams(page=page, page_size=page_size, sort=sort)


def paginate(items: list[Any], total: int, params: PageParams) -> dict[str, Any]:
    total_pages = max(1, (total + params.page_size - 1) // params.page_size) if total else 0
    return {
        "items": items,
        "page": params.page,
        "page_size": params.page_size,
        "total": total,
        "total_pages": total_pages,
        "sort": params.sort,
    }


class OkResponse(BaseModel):
    status: str = "ok"
    message: str | None = None


class NoteIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)
