"""通知 API 路由。

提供通知列表、详情、标记已读、未读计数、测试发送等接口。
遵循CLAUDE.md: Depends注入 + 类型注解 + async/await。
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.notification_service import NotificationRepository, NotificationService

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


# ---------------------------------------------------------------------------
# Depends 注入
# ---------------------------------------------------------------------------


def _get_repo(session: AsyncSession = Depends(get_db)) -> NotificationRepository:
    """注入 NotificationRepository。"""
    return NotificationRepository(session)


def _get_service(session: AsyncSession = Depends(get_db)) -> NotificationService:
    """注入 NotificationService。"""
    return NotificationService(session)


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------


class TestNotificationRequest(BaseModel):
    """测试通知请求体。"""

    level: str = "P2"
    category: str = "system"
    title: str = "测试通知"
    content: str = "这是一条测试通知，用于验证通知系统是否正常工作。"
    market: str = "system"


class NotificationPreferences(BaseModel):
    """通知偏好请求/响应体 (全量替换语义 — 前端 GET 当前值后整体 PUT 回)。

    字段默认值对齐 notification_preferences 表的列默认值 (QUANTMIND_V2_DDL_FINAL.sql)。
    """

    toast_p0: bool = True
    toast_p1: bool = True
    toast_p2: bool = True
    toast_p3: bool = True
    dingtalk_enabled: bool = False
    dingtalk_webhook: str | None = Field(default=None, max_length=500)
    dispatch_p0: bool = True
    dispatch_p1: bool = True
    dispatch_p2: bool = False
    quiet_enabled: bool = True
    quiet_start: int = Field(default=23, ge=0, le=23, description="静默开始小时 0-23")
    quiet_end: int = Field(default=7, ge=0, le=23, description="静默结束小时 0-23")


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.get("")
async def list_notifications(
    level: str | None = Query(None, description="按级别过滤: P0/P1/P2"),
    category: str | None = Query(
        None, description="按分类过滤: system/strategy/factor/risk/pipeline"
    ),
    is_read: bool | None = Query(None, description="按已读状态过滤"),
    limit: int = Query(50, ge=1, le=200, description="每页条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
    repo: NotificationRepository = Depends(_get_repo),
) -> dict[str, Any]:
    """通知列表(分页+级别/分类/已读过滤)。

    Returns:
        包含 items 列表和 total/limit/offset 分页信息的字典。
    """
    items = await repo.list_notifications(
        level=level,
        category=category,
        is_read=is_read,
        limit=limit,
        offset=offset,
    )
    unread = await repo.count_unread()

    return {
        "items": items,
        "limit": limit,
        "offset": offset,
        "unread_count": unread,
    }


@router.get("/unread-count")
async def unread_count(
    repo: NotificationRepository = Depends(_get_repo),
) -> dict[str, int]:
    """未读通知计数(前端铃铛数字)。

    Returns:
        包含 unread_count 的字典。
    """
    count = await repo.count_unread()
    return {"unread_count": count}


@router.put("/read-all")
async def mark_all_read(
    repo: NotificationRepository = Depends(_get_repo),
) -> dict[str, Any]:
    """标记全部未读通知为已读 (DEV_NOTIFICATIONS §8)。

    Returns:
        包含 success 和 updated_count (本次标记的条数) 的字典。
    """
    count = await repo.mark_all_read()
    return {"success": True, "updated_count": count}


@router.delete("/clear-old")
async def clear_old(
    days: int = Query(30, ge=1, le=365, description="保留天数, 早于此的已读通知被清理"),
    repo: NotificationRepository = Depends(_get_repo),
) -> dict[str, Any]:
    """清理旧通知 — 删除超过 days 天的已读通知 (DEV_NOTIFICATIONS §8)。

    未读通知一律保留 (不论多旧), 避免清理绕过用户未读感知。

    Args:
        days: 保留天数 (1-365), 默认 30。

    Returns:
        包含 success 和 deleted_count 的字典。
    """
    count = await repo.delete_old(days)
    return {"success": True, "deleted_count": count}


@router.get("/preferences")
async def get_preferences(
    repo: NotificationRepository = Depends(_get_repo),
) -> dict[str, Any]:
    """获取通知偏好 (DEV_NOTIFICATIONS §8)。

    notification_preferences 是单例设置表; 无记录时返回列默认值
    (id / updated_at 为 None)。

    Returns:
        通知偏好字典。
    """
    prefs = await repo.get_preferences()
    if prefs is None:
        return {**NotificationPreferences().model_dump(), "id": None, "updated_at": None}
    return prefs


@router.put("/preferences")
async def update_preferences(
    body: NotificationPreferences,
    repo: NotificationRepository = Depends(_get_repo),
) -> dict[str, Any]:
    """更新通知偏好 (DEV_NOTIFICATIONS §8) — 全量替换 (单例 upsert)。

    Args:
        body: 完整的通知偏好 (前端 GET 当前值, 用户编辑后整体提交)。

    Returns:
        写入后的通知偏好字典 (含 id / updated_at)。
    """
    return await repo.upsert_preferences(body.model_dump())


@router.get("/{notification_id}")
async def get_notification(
    notification_id: str,
    repo: NotificationRepository = Depends(_get_repo),
) -> dict[str, Any]:
    """通知详情。

    Args:
        notification_id: 通知UUID。

    Returns:
        通知详情字典。

    Raises:
        HTTPException: 通知不存在时返回404。
    """
    record = await repo.get_by_id(notification_id)
    if not record:
        raise HTTPException(status_code=404, detail="通知不存在")
    return record


@router.put("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    repo: NotificationRepository = Depends(_get_repo),
) -> dict[str, Any]:
    """标记单条通知已读。

    Args:
        notification_id: 通知UUID。

    Returns:
        包含 success 和 id 的字典。

    Raises:
        HTTPException: 通知不存在或已读时返回404。
    """
    updated = await repo.mark_read(notification_id)
    if not updated:
        raise HTTPException(status_code=404, detail="通知不存在或已标记已读")
    return {"success": True, "id": notification_id}


@router.post("/test")
async def test_notification(
    body: TestNotificationRequest,
    service: NotificationService = Depends(_get_service),
) -> dict[str, Any]:
    """发送测试通知(调试用)。

    Args:
        body: 测试通知内容。

    Returns:
        发送结果，包含创建的通知记录。
    """
    record = await service.send(
        level=body.level,
        category=body.category,
        title=body.title,
        content=body.content,
        market=body.market,
        force=True,  # 测试通知跳过限流
    )
    return {
        "success": True,
        "message": "测试通知已发送",
        "notification": record,
    }
