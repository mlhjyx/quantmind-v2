"""CircuitBreakerRule — 薄 Hybrid adapter 包老 risk_control_service 接入 Platform Risk Engine.

MVP 3.1 批 3 (Session 30 末). ADR-010 addendum 方案 C 明确决策: 不重写 1640 行
`risk_control_service.py` async state machine (批 0 spike 识别 4 大冲突), 仅新增
~200 行 adapter, 调 sync API `check_circuit_breaker_sync` (L1349), diff pre/post snapshot
推导 transition, 仅在 level 变化时返 RuleResult 入 `risk_event_log` 统一审计.

⚠️ **铁律 31 例外声明** (ADR-010 addendum Decision §Positive):
  标准铁律 31 要求 `backend/platform/**` 纯计算, 不 IO. 本模块是 Hybrid adapter
  特例 — `evaluate` 调 `check_circuit_breaker_sync` 内部 DB commit + 通知, 违反
  纯计算原则. 接受理由: 重写 1640 行 async → sync 风险 >> 违反 P31 代价. Sunset
  gate (A+B+C 满足后批 3b inline 重审) 消此例外.

对齐批 1 PMSRule 设计模式:
  - 单类多 rule_id (RuleResult.rule_id 动态 `cb_escalate_l{N}` / `cb_recover_l{N}`)
  - `root_rule_id_for` 反查 root `"circuit_breaker"`
  - action='alert_only' (CB 通过 signal_engine get_position_multiplier 影响下游
    sizing, Risk Engine 仅记事件 + 钉钉, 非 Engine 调 broker)

关联铁律: 24 (单一职责 adapter) / 31 **例外** / 33 (fail-loud level 变化入 log) /
          34 (initial_capital SSOT) / 36 (precondition 1640 行核查已完成 Session 27)
"""
from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import Any, Literal

# MEDIUM reviewer 采纳 (Session 31 PR #63): psycopg2.errors module-top 对齐既有
# `_check_cb_sync` import guard pattern, 消除每次 _read_current_level 调用 import
# resolution overhead, Platform→psycopg2 依赖边界显式 (铁律 31 例外 wiring 层必要代价)
import psycopg2.errors

from backend.qm_platform._types import Severity

from ..interface import RiskContext, RiskRule, RuleResult

# reviewer P3-2 采纳 (python): module-level import 替 lazy evaluate import (避免每次
# evaluate 跑 import machinery + 使 Platform→App 反向依赖显式). 用 try/except guard
# 处理测试/工具场景 app 模块不可用 (虽生产路径总有). 铁律 31 例外 wiring 层的必要代价.
try:
    from app.services.risk_control_service import (  # noqa: PLC0415
        check_circuit_breaker_sync as _check_cb_sync,
    )
    _LAZY_IMPORT_OK = True
except ImportError:
    _LAZY_IMPORT_OK = False
    _check_cb_sync = None  # type: ignore[assignment]

_logger = logging.getLogger(__name__)


# reviewer P2 采纳 (code HIGH + python): severity → numeric 用显式 dict mapping,
# 原公式非单调 (p0=2.0, p1=1.0, p2=3.0 recovery 反最高 = 语义错). Dict 替:
# P0=0 最严重 / P1=1 / P2=2 / INFO=3 — 监控/dashboard 下游按 ASC 排易理解.
_SEVERITY_NUMERIC: dict[Severity, float] = {
    Severity.P0: 0.0,
    Severity.P1: 1.0,
    Severity.P2: 2.0,
    Severity.INFO: 3.0,
}


