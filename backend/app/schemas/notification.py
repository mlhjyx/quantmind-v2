"""通知 schema。

对应 API 路由: /api/notifications/*
设计文档: docs/DEV_BACKEND.md 通知服务。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class TestNotificationRequest(BaseModel):
    """测试通知请求体（调试用）。"""

    level: str = Field(default="P2", description="通知级别: P0/P1/P2/P3")
    category: str = Field(
        default="system", description="分类: system/strategy/factor/risk/pipeline"
    )
    title: str = Field(default="测试通知", description="通知标题")
    content: str = Field(
        default="这是一条测试通知，用于验证通知系统是否正常工作。",
        description="通知内容",
    )
    market: str = Field(default="system", description="所属市场")


# ---------------------------------------------------------------------------
# 响应模型
# ---------------------------------------------------------------------------


class NotificationResponse(BaseModel):
    """通知记录响应。"""

    id: str = Field(..., description="通知UUID")
    level: str = Field(..., description="通知级别: P0/P1/P2/P3")
    category: str | None = Field(default=None, description="分类")
    title: str = Field(..., description="通知标题")
    message: str | None = Field(default=None, description="通知内容")
    created_at: str | None = Field(default=None, description="创建时间")
    read: bool = Field(default=False, description="是否已读")
    target_path: str | None = Field(default=None, description="跳转路径（前端路由）")


class NotificationListResponse(BaseModel):
    """通知列表响应（含分页和未读计数）。"""

    items: list[NotificationResponse] = Field(
        default_factory=list,
        description="通知列表",
    )
    limit: int = Field(default=50, description="每页条数")
    offset: int = Field(default=0, description="偏移量")
    unread_count: int = Field(default=0, description="未读通知数")


class NotificationPreferences(BaseModel):
    """通知偏好设置。"""

    channels: dict[str, bool] = Field(
        default_factory=lambda: {"web": True, "email": False, "wechat": False},
        description="通知渠道开关: {web, email, wechat}",
    )
    quiet_hours_start: str | None = Field(
        default=None,
        description="免打扰开始时间(HH:MM)",
    )
    quiet_hours_end: str | None = Field(
        default=None,
        description="免打扰结束时间(HH:MM)",
    )
