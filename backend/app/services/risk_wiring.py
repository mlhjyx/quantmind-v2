"""Risk Framework Application wiring — MVP 3.1 批 1/2.

本模块是 Platform/App 边界的 wiring 层 (铁律 31 Engine 纯计算 + 铁律 34 Config SSOT):
  - Platform 层 (backend/platform/risk/) 只定 Protocol + concrete engine/rules
  - Application 层 (本模块) 把 QMTClient / send_alert / PaperBroker 按 DI 注入

工厂函数:
  - build_risk_engine() (批 1): PMS L1/L2/L3 日检, daily_pipeline.risk_check 14:30
  - build_intraday_risk_engine() (批 2): + 4 intraday rules (3/5/8% + QMT disconnect),
    daily_pipeline.intraday_risk_check 5min 盘中
  - IntradayAlertDedup (批 2): Redis 24h TTL 同 rule_id 同日限 1 次告警防泛滥

关联铁律: 24 (单一职责 wiring) / 31 (App 层允许 IO) / 33 (fail-loud send_alert) /
          34 (.env 配置 single source of truth)
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import redis

from app.config import settings
from app.core.qmt_client import get_qmt_client
from app.services.db import get_sync_conn
from app.services.notification_service import send_alert
from backend.qm_platform.risk import PlatformRiskEngine, RiskRule
from backend.qm_platform.risk.rules.circuit_breaker import CircuitBreakerRule
from backend.qm_platform.risk.rules.holding_time import PositionHoldingTimeRule
from backend.qm_platform.risk.rules.intraday import (
    IntradayPortfolioDrop3PctRule,
    IntradayPortfolioDrop5PctRule,
    IntradayPortfolioDrop8PctRule,
    QMTDisconnectRule,
)
from backend.qm_platform.risk.rules.new_position import NewPositionVolatilityRule
from backend.qm_platform.risk.rules.pms import PMSRule, PMSThreshold
from backend.qm_platform.risk.rules.single_stock import SingleStockStopLossRule
from backend.qm_platform.risk.sources import DBPositionSource, QMTPositionSource

logger = logging.getLogger(__name__)

# reviewer P2 采纳 (code): 铁律 41 timezone 统一 — dedup key + SQL trade_date 对比
# 均用北京时间 (A 股市场), 防 OS/PG 时区漂移导致日边界错位.
_CHINA_TZ = ZoneInfo("Asia/Shanghai")


# ---------- Broker Adapter (批 1: logging-only, 批 2 接真 QMT/Paper) ----------


class LoggingSellBroker:
    """批 1 占位 broker — 不实盘卖出, 仅 log + 写 risk_event_log (action_result).

    决策背景: 老 `pms_engine.pms_daily_check_task` 也只调 `record_trigger` 不 sell
    (历史实现 sell 由 StreamBus 下游消费, 现 F27 去重已废). 批 1 保持老语义, 批 2 接
    真 broker 时换 QMTSellBroker / PaperBrokerSellAdapter, RiskRule + Engine 代码不动
    (铁律 23 独立可执行 + Protocol DI 解耦).

    符合 engine.BrokerProtocol.sell 契约.
    """

    def sell(
        self, code: str, shares: int, reason: str, timeout: float = 5.0
    ) -> dict[str, Any]:
        """批 1 占位: 不实盘, 返 status='logged_only'. risk_event_log 仍记录完整触发."""
        logger.warning(
            "[risk-wiring] LoggingSellBroker placeholder: code=%s shares=%d reason=%s "
            "(批 1 仅记录, 批 2 接真 broker)",
            code, shares, reason,
        )
        return {
            "status": "logged_only",
            "note": "MVP 3.1 批 1 placeholder, real sell in 批 2",
            "code": code,
            "shares": shares,
        }


# ---------- Notifier Adapter (复用 send_alert) ----------


class DingTalkRiskNotifier:
    """wrap send_alert 符合 engine.NotifierProtocol.send 契约.

    Severity 映射: P0/P1/P2/info → notification_service level 字段 (大写).
    """

    _SEVERITY_MAP = {
        "p0": "P0",
        "p1": "P1",
        "p2": "P2",
        "info": "P2",  # info 归并 P2 (send_alert 不识 info)
        "warning": "P1",  # 兼容 engine._load_positions fallback 告警
    }

    def send(self, title: str, text: str, severity: str = "warning") -> None:
        """发钉钉. 失败 silent (send_alert 内部 try/except 已 log, 铁律 33-c 读路径)."""
        level = self._SEVERITY_MAP.get(severity.lower(), "P1")
        try:
            send_alert(
                level=level,
                title=title,
                content=text,
                webhook_url=settings.DINGTALK_WEBHOOK_URL,
                secret=settings.DINGTALK_SECRET,
                conn=None,  # 不写 DB, risk_event_log 由 engine._log_event 处理
            )
        except Exception as e:  # noqa: BLE001 — 通知失败不阻塞 Engine 主路径
            logger.warning(
                "[risk-wiring] DingTalkRiskNotifier send failed: %s: %s",
                type(e).__name__, e,
            )


# ---------- Engine Factory ----------


def build_pms_thresholds() -> tuple[PMSThreshold, ...]:
    """从 settings 读 PMS L1/L2/L3 阈值, 构造 PMSThreshold tuple (铁律 34 SSOT).

    老 pms_engine.check_protection hardcoded 对齐 settings, 新 Framework 通过 ctor 注入.
    """
    return (
        PMSThreshold(
            level=1,
            min_gain=settings.PMS_LEVEL1_GAIN,
            max_drawdown=settings.PMS_LEVEL1_DRAWDOWN,
        ),
        PMSThreshold(
            level=2,
            min_gain=settings.PMS_LEVEL2_GAIN,
            max_drawdown=settings.PMS_LEVEL2_DRAWDOWN,
        ),
        PMSThreshold(
            level=3,
            min_gain=settings.PMS_LEVEL3_GAIN,
            max_drawdown=settings.PMS_LEVEL3_DRAWDOWN,
        ),
    )


def build_risk_engine(
    extra_rules: list[RiskRule] | None = None,
) -> PlatformRiskEngine:
    """构造 MVP 3.1 批 1 ready-to-run PlatformRiskEngine (PMSRule 已注册).

    调用方 (daily_pipeline.risk_check): 用返回 engine 调 build_context + run + execute.

    reviewer P2-1 采纳 (architect): `extra_rules` 可选参为批 2/3 铺路.
      - 批 2 加 IntradayMonitorRule: `build_risk_engine(extra_rules=[IntradayMonitorRule(...)])`
      - 批 3 加 CircuitBreakerRule adapter 同上
      - 集成测试可注入 mock rule 绕真 PMSRule 路径
    不采纳 hardcoded register 改造 (铁律 23 独立可执行, 批 1 最小改动).

    Args:
        extra_rules: 可选附加 RiskRule list, 在默认 PMSRule 之后顺序 register.

    Returns:
        PlatformRiskEngine, 已 register PMSRule + extra_rules (阈值从 settings 读).
    """
    qmt_client = get_qmt_client()
    primary = QMTPositionSource(reader=qmt_client, conn_factory=get_sync_conn)
    fallback = DBPositionSource(conn_factory=get_sync_conn, price_reader=qmt_client)

    engine = PlatformRiskEngine(
        primary_source=primary,
        fallback_source=fallback,
        broker=LoggingSellBroker(),
        notifier=DingTalkRiskNotifier(),
        price_reader=qmt_client,
        conn_factory=get_sync_conn,
    )
    engine.register(PMSRule(levels=build_pms_thresholds()))
    # MVP 3.1b Phase 1 (Session 44, 2026-04-29): 单股止损规则补全 (PMS 互补).
    # PMS 保护"涨完回撤" (浮盈 ≥ 10/20/30% AND 回撤 ≥ 10/12/15%),
    # SingleStockStopLossRule 保护"买入即跌" (loss ≥ 10/15/20/25%).
    # 真生产事件: 卓然股份 -29% / 南玻 -9.75% PMS 0 触发 (无浮盈), 缺单股层规则.
    # 默认 action='alert_only' (不自动 sell, 钉钉告警 + 用户决策).
    engine.register(SingleStockStopLossRule())
    # MVP 3.1b Phase 1.5b (Session 44): 时间维度补全 — 与 P&L 维度互补.
    #   - PositionHoldingTimeRule (P2): holding_days >= 30 天告警 (长尾持仓 review)
    #   - NewPositionVolatilityRule (P1): holding_days <= 7 天 + |loss| > 5% 告警
    #     (买入即跌的早期预警, 比 SingleStock L1 -10% 提前)
    # 两规则依赖 Phase 1.5a Position.entry_date (PR #147), entry_date is None
    # silent skip (旧持仓 backfill 缺数据).
    engine.register(PositionHoldingTimeRule())
    engine.register(NewPositionVolatilityRule())
    for rule in (extra_rules or []):
        engine.register(rule)
    logger.info(
        "[risk-wiring] PlatformRiskEngine built, rules=%s",
        engine.registered_rules,
    )
    return engine


# ══════════════════════════════════════════════════════════════════════════
# MVP 3.1 批 2 (Session 30) — Intraday Risk Engine + Dedup + NAV helper
# ══════════════════════════════════════════════════════════════════════════


def _load_prev_close_nav(
    conn: Any, strategy_id: str, execution_mode: str
) -> float | None:
    """从 performance_series 读前一交易日 NAV 作 prev_close_nav (intraday rules 用).

    查询: `SELECT nav FROM performance_series WHERE strategy_id=%s AND execution_mode=%s
           AND trade_date < %s ORDER BY trade_date DESC LIMIT 1`

    reviewer P2 采纳 (code): 显式传北京时间 today_date 替 SQL `CURRENT_DATE`, 防 PG server
    timezone 漂移与 Python `date.today()` 日边界错位 (铁律 41 timezone 统一).
    reviewer P2 采纳 (python): `conn` 加 Any type hint (避 psycopg2 硬依赖).
    reviewer P3 采纳 (python): warning log 移入 with block 内, 语义更清晰.

    Args:
        conn: psycopg2 connection (Any 避免硬类型依赖; 调用方管理事务).
        strategy_id: 策略 UUID.
        execution_mode: 'paper' | 'live' (ADR-008 命名空间).

    Returns:
        float: 前日 NAV (非当日), None: 数据缺失 / 首日 / 异常.
    """
    today_cn = datetime.now(_CHINA_TZ).date()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT nav FROM performance_series
                WHERE strategy_id = %s AND execution_mode = %s
                  AND trade_date < %s
                ORDER BY trade_date DESC
                LIMIT 1""",
                (strategy_id, execution_mode, today_cn),
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                nav = float(row[0])
                if nav > 0:
                    return nav
            logger.warning(
                "[risk-wiring] prev_close_nav 数据缺失 strategy=%s mode=%s today_cn=%s",
                strategy_id, execution_mode, today_cn,
            )
    except Exception as e:  # noqa: BLE001 — 读路径 fallback 允许 (铁律 33-c)
        logger.error(
            "[risk-wiring] _load_prev_close_nav 异常 strategy=%s mode=%s: %s: %s",
            strategy_id, execution_mode, type(e).__name__, e,
        )
    return None


