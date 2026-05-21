"""统一通知服务 -- 创建通知记录 + 防洪泛 + 分发到外部渠道。

替代Phase 0简版(backend/services/notification_service.py)。
遵循CLAUDE.md: async/await + Depends注入 + 类型注解。

流程(DEV_NOTIFICATIONS.md):
1. P3 -> 不存库，仅日志(Phase 0无WS)
2. P0-P2 -> 存库 + 外发检查
3. 外发检查: P0始终发(无视静默), P1受静默限制, P2看偏好
4. 防洪泛: 同类通知在TTL内不重复
"""

import contextlib
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repositories.base_repository import BaseRepository
from app.services.dispatchers import dingtalk
from app.services.notification_templates import (
    get_template,
)
from app.services.notification_throttler import NotificationThrottler, default_throttler

logger = structlog.get_logger(__name__)


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

    async def delete_old(self, days: int = 30) -> int:
        """清理旧通知 —— 删除超过 days 天的已读通知。

        仅删除 is_read = TRUE 的旧通知: 未读通知 (无论多旧) 一律保留, 避免
        清理动作绕过用户未读感知 (前端铃铛未读计数完整性)。days 经
        make_interval 参数化绑定, 不拼接 interval 字符串 (防注入)。

        Args:
            days: 保留天数; created_at 早于 NOW() - days 天的已读通知被删除。

        Returns:
            删除条数。
        """
        result = await self.execute(
            "DELETE FROM notifications "
            "WHERE is_read = TRUE "
            "AND created_at < NOW() - make_interval(days => :days)",
            {"days": days},
        )
        return result.rowcount

    # ─── 通知偏好 (DEV_NOTIFICATIONS §7+§8 — 单例设置表) ───

    async def get_preferences(self) -> dict[str, Any] | None:
        """读取通知偏好。

        notification_preferences 是单用户单例设置表 (无业务键)。取最新一行;
        无任何行时返回 None (调用方用列默认值兜底)。

        Returns:
            偏好字典, 无记录返回 None。
        """
        row = await self.fetch_one(
            """SELECT id, toast_p0, toast_p1, toast_p2, toast_p3,
                      dingtalk_enabled, dingtalk_webhook,
                      dispatch_p0, dispatch_p1, dispatch_p2,
                      quiet_enabled, quiet_start, quiet_end, updated_at
               FROM notification_preferences
               ORDER BY updated_at DESC NULLS LAST
               LIMIT 1"""
        )
        if not row:
            return None
        return _prefs_row_to_dict(row)

    async def upsert_preferences(self, prefs: dict[str, Any]) -> dict[str, Any]:
        """单例 upsert 通知偏好 (全量替换语义)。

        notification_preferences 单例表无业务键: 先做无 WHERE 的 UPDATE
        (单例下命中 0 或 1 行); rowcount==0 (尚无行) 时 INSERT 首行。

        并发安全: 该表无唯一约束, 两个并发请求在空表上可能各自 rowcount==0
        → 双 INSERT 破坏单例不变量。故先取 pg_advisory_xact_lock 串行化
        upsert (事务级锁, get_db 提交时释放) —— code-review MED 采纳。

        Args:
            prefs: 含 12 个可编辑字段的字典 (由 NotificationPreferences 模型
                model_dump() 产出, 字段齐全)。

        Returns:
            写入后的偏好字典 (含 id / updated_at)。
        """
        # 事务级 advisory lock: 串行化并发 upsert, 保单例不变量。
        await self.execute(
            "SELECT pg_advisory_xact_lock(hashtext('notification_preferences_singleton'))"
        )
        result = await self.execute(
            """UPDATE notification_preferences SET
                   toast_p0 = :toast_p0, toast_p1 = :toast_p1,
                   toast_p2 = :toast_p2, toast_p3 = :toast_p3,
                   dingtalk_enabled = :dingtalk_enabled,
                   dingtalk_webhook = :dingtalk_webhook,
                   dispatch_p0 = :dispatch_p0, dispatch_p1 = :dispatch_p1,
                   dispatch_p2 = :dispatch_p2,
                   quiet_enabled = :quiet_enabled,
                   quiet_start = :quiet_start, quiet_end = :quiet_end,
                   updated_at = NOW()""",
            prefs,
        )
        if result.rowcount == 0:
            await self.execute(
                """INSERT INTO notification_preferences (
                       toast_p0, toast_p1, toast_p2, toast_p3,
                       dingtalk_enabled, dingtalk_webhook,
                       dispatch_p0, dispatch_p1, dispatch_p2,
                       quiet_enabled, quiet_start, quiet_end
                   ) VALUES (
                       :toast_p0, :toast_p1, :toast_p2, :toast_p3,
                       :dingtalk_enabled, :dingtalk_webhook,
                       :dispatch_p0, :dispatch_p1, :dispatch_p2,
                       :quiet_enabled, :quiet_start, :quiet_end
                   )""",
                prefs,
            )
        updated = await self.get_preferences()
        if updated is None:  # pragma: no cover - 刚 upsert 必有行 (fail-loud)
            raise RuntimeError("upsert_preferences: 写入后仍读不到偏好行")
        return updated


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

        # 外发检查 (DEV_NOTIFICATIONS §2 line 70): P0 始终发 (无视静默);
        # P1/P2 受 dispatch_pN 开关 + 静默时段限制. 无偏好行时用列默认值兜底.
        prefs = await self.repo.get_preferences()
        hour_sh = datetime.now(ZoneInfo("Asia/Shanghai")).hour
        if not _should_dispatch_external(level, prefs, hour_sh):
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
            keyword=settings.DINGTALK_KEYWORD,
        )

    # ────────────────────── Sync 方法（给pipeline脚本用） ──────────────────────
    # 这些方法接收psycopg2同步conn，写DB但不commit（由调用方管理事务）。

    def send_sync(
        self,
        conn: Any,
        level: str,
        category: str,
        title: str,
        content: str,
        market: str = "astock",
        force: bool = False,
    ) -> None:
        """同步版通知发送：写DB + 钉钉分发。

        复用throttler防洪泛。Service内部不commit。

        Args:
            conn: psycopg2同步连接。
            level: 级别 P0/P1/P2/P3。
            category: 分类 system/strategy/factor/risk/pipeline。
            title: 标题。
            content: 内容(Markdown)。
            market: 市场 astock/forex/system。
            force: 强制发送，跳过防洪泛。
        """
        # 1. 防洪泛
        if not force and not self.throttler.throttle(level, title):
            logger.info("[Notify] sync被限流: level=%s title='%s'", level, title)
            return

        # 2. 存库(P3不存)
        if level in ("P0", "P1", "P2"):
            try:
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO notifications (level, category, market, title, content)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (level, category, market, title[:100], content),
                )
                logger.info("[Notify] sync已存库: level=%s title='%s'", level, title)
            except Exception as e:
                logger.error("[Notify] sync存库失败: %s", e)
        else:
            logger.debug("[Notify] P3调试通知: title='%s'", title)

        # 3. 钉钉分发
        self._dispatch_sync(conn, level, title, content)

    def send_daily_report_sync(
        self,
        conn: Any,
        trade_date: date,
        nav: float,
        daily_return: float,
        holdings_count: int,
        signals_summary: dict[str, Any],
        is_rebalance: bool = False,
    ) -> None:
        """同步版PT日报。写DB + 发钉钉，不commit。

        Args:
            conn: psycopg2同步连接。
            trade_date: 交易日期。
            nav: 净资产。
            daily_return: 日收益率。
            holdings_count: 持仓数。
            signals_summary: 信号摘要，可包含keys:
                cum_return, beta, buys, sells, rejected, initial_capital。
            is_rebalance: 是否调仓日。
        """
        cum_return = signals_summary.get("cum_return", 0.0)
        beta = signals_summary.get("beta", 0.0)
        buys: list[str] = signals_summary.get("buys", [])
        sells: list[str] = signals_summary.get("sells", [])
        rejected: list[str] = signals_summary.get("rejected", [])

        rebal_text = "**是（调仓）**" if is_rebalance else "否"
        ret_emoji = "\U0001f4c8" if daily_return >= 0 else "\U0001f4c9"

        lines = [
            f"### {ret_emoji} Paper Trading {trade_date}",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 调仓 | {rebal_text} |",
            f"| 持仓 | {holdings_count}只 |",
            f"| NAV | \u00a5{nav:,.0f} |",
            f"| 日收益 | {daily_return:+.2%} |",
            f"| 累计收益 | {cum_return:+.2%} |",
            f"| Beta | {beta:.3f} |",
        ]

        if buys:
            buy_str = ", ".join(buys[:8])
            if len(buys) > 8:
                buy_str += f" +{len(buys) - 8}"
            lines.append(f"\n**买入({len(buys)})**: {buy_str}")

        if sells:
            sell_str = ", ".join(sells[:8])
            if len(sells) > 8:
                sell_str += f" +{len(sells) - 8}"
            lines.append(f"\n**卖出({len(sells)})**: {sell_str}")

        if rejected:
            lines.append(f"\n\u26a0\ufe0f **受限({len(rejected)})**: {', '.join(rejected[:5])}")

        content = "\n".join(lines)
        title = f"Paper Trading {trade_date}"

        # 写DB（不commit）
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO notifications (level, category, market, title, content)
                   VALUES (%s, %s, %s, %s, %s)""",
                ("P1", "paper_daily", "astock", title, content),
            )
        except Exception as e:
            logger.warning("[Notify] sync日报写入DB失败: %s", e)

        # 发钉钉
        dingtalk.send_markdown_sync(
            webhook_url=settings.DINGTALK_WEBHOOK_URL,
            title=f"Paper {trade_date} {daily_return:+.2%}",
            content=content,
            secret=settings.DINGTALK_SECRET,
            keyword=getattr(settings, "DINGTALK_KEYWORD", ""),
        )

    def send_execute_report_sync(
        self,
        conn: Any,
        exec_date: date,
        fills_count: int,
        nav: float,
        cb_level: int,
    ) -> None:
        """同步版执行报告。写DB + 发钉钉，不commit。

        Args:
            conn: psycopg2同步连接。
            exec_date: 执行日期。
            fills_count: 成交笔数。
            nav: 当前净资产。
            cb_level: 熔断等级(0=正常)。
        """
        cb_text = f"L{cb_level}" if cb_level > 0 else "正常"
        level_emoji = (
            "\U0001f534" if cb_level >= 2 else ("\U0001f7e1" if cb_level > 0 else "\U0001f7e2")
        )

        content = (
            f"### {level_emoji} 执行确认 {exec_date}\n\n"
            f"| 指标 | 数值 |\n"
            f"|------|------|\n"
            f"| 成交 | {fills_count}笔 |\n"
            f"| NAV | \u00a5{nav:,.0f} |\n"
            f"| 熔断 | {cb_text} |"
        )
        title = f"执行确认 {exec_date}"
        alert_level = "P0" if cb_level >= 2 else "P1"

        # 写DB（不commit）
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO notifications (level, category, market, title, content)
                   VALUES (%s, %s, %s, %s, %s)""",
                (alert_level, "paper_execute", "astock", title, content),
            )
        except Exception as e:
            logger.warning("[Notify] sync执行报告写入DB失败: %s", e)

        # 发钉钉
        self._dispatch_sync(conn, alert_level, title, content)

    def _dispatch_sync(self, conn: Any, level: str, title: str, content: str) -> None:
        """同步版钉钉分发。外发检查 (DEV_NOTIFICATIONS §2): P0 始终发;
        P1/P2 受 dispatch_pN 开关 + 静默时段限制; P3 不外发.

        Args:
            conn: psycopg2 同步连接 (读 notification_preferences 单例行)。
            level: 通知级别。
            title: 标题。
            content: Markdown内容。
        """
        webhook_url = settings.DINGTALK_WEBHOOK_URL
        if not webhook_url:
            return

        prefs = _get_preferences_sync(conn)
        hour_sh = datetime.now(ZoneInfo("Asia/Shanghai")).hour
        if not _should_dispatch_external(level, prefs, hour_sh):
            return

        level_emoji = {
            "P0": "\U0001f534",
            "P1": "\U0001f7e1",
            "P2": "\U0001f535",
            "P3": "\u26aa",
        }.get(level, "\u26aa")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        dingtalk_content = f"{level_emoji} **[{level}]** {title}\n\n{content}\n\n---\n*{now_str}*"

        dingtalk.send_markdown_sync(
            webhook_url=webhook_url,
            title=f"[{level}] {title}",
            content=dingtalk_content,
            secret=settings.DINGTALK_SECRET,
            keyword=getattr(settings, "DINGTALK_KEYWORD", ""),
        )


