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
        """当前已注册 rule_id 列表 (按注册顺序, Python 3.7+ dict 保序)."""
        return list(self._rules.keys())

    def _resolve_rule_for(self, triggered_rule_id: str) -> RiskRule | None:
        """根据 RuleResult.rule_id 反查 root RiskRule (delegate _root_rule_id_via_rules)."""
        return _root_rule_id_via_rules(triggered_rule_id, self._rules)

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
        """分发 action: sell/alert_only/bypass + log + notify.

        reviewer P1-3 采纳: `_root_rule_id` hardcoded pms_l 反查改为 rule 层方法.
        """
        for result in results:
            rule = self._resolve_rule_for(result.rule_id)
            if rule is None:
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

        # reviewer P0-1 采纳: 删 explicit conn.commit(). 依赖 psycopg2 `with conn:`
        # context manager __exit__ 正常退出时 auto-commit, 异常时 rollback. 对齐
        # knowledge/registry.py 模式, 事务边界由 conn_factory 契约持有方管理.
        # MVP 3.4 batch 4 dual-write: outbox enqueue 在同 `with conn:` 块内 →
        # outbox + risk_event_log atomic (单 tx commit). publisher worker (batch 2)
        # 30s 后异步 publish 到 Redis Stream `qm:risk:{rule_id_action}` 替代 ad-hoc.
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
                # MVP 3.4 batch 4 dual-write: outbox event (atomic 同 risk_event_log INSERT)
                # event_type subtype = rule action (sell_full/alert_only/...) 拼回
                # "risk.{action}" stream. aggregate_id = "{code}-{rule_id}-{ts}" 唯一.
                try:
                    from qm_platform.observability import OutboxWriter  # noqa: PLC0415

                    OutboxWriter(conn).enqueue(
                        aggregate_type="risk",
                        aggregate_id=(
                            f"{result.code or 'portfolio'}-{result.rule_id}-"
                            f"{context.timestamp.isoformat()}"
                        ),
                        event_type=rule.action,
                        payload={
                            "risk_id": (
                                f"{result.code or 'portfolio'}-{result.rule_id}-"
                                f"{context.timestamp.isoformat()}"
                            ),
                            "strategy_id": context.strategy_id,
                            "execution_mode": context.execution_mode,
                            "rule_id": result.rule_id,
                            "severity": rule.severity.value,
                            "code": result.code,
                            "shares": result.shares,
                            "reason": result.reason,
                            "action_taken": rule.action,
                            "action_status": action_result.get("status", "unknown"),
                            "timestamp": context.timestamp.isoformat(),
                        },
                    )
                except Exception as outbox_exc:  # noqa: BLE001
                    # outbox 失败不阻塞 risk_event_log INSERT (主审计仍生效).
                    # 7 日 dual-write 观察期: 退役老 ad-hoc StreamBus 前必须 0 outbox 失败.
                    logger.warning(
                        "[risk-engine] outbox enqueue 失败 (dual-write 过渡期 silent_ok) "
                        "rule=%s exc=%s",
                        result.rule_id, type(outbox_exc).__name__, exc_info=True,
                    )
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


# reviewer P1-3 采纳: module-level `_root_rule_id` hardcoded pms_l 反查已废.
# 新设计: RiskRule.root_rule_id_for 方法 + _root_rule_id_via_rules 枚举调度.
def _root_rule_id_via_rules(
    triggered_rule_id: str, rules: dict[str, RiskRule]
) -> RiskRule | None:
    """遍历注册 rules 寻找 triggered_rule_id 的 root rule.

    算法 (v2, fixes ownership edge case):
        1. 直接 hit: triggered_rule_id ∈ rules → 该 rule
        2. 反查: 逐个 rule 调 `transformed = rule.root_rule_id_for(triggered_id)`;
           ownership 条件: transformed != triggered_id AND transformed == rule.rule_id.
           (默认 passthrough 返 triggered_id 不变, 不会被误判为 owner.)
        3. 都不中: None (execute 会 warning skip)
    """
    if triggered_rule_id in rules:
        return rules[triggered_rule_id]
    for rule in rules.values():
        transformed = rule.root_rule_id_for(triggered_rule_id)
        if transformed != triggered_rule_id and transformed == rule.rule_id:
            return rule
    return None
