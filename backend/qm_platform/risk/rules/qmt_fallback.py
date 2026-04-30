"""QMTFallbackTriggeredRule — T0-15 LL-081 guard v2 扩范围.

T0-15 来源: PR #166 SHUTDOWN_NOTICE §6 + D3-A Step 4 修订 v2 (PR #163 L4 NEW v2).

原 LL-081 guard (QMTDisconnectRule, intraday.py:176) 仅 cover `is_connected()=False`.
但 D3-B F-D3B-7 + D3-A Step 4 修订 v2 实测发现:
  - portfolio:current Redis cache = 0 keys (qmt_data_service 26 天 silent skip)
  - QMTClient.is_connected() 仍可能 True (TCP 连接可能存在但 sync loop 死)
  - QMTClient fallback 路径触发 → 直读 stale DB position_snapshot self-loop
  - DB 4-28 stale 19 行持续 6+ 天没人察觉

本 Rule 扩 LL-081 v2 cover:
  - portfolio:current Redis cache 0 keys (即使 QMT TCP 连通) → 视 fallback 触发 → P0 alert
  - 与 QMTDisconnectRule 独立运行 (intraday Beat 同 schedule, 5min cron)

Action: alert_only (与 QMTDisconnect 一致, 仅人工介入)
Severity: P0 (基础设施 silent drift, 沿用 LL-081 v1 严重度)

dedup: 沿用 dingtalk_alert.send_with_dedup, dedup_key='ll081_qmt_fallback_triggered',
P0 severity 默认 5min suppress.

关联铁律:
  - 17 (DataPipeline): 例外, rule 纯计算, dedup 在 wiring 层
  - 31 (纯规则 delegate Protocol): RedisCacheHealthReader Protocol 注入
  - 33 (fail-loud): cache 0 keys → 不 silent skip, 真 alert
  - 41 (UTC tz-aware)

关联 LL: LL-091 (推论必标 P3-FOLLOWUP) + LL-097 (X9 schedule restart)
"""
from __future__ import annotations

from typing import Literal, Protocol

from backend.qm_platform._types import Severity

from ..interface import RiskContext, RiskRule, RuleResult


class RedisCacheHealthReader(Protocol):
    """portfolio:current Redis cache 健康度读取契约.

    实现必须实测 Redis KEYS "portfolio:*" count (read-only).
    单测 mock 注入, 生产用 redis-cli wrapper.

    Note: 非 @runtime_checkable (沿用 QMTConnectionReader pattern, intraday.py:36-38).
    """

    def get_portfolio_cache_key_count(self) -> int:
        """返 portfolio:current Redis cache key 数量.

        0 = qmt_data_service silent drift (sync loop 死), QMTClient 走 fallback DB 路径.
        ≥ 1 = qmt_data_service 正常 sync.
        """
        ...


class QMTFallbackTriggeredRule(RiskRule):
    """QMT fallback 触发告警 (T0-15 LL-081 v2 扩范围).

    触发条件: RedisCacheHealthReader.get_portfolio_cache_key_count() == 0
    Action: alert_only (与 QMTDisconnectRule 一致)
    Severity: P0

    与 QMTDisconnectRule 区别:
      - QMTDisconnectRule: TCP 连接断 (is_connected=False)
      - QMTFallbackTriggeredRule: TCP 连通但 sync loop 死 (cache 0 keys)
      两者并行运行, 互补 cover. D3-A Step 4 实测 4-30 14:54 真账户场景:
        QMTClient.is_connected() 状态可能 True 但 portfolio:current 已 0 keys 26 天.

    防泛滥:
      - Rule 本身不 dedup (纯计算)
      - dedup 在 wiring 层 (dingtalk_alert.send_with_dedup, dedup_key='ll081_qmt_fallback_triggered')
      - P0 severity 默认 5min suppress (alert_dedup TTL 驱动)
    """

    rule_id: str = "ll081_qmt_fallback_triggered"
    severity: Severity = Severity.P0
    action: Literal["sell", "alert_only", "bypass"] = "alert_only"

    def __init__(self, cache_reader: RedisCacheHealthReader) -> None:
        """注入 RedisCacheHealthReader (Protocol), 单测可 mock."""
        self._reader = cache_reader

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        """检查 portfolio:current Redis cache, 0 keys 返 1 RuleResult, 否则 []."""
        key_count = self._reader.get_portfolio_cache_key_count()
        if key_count > 0:
            return []

        return [
            RuleResult(
                rule_id=self.rule_id,
                code="",  # 基础设施级, 非单股
                shares=0,  # alert_only
                reason=(
                    "QMT Data Service silent drift detected: portfolio:current "
                    "Redis cache = 0 keys (qmt_data_service sync loop 死). "
                    "QMTClient fallback 路径触发 → 直读 stale DB position_snapshot. "
                    "T0-15 LL-081 v2 扩范围 cover (沿用 D3-A Step 4 修订 v2 实测). "
                    "需人工 Servy restart QuantMind-QMTData + 验证 sync 恢复."
                ),
                metrics={
                    "checked_at_timestamp": context.timestamp.timestamp(),
                    "portfolio_cache_key_count": key_count,
                    "positions_count_at_check": len(context.positions),
                    "portfolio_nav_at_check": context.portfolio_nav,
                },
            )
        ]