class IntradayAlertDedup:
    """Redis 24h TTL dedup — 同 rule_id × 同 strategy × 同 mode × 同日限 1 次告警.

    防泛滥场景 (plan §5):
      - QMT 持续断连 → 每 5min trigger QMTDisconnectRule → 钉钉 DoS (54 次/日)
      - 盘中持续深跌 → 3%/5%/8% 可能同日多次进出阈值 → 重复告警

    Key pattern: `qm:risk:dedup:{rule_id}:{strategy_id}:{execution_mode}:{YYYY-MM-DD}`
    Value: 触发 timestamp (debug 用, 功能上只判存在)
    TTL: 24h (86400s), 自动清理

    使用方式 (daily_pipeline.intraday_risk_check_task):
        dedup = IntradayAlertDedup()
        for result in results:
            if dedup.should_alert(result.rule_id, strategy_id, execution_mode):
                engine.execute([result], context)  # log + 钉钉 + risk_event_log
                dedup.mark_alerted(result.rule_id, strategy_id, execution_mode)
    """

    _TTL_SECONDS = 86400  # 24h

    def __init__(self, redis_client: redis.Redis | None = None):
        """Args:
            redis_client: Optional 注入 (单测), 默认从 settings.REDIS_URL 构造.

        reviewer P2 采纳 (python): redis_client type hint 明示契约.
        """
        if redis_client is None:
            redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self._redis = redis_client

    @staticmethod
    def _build_key(rule_id: str, strategy_id: str, execution_mode: str) -> str:
        """dedup key 构造. 按日期自然过期 (24h TTL 覆盖单交易日).

        reviewer P2 采纳 (code): 铁律 41 timezone 显式北京时间, 防 OS-local date drift.
        """
        today = datetime.now(_CHINA_TZ).date().isoformat()
        return f"qm:risk:dedup:{rule_id}:{strategy_id}:{execution_mode}:{today}"

    def should_alert(
        self, rule_id: str, strategy_id: str, execution_mode: str
    ) -> bool:
        """判断是否应发告警. True = 未 mark 过 (首次) / Redis 异常 fail-open."""
        key = self._build_key(rule_id, strategy_id, execution_mode)
        try:
            return not self._redis.exists(key)
        except Exception as e:  # noqa: BLE001 — Redis 失败 fail-open (宁可误告警不漏告警)
            logger.error(
                "[risk-wiring] IntradayAlertDedup.should_alert Redis 异常 key=%s: %s: %s "
                "(fail-open, 允许告警)",
                key, type(e).__name__, e,
            )
            return True

    def mark_alerted(
        self, rule_id: str, strategy_id: str, execution_mode: str
    ) -> None:
        """标记已告警. 失败 silent (dedup 失败不应阻塞主路径, 铁律 33-c).

        reviewer P2 采纳 (python): `import time` 已提到模块顶层, 不再 lazy.
        """
        key = self._build_key(rule_id, strategy_id, execution_mode)
        try:
            self._redis.setex(key, self._TTL_SECONDS, str(int(time.time())))
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "[risk-wiring] IntradayAlertDedup.mark_alerted Redis 异常 key=%s: %s: %s",
                key, type(e).__name__, e,
            )


