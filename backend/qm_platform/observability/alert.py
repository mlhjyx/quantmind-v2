"""MVP 4.1 Observability Framework batch 1 — PostgresAlertRouter concrete.

替代 17 个 schtask + Celery 脚本散落 DingTalk webhook 直调 + 各自 dedup 实现的方案:
  - cross-process PG dedup (alert_dedup 表) 替代 in-memory NotificationThrottler
    (Phase 0 单进程内存版跨 schtask 进程永久失效)
  - 统一 settings.DINGTALK_* 入口 (铁律 34 SSOT, 5 scripts os.environ 直读视为漂移)
  - fail-loud: 所有 channel 都失败必 raise AlertDispatchError (interface 契约 + 铁律 33)
  - dedup 行为返回 Literal[sent / deduped / sink_failed], 调用方明确决策

关联铁律:
  - 28 (发现即报告): sink 失败必 log ERROR + raise
  - 33 (fail-loud): 全部 channel 失败 raise, 不静默
  - 34 (config SSOT): webhook 仅经 settings.DINGTALK_WEBHOOK_URL
  - 41 (时区): 所有 timestamp UTC tz-aware

Blueprint Framework #7 双签名兼容:
  - interface.py 契约 fire(alert: Alert, ...) — 完整 Alert 对象
  - Blueprint 字面 alert(severity, payload) — 简洁 API, 内部转 Alert 调 fire

Channel Protocol 抽象:
  - 当前只 DingTalk concrete (单 channel, 所有 severity 走). batch 2 引入 yaml 路由规则.
  - SMS 留 Wave 5+ 视成本评估 (Blueprint P0→SMS 暂用 DingTalk 单 channel 满足 P0 触达 < 30s).

Usage:
    >>> from qm_platform.observability import get_alert_router, Alert, Severity
    >>> router = get_alert_router()
    >>> result = router.fire(
    ...     Alert(
    ...         title="dv_ttm IC 衰减",
    ...         severity=Severity.P1,
    ...         source="factor_lifecycle_monitor",
    ...         details={"ratio": 0.517},
    ...         trade_date="2026-04-28",
    ...         timestamp_utc="2026-04-28T19:00:00+00:00",
    ...     ),
    ...     dedup_key="factor_lifecycle:dv_ttm:warning",
    ... )
    >>> result  # "sent" / "deduped" / 抛 AlertDispatchError
    'sent'
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, Protocol

from .._types import Severity
from .interface import Alert, AlertRouter

if TYPE_CHECKING:
    import psycopg2.extensions

logger = logging.getLogger(__name__)

# Caller-provided dedup_key 长度上限 (PG TEXT PK index 约束 + 防滥用).
_DEDUP_KEY_MAX_LEN = 512

# Severity 默认 suppress 窗口 (分钟). caller 可经 fire(suppress_minutes=...) 覆盖.
# Blueprint #7 "7 天内同 key 自动 dedup" 解读为最大窗口 (7 * 24 * 60 min), 默认值显著
# 短于上限以保证可观测性 (P0 < 5min 触达 + 后续 dedup, P1/P2 半小时-小时维度).
_DEFAULT_SUPPRESS_MINUTES: dict[Severity, int] = {
    Severity.P0: 5,
    Severity.P1: 30,
    Severity.P2: 60,
    Severity.INFO: 60,
}
_MAX_SUPPRESS_MINUTES = 7 * 24 * 60  # Blueprint #7 7d 上限.

FireResult = Literal["sent", "deduped", "sink_failed"]


class AlertDispatchError(RuntimeError):
    """所有 channel 都失败时抛出 (interface 契约 + 铁律 33 fail-loud).

    调用方根据语义决定是否 retry (注意: 同 dedup_key 在 suppress 窗口内仍会被 dedup).
    """


class Channel(Protocol):
    """告警发送 channel 抽象.

    每个 channel send() return True/False. Router fires 全部 channels 收集结果,
    全部 False (或 raise) → AlertDispatchError.
    """

    name: str

    def send(self, alert: Alert) -> bool: ...


class DingTalkChannel:
    """DingTalk webhook channel (HMAC 签名 + 关键词模式).

    Wraps backend.app.services.dispatchers.dingtalk.send_markdown_sync (已存 sync helper,
    10s 超时, 失败 log 不抛 — 我们在此层 wrap 把 False 转成 fail-loud 信号).
    """

    name = "dingtalk"

    def __init__(
        self,
        webhook_url: str,
        secret: str = "",
        keyword: str = "",
        sender: Callable[..., bool] | None = None,
    ) -> None:
        if not webhook_url:
            # 铁律 33 fail-loud: 无 webhook 配置 → 实例化即 raise (调用方/factory 负责处理).
            raise ValueError("DingTalk webhook_url 未配置 (settings.DINGTALK_WEBHOOK_URL)")
        self._webhook_url = webhook_url
        self._secret = secret
        self._keyword = keyword
        # sender 注入便于单测 (生产默认 send_markdown_sync).
        if sender is None:
            from app.services.dispatchers.dingtalk import send_markdown_sync as _default_sender
            sender = _default_sender
        self._sender = sender

    def send(self, alert: Alert) -> bool:
        """发送 alert 为 DingTalk Markdown.

        Returns:
          True 钉钉接受 (errcode==0); False 任何失败 (网络 / 签名 / errcode != 0).
          上游 Router 把 False 转为 sink_failed + AlertDispatchError.
        """
        title = f"[{alert.severity.value.upper()}] {alert.title}"
        # Markdown 排版: 标题 + 元数据表格 + details 自由文本.
        details_lines = [f"- **{k}**: {v}" for k, v in alert.details.items()]
        body = (
            f"### {title}\n\n"
            f"**source**: `{alert.source}`  \n"
            f"**trade_date**: `{alert.trade_date or 'N/A'}`  \n"
            f"**utc**: `{alert.timestamp_utc}`\n\n"
            + "\n".join(details_lines)
        )
        return self._sender(
            webhook_url=self._webhook_url,
            title=title,
            content=body,
            secret=self._secret,
            keyword=self._keyword,
        )


def _now_utc() -> datetime:
    """tz-aware UTC now (铁律 41 显式 UTC, 测试可 monkeypatch)."""
    return datetime.now(UTC)


class PostgresAlertRouter(AlertRouter):
    """AlertRouter concrete: PG-backed cross-process dedup + DingTalk channel.

    线程安全: PG ON CONFLICT 提供原子 upsert; 单 router 实例多线程并发安全.
    跨进程安全: PG 行级语义保证 17 schtask 进程同 dedup_key 互斥.

    Args:
      channels: Channel 实例列表. 默认空 → 从 settings.DINGTALK_WEBHOOK_URL 自动构建
                单 DingTalkChannel. 测试可注入 mock channels.
      conn_factory: 可调用对象返回 psycopg2 connection (须 caller 管 close, 此 router
                    负责 close). None 默认 app.services.db.get_sync_conn.
      now_fn: 时间注入 (单测 freeze 用), 默认 _now_utc.

    Raises:
      ValueError: channels 空 + DINGTALK_WEBHOOK_URL 未配置 (铁律 33 boot fail-loud).
    """

    def __init__(
        self,
        channels: Iterable[Channel] | None = None,
        conn_factory: Callable[[], psycopg2.extensions.connection] | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        if channels is None:
            from app.config import settings
            channels = [
                DingTalkChannel(
                    webhook_url=settings.DINGTALK_WEBHOOK_URL,
                    secret=settings.DINGTALK_SECRET,
                    keyword=settings.DINGTALK_KEYWORD,
                )
            ]
        chans = list(channels)
        if not chans:
            raise ValueError(
                "PostgresAlertRouter 至少需要 1 个 Channel. 默认从 settings.DINGTALK_* "
                "构建, 显式传入 channels=[] 表示无 sink, 不允许."
            )
        self._channels: list[Channel] = chans
        if conn_factory is None:
            from app.services.db import get_sync_conn as _default_factory
            conn_factory = _default_factory
        self._conn_factory = conn_factory
        self._now_fn = now_fn or _now_utc

    def fire(
        self,
        alert: Alert,
        *,
        dedup_key: str,
        suppress_minutes: int | None = None,
    ) -> FireResult:
        """触发告警 — PG dedup 检查 + 多 channel 发送 + 持久化 dedup 状态.

        Args:
          alert: Alert dataclass (interface.py).
          dedup_key: caller 显式 dedup 键 (e.g. "factor_lifecycle:dv_ttm:warning").
                     非空, ≤ 512 字符. 显式 > 隐式, 避免 title 微小变化导致 dedup miss.
          suppress_minutes: dedup 窗口分钟数. None → severity 驱动默认值
                            (P0=5/P1=30/P2=60/INFO=60). 上限 7d (Blueprint #7).

        Returns:
          "sent" — 实际发送至少 1 channel 成功
          "deduped" — 在 suppress 窗口内, 跳过发送 (fire_count++)
          "sink_failed" — 全部 channel 失败 (同时 raise AlertDispatchError)

        Raises:
          ValueError: dedup_key 空 / 超长 / suppress_minutes 越界.
          AlertDispatchError: 全部 channel 失败 (铁律 33 fail-loud).
        """
        self._validate(dedup_key, suppress_minutes)
        suppress_min = (
            suppress_minutes
            if suppress_minutes is not None
            else _DEFAULT_SUPPRESS_MINUTES.get(alert.severity, 60)
        )
        now = self._now_fn()

        conn = self._conn_factory()
        try:
            try:
                with conn:  # 自动 commit / rollback
                    if self._is_deduped(conn, dedup_key, now):
                        self._increment_dedup_count(conn, dedup_key, alert, now)
                        logger.info(
                            "[AlertRouter] deduped key=%s severity=%s source=%s",
                            dedup_key,
                            alert.severity.value,
                            alert.source,
                        )
                        return "deduped"
                    # 发送至所有 channel (短路: 不要求全部成功, 任 1 成功即视为 sent)
                    sent_any, failures = self._dispatch(alert)
                    self._upsert_dedup(
                        conn, dedup_key, alert, now, suppress_min, fired=sent_any
                    )
                    if not sent_any:
                        logger.error(
                            "[AlertRouter] sink_failed key=%s failures=%s",
                            dedup_key,
                            failures,
                        )
                        raise AlertDispatchError(
                            f"All channels failed for dedup_key={dedup_key!r}: {failures}"
                        )
                    logger.info(
                        "[AlertRouter] sent key=%s severity=%s suppress=%dmin",
                        dedup_key,
                        alert.severity.value,
                        suppress_min,
                    )
                    return "sent"
            finally:
                conn.close()
        except AlertDispatchError:
            raise
        except Exception:
            # 非 AlertDispatchError 的异常 (e.g. PG 连接错 / cursor 错) 也要 fail-loud.
            logger.exception(
                "[AlertRouter] unexpected fire() exception key=%s", dedup_key
            )
            raise

    def alert(self, severity: Severity, payload: dict[str, Any]) -> FireResult:
        """Blueprint Framework #7 字面签名 (alert(severity, payload)).

        从 payload 构造 Alert 调 fire. payload 必须含 keys: title / source / dedup_key.
        可选: details (dict) / trade_date / suppress_minutes / timestamp_utc.
        """
        if "title" not in payload or "source" not in payload or "dedup_key" not in payload:
            raise ValueError(
                "alert(payload) 必须含 keys: title / source / dedup_key. "
                "fire(Alert, dedup_key=...) 是更精确签名, 推荐."
            )
        ts = payload.get("timestamp_utc") or self._now_fn().isoformat()
        a = Alert(
            title=str(payload["title"]),
            severity=severity,
            source=str(payload["source"]),
            details=dict(payload.get("details") or {}),
            trade_date=payload.get("trade_date"),
            timestamp_utc=ts,
        )
        return self.fire(
            a,
            dedup_key=str(payload["dedup_key"]),
            suppress_minutes=payload.get("suppress_minutes"),
        )

    def get_history(
        self,
        severity: Severity | None = None,
        limit: int = 100,
    ) -> list[Alert]:
        """读 alert_dedup 最近 N 条 (按 last_fired_at DESC).

        Note: alert_dedup 是 dedup 状态表 (1 row / dedup_key), 非完整告警历史. 完整审计
        (含被 dedup 的) 需走 batch 2 platform_metrics + alert_history view (留 future).
        """
        if limit <= 0 or limit > 10000:
            raise ValueError(f"limit 必须 1..10000, got {limit}")
        conn = self._conn_factory()
        try:
            with conn.cursor() as cur:
                if severity is None:
                    cur.execute(
                        """
                        SELECT dedup_key, severity, source, last_fired_at, last_title
                        FROM alert_dedup
                        ORDER BY last_fired_at DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT dedup_key, severity, source, last_fired_at, last_title
                        FROM alert_dedup
                        WHERE severity = %s
                        ORDER BY last_fired_at DESC
                        LIMIT %s
                        """,
                        (severity.value, limit),
                    )
                rows = cur.fetchall()
        finally:
            conn.close()

        out: list[Alert] = []
        for dedup_key, sev_str, source, last_fired, last_title in rows:
            try:
                sev = Severity(sev_str)
            except ValueError:
                # 未来扩 enum 时旧 row 兜底 (铁律 33 不静默, log warn).
                logger.warning(
                    "[AlertRouter] unknown severity %r in alert_dedup row %s",
                    sev_str,
                    dedup_key,
                )
                continue
            out.append(
                Alert(
                    title=str(last_title or dedup_key),
                    severity=sev,
                    source=str(source),
                    details={"dedup_key": dedup_key},
                    trade_date=None,
                    timestamp_utc=(
                        last_fired.isoformat()
                        if isinstance(last_fired, datetime)
                        else str(last_fired)
                    ),
                )
            )
        return out

    # ─────────────────────────── 内部 helpers ───────────────────────────

    @staticmethod
    def _validate(dedup_key: str, suppress_minutes: int | None) -> None:
        if not isinstance(dedup_key, str) or not dedup_key.strip():
            raise ValueError("dedup_key 必须非空字符串")
        if len(dedup_key) > _DEDUP_KEY_MAX_LEN:
            raise ValueError(
                f"dedup_key 超长 (>{_DEDUP_KEY_MAX_LEN} chars): {len(dedup_key)}"
            )
        if suppress_minutes is not None:
            if not isinstance(suppress_minutes, int) or suppress_minutes <= 0:
                raise ValueError(
                    f"suppress_minutes 必须正整数, got {suppress_minutes!r}"
                )
            if suppress_minutes > _MAX_SUPPRESS_MINUTES:
                raise ValueError(
                    f"suppress_minutes 超过 7d 上限 ({_MAX_SUPPRESS_MINUTES}min), "
                    f"got {suppress_minutes}"
                )

    @staticmethod
    def _is_deduped(
        conn: psycopg2.extensions.connection, dedup_key: str, now: datetime
    ) -> bool:
        """SELECT FOR UPDATE 上锁查 suppress_until > now."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT suppress_until FROM alert_dedup
                WHERE dedup_key = %s
                FOR UPDATE
                """,
                (dedup_key,),
            )
            row = cur.fetchone()
        if not row:
            return False
        (suppress_until,) = row
        # PG TIMESTAMPTZ -> aware datetime; tz-naive 视为已过期 (铁律 41 防御)
        if suppress_until is None or suppress_until.tzinfo is None:
            return False
        return suppress_until > now

    @staticmethod
    def _increment_dedup_count(
        conn: psycopg2.extensions.connection,
        dedup_key: str,
        alert: Alert,
        now: datetime,
    ) -> None:
        """deduped 路径: 仅 fire_count++ + last_title 更新, 不动 last_fired_at / suppress_until."""
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE alert_dedup
                SET fire_count = fire_count + 1,
                    last_title = %s
                WHERE dedup_key = %s
                """,
                (alert.title, dedup_key),
            )
            # row 必存在 (caller 已 SELECT FOR UPDATE 命中), 此处不验证 rowcount.

    @staticmethod
    def _upsert_dedup(
        conn: psycopg2.extensions.connection,
        dedup_key: str,
        alert: Alert,
        now: datetime,
        suppress_min: int,
        *,
        fired: bool,
    ) -> None:
        """sent 路径: ON CONFLICT 写新 suppress_until + 累加 fire_count.

        注: 即使 fired=False (sink_failed), 也写 row (caller raise + 标记 fire_count
        反映被尝试). 下次同 dedup_key 在 suppress 窗口内仍 dedup, 防 broken sink 风暴.
        """
        suppress_until = now + timedelta(minutes=suppress_min)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alert_dedup
                    (dedup_key, severity, source, last_fired_at,
                     suppress_until, fire_count, last_title)
                VALUES (%s, %s, %s, %s, %s, 1, %s)
                ON CONFLICT (dedup_key) DO UPDATE SET
                    severity = EXCLUDED.severity,
                    source = EXCLUDED.source,
                    last_fired_at = EXCLUDED.last_fired_at,
                    suppress_until = EXCLUDED.suppress_until,
                    fire_count = alert_dedup.fire_count + 1,
                    last_title = EXCLUDED.last_title
                """,
                (
                    dedup_key,
                    alert.severity.value,
                    alert.source,
                    now,
                    suppress_until,
                    alert.title,
                ),
            )

    def _dispatch(self, alert: Alert) -> tuple[bool, list[str]]:
        """逐 channel 发送, 收集失败原因. 任一成功即 sent_any=True."""
        sent_any = False
        failures: list[str] = []
        for ch in self._channels:
            try:
                ok = ch.send(alert)
            except Exception as e:  # noqa: BLE001
                # channel 抛异常 → 视为该 channel failed, 继续下一 channel (铁律 28).
                logger.exception(
                    "[AlertRouter] channel %s raised", getattr(ch, "name", "?")
                )
                failures.append(f"{getattr(ch, 'name', '?')}: {type(e).__name__}: {e}")
                continue
            if ok:
                sent_any = True
            else:
                failures.append(f"{getattr(ch, 'name', '?')}: send returned False")
        return sent_any, failures


# ────────────────── 全局单例 + factory ──────────────────

_router_singleton: PostgresAlertRouter | None = None
_singleton_lock = threading.Lock()


def get_alert_router() -> PostgresAlertRouter:
    """Lazy-init 全局 PostgresAlertRouter 单例.

    Application 调用方典型用法:
        from qm_platform.observability import get_alert_router, Alert, Severity
        router = get_alert_router()
        router.fire(Alert(...), dedup_key="...")

    测试需 reset 单例: alert._router_singleton = None 或调 reset_alert_router.
    """
    global _router_singleton
    if _router_singleton is None:
        with _singleton_lock:
            if _router_singleton is None:
                _router_singleton = PostgresAlertRouter()
    return _router_singleton


def reset_alert_router() -> None:
    """重置全局单例 (单测用)."""
    global _router_singleton
    with _singleton_lock:
        _router_singleton = None
