"""Risk Framework Application wiring — MVP 3.1 批 1 PR 3.

本模块是 Platform/App 边界的 wiring 层 (铁律 31 Engine 纯计算 + 铁律 34 Config SSOT):
  - Platform 层 (backend/platform/risk/) 只定 Protocol + concrete engine/rules
  - Application 层 (本模块) 把 QMTClient / send_alert / PaperBroker 按 DI 注入

daily_pipeline.risk_check 直接调 build_risk_engine(strategy_id, execution_mode)
获取一个 ready-to-run PlatformRiskEngine.

关联铁律: 24 (单一职责 wiring) / 31 (App 层允许 IO) / 33 (fail-loud send_alert) /
          34 (.env 配置 single source of truth)
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.core.qmt_client import get_qmt_client
from app.services.db import get_sync_conn
from app.services.notification_service import send_alert
from backend.platform.risk import PlatformRiskEngine
from backend.platform.risk.rules.pms import PMSRule, PMSThreshold
from backend.platform.risk.sources import DBPositionSource, QMTPositionSource

logger = logging.getLogger(__name__)


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


def build_risk_engine() -> PlatformRiskEngine:
    """构造 MVP 3.1 批 1 ready-to-run PlatformRiskEngine (PMSRule 已注册).

    调用方 (daily_pipeline.risk_check): 用返回 engine 调 build_context + run + execute.

    Returns:
        PlatformRiskEngine, 已 register PMSRule (阈值从 settings 读).
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
    logger.info(
        "[risk-wiring] PlatformRiskEngine built, rules=%s",
        engine.registered_rules,
    )
    return engine