def build_intraday_risk_engine(
    extra_rules: list[RiskRule] | None = None,
) -> PlatformRiskEngine:
    """构造 MVP 3.1 批 2 intraday PlatformRiskEngine (4 rules 已注册).

    规则 (ADR-010 D5 迁移表批 2 行):
      - IntradayPortfolioDrop3PctRule (P2)
      - IntradayPortfolioDrop5PctRule (P1)
      - IntradayPortfolioDrop8PctRule (P0)
      - QMTDisconnectRule (P0, 注入 QMTClient.is_connected)

    调用方 (daily_pipeline.intraday_risk_check_task): build → context → run → dedup → execute.

    Note: **不** 注册 PMSRule (PMS 归批 1 daily 14:30 专属, 避免双告警).

    Args:
        extra_rules: 可选附加 RiskRule list (批 3 CB adapter 可注入).

    Returns:
        PlatformRiskEngine, 已 register 4 intraday rules + extra_rules.
    """
    qmt_client = get_qmt_client()
    primary = QMTPositionSource(reader=qmt_client, conn_factory=get_sync_conn)
    fallback = DBPositionSource(conn_factory=get_sync_conn, price_reader=qmt_client)

    engine = PlatformRiskEngine(
        primary_source=primary,
        fallback_source=fallback,
        broker=LoggingSellBroker(),  # 批 2 仍占位 (所有 intraday rules action='alert_only')
        notifier=DingTalkRiskNotifier(),
        price_reader=qmt_client,
        conn_factory=get_sync_conn,
    )
    engine.register(IntradayPortfolioDrop3PctRule())
    engine.register(IntradayPortfolioDrop5PctRule())
    engine.register(IntradayPortfolioDrop8PctRule())
    engine.register(QMTDisconnectRule(qmt_reader=qmt_client))
    # MVP 3.1b Phase 1 (Session 44): 单股止损规则补全 (intraday 5min 高频复用).
    # 与 build_risk_engine (daily 14:30) 双频检查 — 任一频率触发都告警.
    # 卓然 -29% 真生产事件如果 SingleStockStopLossRule 已上线 → intraday 5min 必触发 P0.
    engine.register(SingleStockStopLossRule())
    for rule in (extra_rules or []):
        engine.register(rule)
    logger.info(
        "[risk-wiring] Intraday PlatformRiskEngine built, rules=%s",
        engine.registered_rules,
    )
    return engine


# ══════════════════════════════════════════════════════════════════════════
# MVP 3.1 批 3 (Session 30 末) — CircuitBreaker Rule Adapter Factory
# ══════════════════════════════════════════════════════════════════════════


def build_circuit_breaker_rule() -> CircuitBreakerRule:
    """构造 CircuitBreakerRule 实例 (方案 C Hybrid adapter, ADR-010 addendum).

    使用方式 (daily_pipeline.risk_daily_check_task):
        engine = build_risk_engine(extra_rules=[build_circuit_breaker_rule()])
        # Engine 顺序 register: PMSRule → CircuitBreakerRule
        # 14:30 daily 跑时两 rule 并列评估 (PMS 个股级 + CB 组合级)

    **不** 挂批 2 intraday (5min × 72 次/日) — CB 阈值日频语义 + check_circuit_breaker_sync
    内部 DB commit 频率放大. 批 3b 若需盘中触发, 抽 read-only passive check 分离.

    Returns:
        CircuitBreakerRule, 注入 get_sync_conn + settings.PAPER_INITIAL_CAPITAL SSOT.
    """
    return CircuitBreakerRule(
        conn_factory=get_sync_conn,
        initial_capital=settings.PAPER_INITIAL_CAPITAL,
    )
