from typing import Any, Generic, TypeVar

from pydantic import Field, computed_field
from sqlmodel import SQLModel

from app.core.observability import build_meta_dict

T = TypeVar("T")


class PaginationMeta(SQLModel):
    total: int
    page: int = 1
    page_size: int = 10

    @computed_field
    @property
    def total_pages(self) -> int:
        if self.page_size > 0:
            return (self.total + self.page_size - 1) // self.page_size
        return 0


class ApiResponse(SQLModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: T | None = None
    meta: dict[str, str] = Field(default_factory=build_meta_dict)


class PagedApiResponse(SQLModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: T | None = None
    page_info: PaginationMeta | None = None
    meta: dict[str, str] = Field(default_factory=build_meta_dict)


class ApiErrorResponse(SQLModel):
    code: int = -1
    message: str = "error"
    detail: Any = None
    meta: dict[str, str] = Field(default_factory=build_meta_dict)


def api_success(data: T | None = None, message: str = "success") -> ApiResponse[T]:
    return ApiResponse(code=0, message=message, data=data)


def api_error(code: int = -1, message: str = "error", detail: str | None = None) -> ApiErrorResponse:
    return ApiErrorResponse(code=code, message=message, detail=detail)


def api_page(
    data: list[T],
    total: int,
    page: int = 1,
    page_size: int = 10,
    message: str = "success",
) -> PagedApiResponse[list[T]]:
    return PagedApiResponse(
        code=0,
        message=message,
        data=data,
        page_info=PaginationMeta(total=total, page=page, page_size=page_size),
    )
