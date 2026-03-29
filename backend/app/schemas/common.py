"""通用 Pydantic schema（分页、错误、日期范围等）。

供所有 API 模块复用的基础响应模型。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorResponse(BaseModel):
    """统一错误响应体。"""

    detail: str = Field(..., description="错误描述")
    code: str | None = Field(default=None, description="业务错误码")


class PaginatedResponse(BaseModel, Generic[T]):
    """通用分页响应体。"""

    items: list[Any] = Field(default_factory=list, description="数据列表")
    total: int = Field(..., description="总记录数")
    page: int = Field(default=1, ge=1, description="当前页码")
    page_size: int = Field(default=50, ge=1, le=200, description="每页条数")


class DateRangeParams(BaseModel):
    """日期范围查询参数。"""

    start_date: date = Field(..., description="起始日期")
    end_date: date = Field(..., description="截止日期")


class TimestampMixin(BaseModel):
    """带时间戳的基础模型。"""

    created_at: datetime | None = Field(default=None, description="创建时间")
    updated_at: datetime | None = Field(default=None, description="更新时间")