class CircuitBreakerRule(RiskRule):
    """Hybrid adapter — 包 `risk_control_service.check_circuit_breaker_sync` 接入 Engine.

    调用签名 (实测 risk_control_service.py:1349):
        check_circuit_breaker_sync(conn, strategy_id, exec_date, initial_capital)
        -> {"level": 0-4, "action": str, "reason": str,
            "position_multiplier": float, "recovery_info": str}

    Evaluate 流程:
      1. 读 prev_level 从 `circuit_breaker_state` 表 (pre-snapshot)
      2. 调 sync API (触发 state 评估 + DB upsert + 可能的 async NotificationService)
      3. 读 new_level = result["level"] (post-snapshot, sync API 返)
      4. 若 prev == new: return [] (no event, 铁律 33 只真事件入 log)
      5. 若 new > prev: rule_id=f"cb_escalate_l{new}" severity=P0 (L≥3) 否则 P1
      6. 若 new < prev: rule_id=f"cb_recover_l{new}" severity=P2

    Invariants:
      - rule_id = "circuit_breaker" (RuleResult.rule_id 动态按 transition)
      - severity = Severity.P1 (class 默认, RuleResult 按 level 动态调整未来版本)
      - action = "alert_only" (Engine 不调 broker, CB 通过 signal_engine 下游影响)

    关联铁律: 31 例外 / 33 fail-loud 只真事件入 log / 41 tz-aware via datetime
    """

    rule_id: str = "circuit_breaker"
    severity: Severity = Severity.P1
    action: Literal["sell", "alert_only", "bypass"] = "alert_only"

    def __init__(
        self, conn_factory: Callable[[], Any], initial_capital: float
    ) -> None:
        """注入 conn_factory + 初始资金 (DI).

        reviewer P2-1 采纳 (python): `Callable[[], Any]` 精确 conn_factory 签名
        (替 bare Any 避免 DI 边界类型擦除). Any 内层因 psycopg2 stubs 未安装保留.

        Args:
            conn_factory: callable () → psycopg2 conn (调用方管理 close()).
            initial_capital: PAPER_INITIAL_CAPITAL (settings, 铁律 34 SSOT).
        """
        self._conn_factory = conn_factory
        self._initial_capital = initial_capital

    def root_rule_id_for(self, triggered_rule_id: str) -> str:
        """CB transition rule_id 反查 root `"circuit_breaker"`.

        Semantic (v2 passthrough 模式, 对齐 batch 1 PMSRule):
          - `cb_escalate_l{N}` / `cb_recover_l{N}` pattern → 返 self.rule_id
          - 其他 triggered_id → passthrough (不声明所有权)
        """
        if triggered_rule_id.startswith(("cb_escalate_l", "cb_recover_l")):
            suffix = triggered_rule_id.rsplit("_l", 1)[-1]
            if suffix.isdigit():
                return self.rule_id
        return triggered_rule_id

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        """调 sync API 并 diff pre/post snapshot, 仅 level 变化时返 RuleResult.

        reviewer P1 HIGH 采纳 (code): 原 `with self._conn_factory() as conn:`
        走 psycopg2 __exit__ 只 commit/rollback 不 close() → _TrackedConnection 泄漏.
        改显式 conn = factory(); try/finally conn.close() 对齐 app/api/pms.py:23
        全项目 pattern, 防每 14:30 daily 累积到 _MAX_CONNECTIONS 耗尽.

        TODO(batch-3b): `check_circuit_breaker_sync` 内部 L1597 也调 send_alert,
        本 adapter 返 RuleResult 后 Engine.execute 再调 _notify → 双钉钉告警.
        Sunset gate 条件 A+B+C 满足后 inline 重构时去重 (Redis dedup 或 adapter
        层 skip notify). 当前接受此小重复 (实战观察).
        """
        if not _LAZY_IMPORT_OK or _check_cb_sync is None:
            raise ImportError(
                "CircuitBreakerRule requires app.services.risk_control_service — "
                "module import failed (生产 import path 断)"
            )

        # reviewer P1 HIGH 采纳: 显式 try/finally close, 不用 with 防 _TrackedConnection 泄漏
        conn = self._conn_factory()
        try:
            prev_level = self._read_current_level(
                conn, context.strategy_id, context.execution_mode
            )
            cb_result = _check_cb_sync(
                conn,
                context.strategy_id,
                context.timestamp.date(),
                self._initial_capital,
            )
        finally:
            conn.close()

        new_level = int(cb_result["level"])
        if new_level == prev_level:
            return []

        if new_level > prev_level:
            transition = "escalate"
            # L3/L4 = P0 (降仓/停交易, 影响真金), L1/L2 = P1 (暂停1日)
            triggered_severity = Severity.P0 if new_level >= 3 else Severity.P1
        else:
            transition = "recover"
            # Recovery 是好消息, P2 info-level
            triggered_severity = Severity.P2

        return [
            RuleResult(
                rule_id=f"cb_{transition}_l{new_level}",
                code="",  # 组合级 CB, 非单股
                shares=0,  # alert_only 不下单
                reason=(
                    f"CircuitBreaker {transition} L{prev_level}→L{new_level}: "
                    f"{cb_result.get('reason', 'no reason provided')} "
                    f"(action={cb_result.get('action')}, "
                    f"position_multiplier={cb_result.get('position_multiplier')})"
                ),
                metrics={
                    # reviewer P2 采纳 (python P2-2 + code MEDIUM): int 保存 level/severity
                    # 不 cast float — metrics dict 允许混类型 (JSON 序列化层处理).
                    "prev_level": prev_level,
                    "new_level": new_level,
                    # reviewer P2 采纳 (python P2-3 + code MEDIUM): transition_type 用 string
                    # 替 magic float 1.0/-1.0, 可读且扩展新 transition 时不 break downstream
                    # if-else (e.g. 若未来加 "lateral").
                    "transition_type": transition,  # "escalate" | "recover"
                    "position_multiplier": float(
                        cb_result.get("position_multiplier", 1.0)
                    ),
                    # reviewer P2 采纳 (python P2-2 + code MEDIUM): severity_numeric dict
                    # mapping 替原公式 (非单调 p0=2 p1=1 p2=3, recovery 反最高 = 语义错).
                    "severity_numeric": _SEVERITY_NUMERIC[triggered_severity],
                },
            )
        ]

    @staticmethod
    def _read_current_level(
        conn: Any,  # psycopg2.extensions.connection (Any 避免 stubs 硬依赖)
        strategy_id: str,
        execution_mode: str,
    ) -> int:
        """读 circuit_breaker_state 当前 level (pre-snapshot). 首次运行 / 无行返 0.

        ⚠️ **Session 31 fix** (dry-run 发现): 原查询 `SELECT level` 拼错, 实际 column
        名 `current_level` (DDL `docs/QUANTMIND_V2_DDL_FINAL.sql` + 实测 cb_state
        schema). 配合老 `except Exception: return 0` 吞所有异常, **prev_level 永远
        silent 返 0** — escalate 路径重复 emit / recover 路径永 missed event. 2 opus
        reviewer 漏 (PR #61), 因单测 mock cursor 无法捕 column name drift.

        铁律 33 fail-loud 合规窄化 except:
          - `UndefinedTable` (首次运行表未建) → silent_ok 返 0 (CB 语义 "首次 = 未熔断")
          - 其他异常 (UndefinedColumn / connection error / ...) → log.error + re-raise
            (绝不 silent 吞, 防本 bug 再隐匿)

        Note: check_circuit_breaker_sync 内部 `_ensure_cb_tables_sync` 会建表, 但本
        pre-snapshot 发生在 sync API 之前, 首次 adapter 运行时表可能不存在.

        **P2 reviewer 采纳** (database, Session 31 PR #63): 查询省 ORDER BY/LIMIT —
        `circuit_breaker_state` schema UNIQUE 约束 `(strategy_id, execution_mode)`
        保证每 key 最多 1 row (sync API L1267 UPSERT 单行语义). 对齐 risk_control_
        service.py:1218 老 sync API 纯 WHERE 风格, 避免读者误认为 append-only log.
        """
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT current_level FROM circuit_breaker_state
                    WHERE strategy_id = %s AND execution_mode = %s""",
                    (strategy_id, execution_mode),
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0
        except psycopg2.errors.UndefinedTable:
            # silent_ok: 首次运行 cb_state 表未建 (check_circuit_breaker_sync 会建),
            # 符合 CB 状态机 "首次 = L0 未熔断" 语义. 铁律 33 (d) silent_ok 具体原因.
            with contextlib.suppress(Exception):
                conn.rollback()  # silent_ok: rollback 失败 conn 已坏
            return 0
        except Exception:
            # fail-loud: column drift / connection error / 其他 SQL 错 — 绝不吞,
            # 铁律 33 (b) 生产链路 fail-loud. 本 bug (PR #61 → Session 31 dry-run
            # 发现) 就是老版本 silent Exception 吞 UndefinedColumn 导致.
            with contextlib.suppress(Exception):
                conn.rollback()
            _logger.exception(
                "CircuitBreakerRule._read_current_level 读 cb_state 失败 "
                "(strategy_id=%s, execution_mode=%s) — 铁律 33 fail-loud, "
                "非 UndefinedTable 异常不 silent 返 0",
                strategy_id, execution_mode,
            )
            raise
