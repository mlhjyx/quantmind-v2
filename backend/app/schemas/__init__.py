"""Pydantic schema 集中管理层。

所有 API 请求/响应模型统一定义在 schemas/ 目录下，
路由文件通过此包导入使用，避免 inline 模型散落在各 router 中。
"""

from __future__ import annotations

from .common import DateRangeParams, ErrorResponse, PaginatedResponse

__all__ = [
    "DateRangeParams",
    "ErrorResponse",
    "PaginatedResponse",
]