# ────────────────────── Sync Wrappers（给pipeline脚本用） ──────────────────────
# run_paper_trading.py等同步脚本通过这些函数调用，签名兼容旧版notification_service。


def send_alert(
    level: str,
    title: str,
    content: str,
    webhook_url: str = "",
    secret: str = "",
    conn: Any = None,
) -> bool:
    """同步告警（兼容旧版接口，给pipeline脚本用）。

    内部通过钉钉直接发送 + 写DB（如有conn）。
    不走async NotificationService，避免脚本中创建事件循环。

    .. note:: **铁律 32 Class C 例外** (Phase D D2 audited 2026-04-16)

       本函数内部 ``conn.commit()`` (写 DB 后) 是 **leaf utility 例外**:

       * 16 个调用方 (services + scripts + tests, 详见
         ``docs/audit/F16_service_commit_audit.md`` §send_alert callers),
         推 commit 到全部调用方违反 DRY 且增加每个 caller 的事务负担
       * 函数已有 ``try/except + rollback`` 自管事务, 不破坏调用方事务原子性
       * 写 DB 是 fire-and-forget 通知日志, 与业务事务解耦是合理设计
       * 同模块 ``send_daily_report`` 同样是 Class C 例外, 保持模式一致

       新代码不要再仿造此模式. 标准 Service 函数应遵循铁律 32 由调用方管理 commit.

    Args:
        level: 告警级别 'P0'/'P1'/'P2'。
        title: 告警标题。
        content: 详细内容。
        webhook_url: DingTalk Webhook地址。
        secret: DingTalk签名密钥。
        conn: psycopg2同步连接（可选，用于写DB + 读外发偏好）。

    Returns:
        True = 外发成功, 或按偏好/静默时段正确抑制 (均视为已正确处理);
        False = 外发失败 (需关注)。
    """
    level_emoji = {"P0": "\U0001f534", "P1": "\U0001f7e1", "P2": "\U0001f535"}.get(level, "\u26aa")
    md = f"### {level_emoji} [{level}] {title}\n\n{content}"

    # 写DB
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO notifications (level, category, market, title, content)
                   VALUES (%s, %s, %s, %s, %s)""",
                (level, "alert", "astock", title, content),
            )
            conn.commit()
        except Exception as e:
            logger.warning("[Notify] sync写入DB失败: %s", e)
            with contextlib.suppress(Exception):
                conn.rollback()

    # 外发检查 (DEV_NOTIFICATIONS §2 line 70): P0 始终发; P1/P2 受 dispatch_pN
    # 开关 + 静默时段限制. conn 缺失或读偏好故障 → fail-safe 照发 (告警不可因
    # 偏好读取问题被静默丢失). 与 NotificationService._dispatch_sync 同口径.
    if conn is not None:
        try:
            _prefs = _get_preferences_sync(conn)
            _suppressed = not _should_dispatch_external(
                level, _prefs, datetime.now(ZoneInfo("Asia/Shanghai")).hour
            )
        except Exception as e:
            logger.warning("[Notify] send_alert 读外发偏好失败, fail-safe 照发: %s", e)
            _suppressed = False
        if _suppressed:
            logger.info(
                "[Notify] send_alert 外发按偏好/静默抑制: level=%s title='%s'", level, title
            )
            return True

    # 发送DingTalk
    return dingtalk.send_markdown_sync(
        webhook_url=webhook_url,
        title=f"[{level}] {title}",
        content=md,
        secret=secret,
        keyword=settings.DINGTALK_KEYWORD if hasattr(settings, "DINGTALK_KEYWORD") else "",
    )


class _SyncNotificationFacade:
    """Sync-only facade for scripts / Celery tasks / sync test code.

    历史 ``get_notification_service()`` 真**从未实现** sustained — 14 callers
    (risk_framework_health_check / pt_monitor_service / daily_pipeline / 多 tests)
    sprint period sustained ImportError silent. Layer 1 P0 修 (Week 1, F-D78-235):
    本 facade 提供 ``send_sync(conn, level, category, title, content, force=False)``,
    内部走 ``send_alert`` (existing sync). 真不实现 throttling/dedup/template — 留 Layer 2.
    """

    def send_sync(
        self,
        conn: Any,
        level: str,
        category: str,
        title: str,
        content: str,
        force: bool = False,
    ) -> bool:
        """同步发送告警 (脚本/Celery tasks 用).

        Args:
            conn: psycopg2 sync 连接 (用于写 notifications 表)
            level: 'P0'/'P1'/'P2'/'P3'
            category: 'risk' / 'system' / 'data' / etc (本版仅 audit log, 不影响路由)
            title: 告警标题
            content: 告警内容 (markdown)
            force: 强制发送 flag (本版 sync 路径 always honored, 不区分)

        Returns:
            DingTalk 发送是否成功 (DB 写入 fire-and-forget).
        """
        webhook = getattr(settings, "DINGTALK_WEBHOOK_URL", "") or ""
        secret = getattr(settings, "DINGTALK_SECRET", "") or ""
        if level == "P3":
            level = "P2"  # send_alert level enum 仅支持 P0/P1/P2
        return send_alert(
            level=level,
            title=title,
            content=content,
            webhook_url=webhook,
            secret=secret,
            conn=conn,
        )


def get_notification_service() -> _SyncNotificationFacade:
    """工厂函数 — 返回 sync facade.

    历史 14 callers (sustained F-D78-235 cluster) sprint period 真依赖此 factory,
    Week 1 Layer 1 P0 修. Async (FastAPI handler) 真路径仍走
    ``NotificationService(session)`` 直 instantiate.
    """
    return _SyncNotificationFacade()


def send_daily_report(
    trade_date: Any,
    nav: float,
    daily_return: float,
    cum_return: float,
    position_count: int,
    is_rebalance: bool,
    beta: float,
    buys: list[str],
    sells: list[str],
    rejected: list[str],
    initial_capital: float,
    webhook_url: str = "",
    secret: str = "",
    conn: Any = None,
) -> bool:
    """同步每日报告（兼容旧版接口，给pipeline脚本用）。

    .. note:: **铁律 32 Class C 例外** (Phase D D2 audited 2026-04-16)

       本函数内部 ``conn.commit()`` (line ~670) 是 leaf utility 例外, 与
       ``send_alert`` 同模式 (fire-and-forget 通知日志, 写 DB 与业务事务解耦).
       详见 ``docs/audit/F16_service_commit_audit.md``.

       **本函数 0 个外部调用方** (Phase D D2 grep 实测), 可能是 dead code;
       Phase E 验证后可能整体删除. 在删除前保持 Class C 例外一致性.

    Args:
        trade_date: 交易日期。
        nav: 净资产。
        daily_return: 日收益率。
        cum_return: 累计收益率。
        position_count: 持仓数。
        is_rebalance: 是否调仓日。
        beta: 组合Beta。
        buys: 买入列表。
        sells: 卖出列表。
        rejected: 受限列表。
        initial_capital: 初始资金。
        webhook_url: DingTalk Webhook地址。
        secret: DingTalk签名密钥。
        conn: psycopg2同步连接。

    Returns:
        DingTalk是否发送成功。
    """
    rebal_text = "**是（调仓）**" if is_rebalance else "否"
    ret_emoji = "\U0001f4c8" if daily_return >= 0 else "\U0001f4c9"

    lines = [
        f"### {ret_emoji} Paper Trading {trade_date}",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 调仓 | {rebal_text} |",
        f"| 持仓 | {position_count}只 |",
        f"| NAV | \u00a5{nav:,.0f} |",
        f"| 日收益 | {daily_return:+.2%} |",
        f"| 累计收益 | {cum_return:+.2%} |",
        f"| Beta | {beta:.3f} |",
    ]

    if buys:
        buy_str = ", ".join(buys[:8])
        if len(buys) > 8:
            buy_str += f" +{len(buys) - 8}"
        lines.append(f"\n**买入({len(buys)})**: {buy_str}")

    if sells:
        sell_str = ", ".join(sells[:8])
        if len(sells) > 8:
            sell_str += f" +{len(sells) - 8}"
        lines.append(f"\n**卖出({len(sells)})**: {sell_str}")

    if rejected:
        lines.append(f"\n\u26a0\ufe0f **受限({len(rejected)})**: {', '.join(rejected[:5])}")

    content = "\n".join(lines)

    # 写DB
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO notifications (level, category, market, title, content)
                   VALUES (%s, %s, %s, %s, %s)""",
                ("info", "paper_daily", "astock", f"Paper Trading {trade_date}", content),
            )
            conn.commit()
        except Exception as e:
            logger.warning("[Notify] sync写入DB失败: %s", e)
            with contextlib.suppress(Exception):
                conn.rollback()

    # 发送DingTalk
    return dingtalk.send_markdown_sync(
        webhook_url=webhook_url,
        title=f"Paper {trade_date} {daily_return:+.2%}",
        content=content,
        secret=secret,
        keyword=settings.DINGTALK_KEYWORD if hasattr(settings, "DINGTALK_KEYWORD") else "",
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


def _prefs_row_to_dict(row: Any) -> dict[str, Any]:
    """将 notification_preferences 行转换为偏好字典。

    Args:
        row: SELECT 结果行 (列顺序见 get_preferences 的 SELECT)。

    Returns:
        偏好字典。
    """
    return {
        "id": str(row[0]),
        "toast_p0": row[1],
        "toast_p1": row[2],
        "toast_p2": row[3],
        "toast_p3": row[4],
        "dingtalk_enabled": row[5],
        "dingtalk_webhook": row[6],
        "dispatch_p0": row[7],
        "dispatch_p1": row[8],
        "dispatch_p2": row[9],
        "quiet_enabled": row[10],
        "quiet_start": row[11],
        "quiet_end": row[12],
        "updated_at": row[13].isoformat() if row[13] else None,
    }


# ─── 外发检查 (DEV_NOTIFICATIONS §2 line 70) ───
# notification_preferences 无行时用 DDL_FINAL.sql 列默认值兜底.
_DISPATCH_PREF_DEFAULTS: dict[str, Any] = {
    "dispatch_p1": True,
    "dispatch_p2": False,
    "quiet_enabled": True,
    "quiet_start": 23,
    "quiet_end": 7,
}


def _in_quiet_window(hour: int, start: int, end: int) -> bool:
    """hour (0-23) 是否落在静默时段 [start, end) — 支持跨午夜 wrap-around。

    start == end 视为空窗 (不静默)。start < end 为同日区间;
    start > end (如 23→7) 为跨午夜区间。
    """
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _should_dispatch_external(level: str, prefs: dict[str, Any] | None, hour_sh: int) -> bool:
    """外发检查 (DEV_NOTIFICATIONS §2 line 70):

    - P0: 始终发 (无视静默 + 无视开关) — 关键告警不可被抑制。
    - P1/P2: 受 dispatch_pN 开关 + 静默时段限制 (quiet_enabled 时)。
    - P3 / 未知 level: 不外发。

    Args:
        level: 通知级别 P0/P1/P2/P3。
        prefs: get_preferences() 偏好字典; None (无偏好行) 时用列默认值兜底。
        hour_sh: 当前 Asia/Shanghai 小时 (0-23, 铁律 41)。

    Returns:
        是否应外发到钉钉。
    """
    if level == "P0":
        return True
    if level not in ("P1", "P2"):
        return False

    prefs = prefs or {}

    def _pref(key: str) -> Any:
        val = prefs.get(key)
        return _DISPATCH_PREF_DEFAULTS[key] if val is None else val

    toggle_key = "dispatch_p1" if level == "P1" else "dispatch_p2"
    if not _pref(toggle_key):
        return False
    in_quiet = _pref("quiet_enabled") and _in_quiet_window(
        hour_sh, _pref("quiet_start"), _pref("quiet_end")
    )
    return not in_quiet


def _get_preferences_sync(conn: Any) -> dict[str, Any] | None:
    """同步读取 notification_preferences 单例行 (给 _dispatch_sync 复用调用方 conn)。

    列顺序与 NotificationRepository.get_preferences 的 SELECT 一致 (供
    _prefs_row_to_dict 索引)。无行返回 None。
    """
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT id, toast_p0, toast_p1, toast_p2, toast_p3,
                      dingtalk_enabled, dingtalk_webhook,
                      dispatch_p0, dispatch_p1, dispatch_p2,
                      quiet_enabled, quiet_start, quiet_end, updated_at
               FROM notification_preferences
               ORDER BY updated_at DESC NULLS LAST
               LIMIT 1"""
        )
        row = cur.fetchone()
    finally:
        cur.close()
    return _prefs_row_to_dict(row) if row else None
