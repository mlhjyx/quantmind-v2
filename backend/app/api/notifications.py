"""通知 API 路由。

提供通知列表、详情、标记已读、未读计数、测试发送等接口。
遵循CLAUDE.md: Depends注入 + 类型注解 + async/await。
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
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
