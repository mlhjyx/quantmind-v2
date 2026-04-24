"""Framework Risk — 统一风控规则引擎 (MVP 3.1 Wave 3 启动 MVP).

归属: Framework #6 Signal/Exec 子模块 (QPB v1.7 §Part 2). 替代 5 个独立监控系统
(PMS / intraday_monitor / risk_control_service / pt_audit / pt_watchdog) 互不通信的碎片,
统一为 RiskRule + PlatformRiskEngine + PositionSource Protocol + risk_event_log 单表.

批 1 (本模块 PR 2): Framework core + PMS L1-L3 迁入
批 2 (后续): intraday_monitor 3/5/8% + QMT disconnect 迁入
批 3 (后续, ADR-010 addendum 方案 C): CircuitBreakerRule adapter 接入

关联铁律: 24 (单一职责) / 31 (纯接口无 IO) / 33 (fail-loud) / 34 (Config SSOT) /
          38 (Blueprint 真相源) / 41 (timezone UTC)

Application 消费示例 (PR 3 daily_pipeline.risk_check):
    from backend.platform.risk import PlatformRiskEngine
    from backend.platform.risk.sources import QMTPositionSource, DBPositionSource
    from backend.platform.risk.rules.pms import PMSRule

    engine = PlatformRiskEngine(
        primary_source=QMTPositionSource(reader=qmt_client),
        fallback_source=DBPositionSource(conn_factory=get_conn),
        broker=get_broker(settings.EXECUTION_MODE),
        conn_factory=get_conn,
        notifier=dingding_notifier,
    )
    engine.register(PMSRule())
    ctx = engine.build_context(strategy_id=settings.PT_STRATEGY_ID)
    results = engine.run(ctx)
    engine.execute(results, ctx)
"""
from .engine import PlatformRiskEngine
from .interface import (
    Position,
    PositionSource,
    PositionSourceError,
    RiskContext,
    RiskRule,
    RuleResult,
)

__all__ = [
    "PlatformRiskEngine",
    "Position",
    "PositionSource",
    "PositionSourceError",
    "RiskContext",
    "RiskRule",
    "RuleResult",
]
