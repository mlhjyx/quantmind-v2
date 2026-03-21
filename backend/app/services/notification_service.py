"""统一通知服务 -- 创建通知记录 + 防洪泛 + 分发到外部渠道。

替代Phase 0简版(backend/services/notification_service.py)。
遵循CLAUDE.md: async/await + Depends注入 + 类型注解。

流程(DEV_NOTIFICATIONS.md):
1. P3 -> 不存库，仅日志(Phase 0无WS)
2. P0-P2 -> 存库 + 外发检查
3. 外发检查: P0始终发(无视静默), P1受静默限制, P2看偏好
4. 防洪泛: 同类通知在TTL内不重复
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repositories.base_repository import BaseRepository
from app.services.dispatchers import dingtalk
from app.services.notification_templates import (
    get_template,
)
from app.services.notification_throttler import NotificationThrottler, default_throttler

logger = logging.getLogger(__name__)


class NotificationRepository(BaseRepository):
    """notifications表访问层。"""

    async def create(
        self,
        level: str,
        category: str,
        title: str,
        content: str,
        market: str = "system",
        link: str | None = None,
    ) -> dict[str, Any] | None:
        """创建通知记录。

        Args:
            level: 级别 P0/P1/P2。
            category: 分类 system/strategy/factor/risk/pipeline。
            title: 标题(最长100字符)。
            content: 内容(Markdown)。
            market: 市场 astock/forex/system。
            link: 关联链接(可选)。

        Returns:
            创建的通知记录字典，失败返回None。
        """
        row = await self.fetch_one(
            """INSERT INTO notifications (level, category, market, title, content, link)
               VALUES (:level, :category, :market, :title, :content, :link)
               RETURNING id, level, category, market, title, content, link,
                         is_read, is_acted, created_at""",
            {
                "level": level,
                "category": category,
                "market": market,
                "title": title[:100],
                "content": content,
                "link": link,
            },
        )
        if not row:
            return None
        return _row_to_dict(row)

    async def get_by_id(self, notification_id: str) -> dict[str, Any] | None:
        """按ID查询通知。

        Args:
            notification_id: 通知UUID。

        Returns:
            通知字典，不存在返回None。
        """
        row = await self.fetch_one(
            """SELECT id, level, category, market, title, content, link,
                      is_read, is_acted, created_at
               FROM notifications WHERE id = :id""",
            {"id": notification_id},
        )
        if not row:
            return None
        return _row_to_dict(row)

    async def list_notifications(
        self,
        level: str | None = None,
        category: str | None = None,
        is_read: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """分页查询通知列表。

        Args:
            level: 按级别过滤(可选)。
            category: 按分类过滤(可选)。
            is_read: 按已读状态过滤(可选)。
            limit: 每页条数，默认50。
            offset: 偏移量。

        Returns:
            通知列表。
        """
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if level is not None:
            conditions.append("level = :level")
            params["level"] = level
        if category is not None:
            conditions.append("category = :category")
            params["category"] = category
        if is_read is not None:
            conditions.append("is_read = :is_read")
            params["is_read"] = is_read

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = await self.fetch_all(
            f"""SELECT id, level, category, market, title, content, link,
                       is_read, is_acted, created_at
                FROM notifications {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset""",
            params,
        )
        return [_row_to_dict(r) for r in rows]

    async def count_unread(self) -> int:
        """未读通知计数。

        Returns:
            未读通知数量。
        """
        count = await self.fetch_scalar(
            "SELECT COUNT(*) FROM notifications WHERE is_read = FALSE",
        )
        return count or 0

    async def mark_read(self, notification_id: str) -> bool:
        """标记单条通知已读。

        Args:
            notification_id: 通知UUID。

        Returns:
            是否更新成功(记录存在)。
        """
        result = await self.execute(
            "UPDATE notifications SET is_read = TRUE WHERE id = :id AND is_read = FALSE",
            {"id": notification_id},
        )
        return result.rowcount > 0

    async def mark_all_read(self) -> int:
        """标记全部未读通知为已读。

        Returns:
            更新条数。
        """
        result = await self.execute(
            "UPDATE notifications SET is_read = TRUE WHERE is_read = FALSE",
        )
        return result.rowcount


class NotificationService:
    """统一通知服务。

    通过 FastAPI Depends 注入 session。
    提供 send() 统一入口和 send_template() 模板入口。
    """

    def __init__(
        self,
        session: AsyncSession,
        throttler: NotificationThrottler | None = None,
    ) -> None:
        """初始化通知服务。

        Args:
            session: 数据库异步会话。
            throttler: 限流器，None则用全局默认实例。
        """
        self.repo = NotificationRepository(session)
        self.throttler = throttler or default_throttler

    async def send(
        self,
        level: str,
        category: str,
        title: str,
        content: str,
        market: str = "astock",
        link: str | None = None,
        force: bool = False,
    ) -> dict[str, Any] | None:
        """发送通知 -- 统一入口。

        流程:
        1. 防洪泛检查(force=True跳过)
        2. P3不存库仅日志; P0-P2存库
        3. 外发分发(钉钉)

        Args:
            level: 级别 P0/P1/P2/P3。
            category: 分类 system/strategy/factor/risk/pipeline。
            title: 标题。
            content: 内容(Markdown)。
            market: 市场 astock/forex/system。
            link: 关联前端链接(可选)。
            force: 强制发送，跳过防洪泛(默认False)。

        Returns:
            创建的通知记录(P0-P2)，P3返回None。
        """
        # 1. 防洪泛
        if not force and not self.throttler.throttle(level, title):
            logger.info("[Notify] 被限流: level=%s title='%s'", level, title)
            return None

        # 2. 存库(P3不存)
        record: dict[str, Any] | None = None
        if level in ("P0", "P1", "P2"):
            try:
                record = await self.repo.create(
                    level=level,
                    category=category,
                    title=title,
                    content=content,
                    market=market,
                    link=link,
                )
                logger.info(
                    "[Notify] 已存库: id=%s level=%s title='%s'",
                    record["id"] if record else "?",
                    level,
                    title,
                )
            except Exception as e:
                logger.error("[Notify] 存库失败: %s", e)
        else:
            # P3仅日志
            logger.debug("[Notify] P3调试通知: title='%s'", title)

        # 3. 外发分发
        await self._dispatch(level, title, content)

        return record

    async def send_template(
        self,
        template_key: str,
        market: str = "astock",
        link: str | None = None,
        force: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """按模板发送通知。

        Args:
            template_key: 模板key，如 'health_check_failed'。
            market: 市场(覆盖模板默认值)。
            link: 关联链接。
            force: 强制发送。
            **kwargs: 模板变量。

        Returns:
            创建的通知记录。

        Raises:
            KeyError: 模板不存在。
        """
        template = get_template(template_key)
        title, content, level = template.render(**kwargs)
        actual_market = template.market or market

        return await self.send(
            level=level,
            category=template.category,
            title=title,
            content=content,
            market=actual_market,
            link=link,
            force=force,
        )

    async def _dispatch(self, level: str, title: str, content: str) -> None:
        """分发到外部渠道(钉钉)。

        P0始终发; P1/P2看配置。
        失败不影响主流程。

        Args:
            level: 通知级别。
            title: 标题。
            content: Markdown内容。
        """
        webhook_url = settings.DINGTALK_WEBHOOK_URL
        if not webhook_url:
            return

        # P0始终发, P1默认发, P2/P3不外发
        should_dispatch = level in ("P0", "P1")
        if not should_dispatch:
            return

        # 格式化钉钉消息
        level_emoji = {"P0": "🔴", "P1": "🟡", "P2": "🔵", "P3": "⚪"}.get(level, "⚪")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dingtalk_content = f"{level_emoji} **[{level}]** {title}\n\n{content}\n\n---\n*{now_str}*"

        await dingtalk.send_markdown(
            webhook_url=webhook_url,
            title=f"[{level}] {title}",
            content=dingtalk_content,
            secret=settings.DINGTALK_SECRET,
        )


def _row_to_dict(row: Any) -> dict[str, Any]:
    """将数据库行转换为通知字典。

    Args:
        row: 数据库查询结果行。

    Returns:
        通知字典。
    """
    return {
        "id": str(row[0]),
        "level": row[1],
        "category": row[2],
        "market": row[3],
        "title": row[4],
        "content": row[5],
        "link": row[6],
        "is_read": row[7],
        "is_acted": row[8],
        "created_at": row[9].isoformat() if row[9] else None,
    }
