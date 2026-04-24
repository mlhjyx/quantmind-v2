"""PlatformRiskEngine — Risk Framework 核心编排器 (MVP 3.1 批 1).

职责 (MVP_3_1_batch_1_plan.md §3.4):
  1. register(rule): rule_id 去重注册
  2. build_context(strategy_id): primary/fallback 加载 positions + 计算 portfolio_nav
  3. run(context): 分发给所有 rule.evaluate, 收集 RuleResult
  4. execute(results, context): 按 action 分发 (sell → broker.sell / alert_only → notify only),
                                 写 risk_event_log + 发钉钉

Platform/App 边界:
  - broker / notifier / conn_factory / price_reader 全部 DI 注入, 不 import app.*
  - risk_event_log INSERT 是必须的 DB IO, 对齐 MVP 1.3b Platform 允许 DAL-like 访问模式
    (knowledge/registry.py 同模式: conn_factory 注入 + 内部直接 INSERT)

关联铁律: 17 (本表有 DataPipeline 例外: 单 writer subset cols ON CONFLICT DO UPDATE
            不适用, 因每次都是新 UUID INSERT 非 upsert) /
          22 / 24 / 31 (规则层纯计算, 本 engine 层允许 IO) / 33 / 34 / 41
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Protocol

from .interface import (
    Position,
    PositionSource,
    PositionSourceError,
    RiskContext,
    RiskRule,
    RuleResult,
)

logger = logging.getLogger(__name__)


# ---------- Broker / Notifier Protocol (DI) ----------


class BrokerProtocol(Protocol):
    """Broker 抽象 (执行层, QMT 或 paper_broker).

    Platform 不直 import xtquant. Application 层 wire 时注入具体实现.
    """

    def sell(
        self, code: str, shares: int, reason: str, timeout: float = 5.0
    ) -> dict[str, Any]:
        """市价卖出 N 股. 超时 / 失败时 raise 或 return {'status': 'error', ...}."""
        ...


class NotifierProtocol(Protocol):
    """钉钉 / 通知抽象."""

    def send(self, title: str, text: str, severity: str = "warning") -> None:
        """发送告警. 失败 silent (notifier 内部 log warning), 不阻塞 Engine."""
        ...


class PriceReaderProtocol(Protocol):
    """批量价格读取 (Redis market:latest 共享)."""

    def get_prices(self, codes: list[str]) -> dict[str, float]:
        """返 {code: current_price}, 失败返 {}."""
        ...

    def get_nav(self) -> dict[str, Any] | None:
        """Redis portfolio:nav → {cash, total_value, ...}. 失败返 None."""
        ...


# ---------- PlatformRiskEngine ----------


class PlatformRiskEngine:
    """Risk Framework 核心编排器.

    Args:
        primary_source: QMTPositionSource (推荐) 或其他 primary 持仓源
        fallback_source: DBPositionSource 或其他 fallback
        broker: 执行 action=sell 时调用
        notifier: 钉钉等告警通道
        price_reader: Redis 价格+NAV 读取器 (获取 portfolio_nav)
        conn_factory: callable → psycopg2 conn (risk_event_log INSERT + 日志)
    """

    def __init__(
        self,
        primary_source: PositionSource,
        fallback_source: PositionSource,
        broker: BrokerProtocol,
        notifier: NotifierProtocol,
        price_reader: PriceReaderProtocol,
        conn_factory,
    ):
        self._primary = primary_source
        self._fallback = fallback_source
        self._broker = broker
        self._notifier = notifier
        self._price_reader = price_reader
        self._conn_factory = conn_factory
        self._rules: dict[str, RiskRule] = {}

    # ---------- 规则注册 ----------

    def register(self, rule: RiskRule) -> None:
        """注册规则. rule_id 重复 raise ValueError."""
        if rule.rule_id in self._rules:
            raise ValueError(
                f"RiskRule rule_id={rule.rule_id!r} already registered "
                f"(existing={type(self._rules[rule.rule_id]).__name__})"
            )
        self._rules[rule.rule_id] = rule
        logger.info(
            "[risk-engine] registered rule_id=%s cls=%s severity=%s action=%s",
            rule.rule_id,
            type(rule).__name__,
            rule.severity.value,
            rule.action,
        )

    @property
    def registered_rules(self) -> list[str]:
        """当前已注册 rule_id 列表 (only 测试用, 不保证顺序稳定)."""
        return list(self._rules.keys())

    # ---------- Context 构建 ----------

    def _load_positions(self, strategy_id: str, execution_mode: str) -> list[Position]:
        """Primary → Fallback 切换逻辑. 两个都挂 raise PositionSourceError."""
        try:
            return self._primary.load(strategy_id, execution_mode)
        except PositionSourceError as e:
            logger.warning(
                "[risk-engine] primary source failed, switching to fallback: %s", e
            )
            self._notifier.send(
                title="[risk] primary position source failed",
                text=f"{type(self._primary).__name__} raised {type(e).__name__}: {e}. "
                f"Falling back to {type(self._fallback).__name__}.",
                severity="p1",
            )
            # fallback 自身失败原样 raise, 不再 fallback 再 fallback
            return self._fallback.load(strategy_id, execution_mode)

    def build_context(self, strategy_id: str, execution_mode: str) -> RiskContext:
        """构造 RiskContext. 含 primary/fallback 切换 + portfolio_nav 拉取.

        Args:
            strategy_id: 策略 UUID.
            execution_mode: 'paper' | 'live'.

        Returns:
            RiskContext (frozen, 不可变).

        Raises:
            PositionSourceError: primary + fallback 都挂.
        """
        positions = self._load_positions(strategy_id, execution_mode)

        nav_blob = self._price_reader.get_nav()
        if nav_blob and "total_value" in nav_blob:
            portfolio_nav = float(nav_blob["total_value"])
        else:
            # fallback: 用 shares × current_price 估算 (prev_close_nav 批 2 再加)
            portfolio_nav = sum(p.shares * p.current_price for p in positions)
            logger.warning(
                "[risk-engine] NAV unavailable from price_reader, using "
                "sum(shares*current)=%.2f (approx, cash 未含)",
                portfolio_nav,
            )

        return RiskContext(
            strategy_id=strategy_id,
            execution_mode=execution_mode,
            timestamp=datetime.now(UTC),
            positions=tuple(positions),  # tuple 保 frozen
            portfolio_nav=portfolio_nav,
            prev_close_nav=None,  # 批 2 intraday 规则再用
        )

    # ---------- 规则执行 ----------

    def run(self, context: RiskContext) -> list[RuleResult]:
        """遍历所有规则 .evaluate, 收集 RuleResult."""
        all_results: list[RuleResult] = []
        for rule_id, rule in self._rules.items():
            try:
                rule_results = rule.evaluate(context)
            except Exception as e:  # noqa: BLE001 — rule 内部异常降为 log, 非终止其他 rule
                logger.error(
                    "[risk-engine] rule %s evaluate() raised %s: %s",
                    rule_id,
                    type(e).__name__,
                    e,
                    exc_info=True,
                )
                self._notifier.send(
                    title=f"[risk] rule {rule_id} evaluation failed",
                    text=f"{type(e).__name__}: {e}",
                    severity="p1",
                )
                continue
            all_results.extend(rule_results)
        return all_results

    def execute(self, results: list[RuleResult], context: RiskContext) -> None:
        """分发 action: sell/alert_only/bypass + log + notify."""
        for result in results:
            rule = self._rules.get(_root_rule_id(result.rule_id))
            if rule is None:
                # 例: RuleResult.rule_id="pms_l1" 基础规则是 "pms"
                # 找不到 root 则降级 warning, 不阻塞其他 result
                logger.warning(
                    "[risk-engine] RuleResult.rule_id=%s root rule not found, skipping",
                    result.rule_id,
                )
                continue

            action_result: dict[str, Any] = {"status": "noop"}
            if rule.action == "sell":
                action_result = self._execute_sell(result, rule)
            elif rule.action == "alert_only":
                action_result = {"status": "alert_only"}
            elif rule.action == "bypass":
                action_result = {"status": "bypass"}

            self._log_event(result, rule, context, action_result)

            if rule.action in ("sell", "alert_only"):
                self._notify(result, rule, context, action_result)

    def _execute_sell(self, result: RuleResult, rule: RiskRule) -> dict[str, Any]:
        """直调 broker.sell, 返 {status, ...}. 失败不 raise (继续其他 result)."""
        try:
            fill = self._broker.sell(
                code=result.code,
                shares=result.shares,
                reason=f"risk:{result.rule_id}",
                timeout=5.0,
            )
            logger.info(
                "[risk-engine] sell executed rule=%s code=%s shares=%d fill=%s",
                result.rule_id, result.code, result.shares, fill,
            )
            return {"status": "sell_executed", **fill}
        except Exception as e:  # noqa: BLE001
            logger.error(
                "[risk-engine] broker.sell failed rule=%s code=%s shares=%d: %s: %s",
                result.rule_id, result.code, result.shares,
                type(e).__name__, e, exc_info=True,
            )
            return {
                "status": "sell_failed",
                "error_type": type(e).__name__,
                "error_msg": str(e),
            }

    def _log_event(
        self,
        result: RuleResult,
        rule: RiskRule,
        context: RiskContext,
        action_result: dict[str, Any],
    ) -> None:
        """INSERT INTO risk_event_log. 失败 log error + 不 raise (主路径已 sell, DB 后补)."""
        context_snapshot = {
            "positions": [
                {
                    "code": p.code,
                    "shares": p.shares,
                    "entry_price": p.entry_price,
                    "peak_price": p.peak_price,
                    "current_price": p.current_price,
                }
                for p in context.positions
            ],
            "portfolio_nav": context.portfolio_nav,
            "timestamp": context.timestamp.isoformat(),
            "metrics": result.metrics,
        }

        try:
            with self._conn_factory() as conn, conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO risk_event_log
                    (strategy_id, execution_mode, rule_id, severity,
                     code, shares, reason, context_snapshot, action_taken, action_result)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb)""",
                    (
                        context.strategy_id,
                        context.execution_mode,
                        result.rule_id,
                        rule.severity.value,
                        result.code,
                        result.shares,
                        result.reason,
                        json.dumps(context_snapshot, default=str),
                        rule.action,
                        json.dumps(action_result, default=str),
                    ),
                )
                conn.commit()
        except Exception as e:  # noqa: BLE001 — log 失败不阻塞主路径
            logger.error(
                "[risk-engine] risk_event_log INSERT failed rule=%s: %s: %s",
                result.rule_id, type(e).__name__, e, exc_info=True,
            )

    def _notify(
        self,
        result: RuleResult,
        rule: RiskRule,
        context: RiskContext,
        action_result: dict[str, Any],
    ) -> None:
        """发钉钉. 失败 silent (notifier 自行 log)."""
        title = f"[risk:{rule.severity.value}] {result.rule_id} — {result.code or 'PORTFOLIO'}"
        text = (
            f"{result.reason}\n\n"
            f"Strategy: {context.strategy_id}\n"
            f"ExecMode: {context.execution_mode}\n"
            f"Action: {rule.action} → {action_result.get('status', '?')}\n"
            f"Timestamp: {context.timestamp.isoformat()}"
        )
        self._notifier.send(title=title, text=text, severity=rule.severity.value)


def _root_rule_id(triggered_rule_id: str) -> str:
    """从 RuleResult.rule_id 反推 root RiskRule.rule_id.

    约定: PMSRule.rule_id="pms", 触发时 RuleResult.rule_id="pms_l1"/"pms_l2"/"pms_l3".
    其他规则 rule_id 与 RuleResult.rule_id 一致 (如 "intraday_portfolio_drop_5pct").

    算法: 找 "_" 分隔第一段, 若匹配已注册则用, 否则 fallback 用完整 id.
    (未来扩展更严格的 rule_id 映射需 rule base class 增字段.)
    """
    # Special case: pms_l{N} → pms
    if triggered_rule_id.startswith("pms_l") and triggered_rule_id[5:].isdigit():
        return "pms"
    return triggered_rule_id
