"""MVP 3.2 Strategy Framework — DBStrategyRegistry concrete.

**批 1 (Session 33 Part 1, 2026-04-24)**: 提供 Strategy 注册表的 DB-backed 实现.
与 `strategy_registry` + `strategy_status_log` 2 DB 表配对 (backend/migrations/strategy_registry.sql).

**MVP 3.5.1 (Session 43 跨 PR follow-up, 2026-04-28)**: 加 `record_evaluation()` +
`update_status(LIVE)` 守门. 防止策略未经 PlatformStrategyEvaluator 评估直接升 LIVE.
配套表 `strategy_evaluations` (backend/migrations/strategy_evaluations.sql).

## 架构决策

- **In-memory instance cache + DB metadata**: `_instances: dict[UUID, Strategy]` 启动时注入,
  DB 只存 metadata (name / status / factor_pool / config). `get_live()` 返 DB live UUIDs ∩
  cache 的 instances. 若 DB 有 UUID 但 cache 未 register → fail-loud StrategyNotFound
  (铁律 33 silent fail 禁).

- **铁律 32 事务边界**: 本类所有 DB 方法**不 commit**, 调用方 (daily_pipeline / FastAPI) 管事务.
  上层 Exception 必须 rollback.

- **铁律 39 显式声明**: DBStrategyRegistry 走 sync psycopg2 (对齐 DBFactorRegistry +
  DBFeatureFlag + DBExperimentRegistry 等既有 Platform concrete 模式).

- **MVP 3.5.1 LIVE 守门**: update_status(strategy_id, LIVE, ...) 必先 record_evaluation(verdict)
  把 PlatformStrategyEvaluator 输出落 strategy_evaluations 表. 守门读最新行 +
  freshness check (默认 30 天). 防止跳过评估直接升 LIVE 真金事故.
  调用顺序: evaluator.evaluate_strategy(sid) → registry.record_evaluation(verdict) →
  registry.update_status(sid, LIVE, reason).
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from .._types import Verdict
from .interface import RebalanceFreq, Strategy, StrategyRegistry, StrategyStatus

if TYPE_CHECKING:
    import psycopg2.extensions

_logger = logging.getLogger(__name__)

# MVP 3.5.1 default freshness window for "latest evaluation must be within N days
# before promoting to LIVE". Configurable via DBStrategyRegistry constructor arg.
DEFAULT_LIVE_EVAL_FRESHNESS_DAYS = 30


class StrategyNotFound(KeyError):  # noqa: N818 — 语义优先 (对齐 FactorNotFound)
    """策略 ID 在 DB 或 in-memory cache 中找不到."""


class StrategyRegistryIntegrityError(RuntimeError):
    """DB 与 in-memory cache 不一致 (e.g. DB live 但 cache 未 register)."""


class EvaluationRequired(RuntimeError):  # noqa: N818 — 语义优先 (对齐 StrategyNotFound)
    """update_status(LIVE) 触发但最近评估缺失/未通过/已过期 (MVP 3.5.1 守门).

    触发条件 (任一):
      - strategy_evaluations 表无该 strategy_id 记录
      - 最新行 passed=False (有 blockers)
      - 最新行 evaluated_at 超出 freshness 窗口 (默认 30 天)

    修复路径:
      evaluator = PlatformStrategyEvaluator(loader)
      verdict = evaluator.evaluate_strategy(strategy_id)
      registry.record_evaluation(verdict)
      registry.update_status(strategy_id, StrategyStatus.LIVE, reason)
    """


class DBStrategyRegistry(StrategyRegistry):
    """DB-backed StrategyRegistry 实现.

    Args:
      conn_factory: 返回 psycopg2 connection 的 callable (DI, 对齐 MVP 1.3b DBFactorRegistry).

    Usage:
      >>> registry = DBStrategyRegistry(conn_factory=get_sync_conn)
      >>> registry.register(S1MonthlyRanking())  # 在 boot 时 (FastAPI lifespan) 注册
      >>> live = registry.get_live()  # daily_pipeline 16:30 signal_phase 遍历
    """

    def __init__(
        self,
        conn_factory: Callable[[], psycopg2.extensions.connection],
        *,
        live_eval_freshness_days: int = DEFAULT_LIVE_EVAL_FRESHNESS_DAYS,
    ) -> None:
        """初始化.

        Args:
          conn_factory: psycopg2 connection callable (DI, 对齐 MVP 1.3b DBFactorRegistry).
          live_eval_freshness_days: MVP 3.5.1 update_status(LIVE) freshness 阈值 (默认 30 天).
            最新评估超出此窗口视为过期, 拒绝升 LIVE. 必 > 0.
        """
        if live_eval_freshness_days <= 0:
            raise ValueError(
                f"live_eval_freshness_days 必须 > 0, 实测 {live_eval_freshness_days}"
            )
        self._conn_factory = conn_factory
        self._live_eval_freshness_days = live_eval_freshness_days
        # In-memory instance cache (boot-time populated via register())
        self._instances: dict[UUID, Strategy] = {}

    # ─── CRUD: register ───────────────────────────────────────────────

    def register(self, strategy: Strategy) -> None:
        """注册策略 — instance 入 cache + metadata upsert 到 DB.

        幂等: 同 strategy_id 重复 register 不报错, 更新 metadata (name/factor_pool/config)
        但保留 status (status 变更走 update_status() 带审计).

        Raises:
          ValueError: strategy.strategy_id 非有效 UUID, 或 factor_pool 空
          psycopg2 errors: DB 连接失败 / CHECK 约束违反 (fail-loud, 铁律 33)
        """
        sid = self._parse_uuid(strategy.strategy_id, "strategy_id")
        name = getattr(strategy, "name", None) or strategy.__class__.__name__
        factor_pool = list(strategy.factor_pool)
        # 铁律 13/14 例外 (Session 36 Sprint 5 sourced from MVP 3.2 batch 4 follow-up):
        # event-driven 策略 (rebalance_freq=EVENT) 不依赖 factor_registry 因子, 而由 event
        # source 提供 alpha (e.g. S2PEADEvent 直接消费 earnings_announcements.eps_surprise_pct).
        # 此类策略 factor_pool=[] 是有意设计, MVP_3_2_strategy_framework.md §批 3 明确:
        # "不依赖 DEPRECATED `pead_q1` ... 直接消费 earnings_announcements 原始数据".
        # 仅 ranking/timing 类策略 (MONTHLY/WEEKLY/DAILY/QUARTERLY) 强制 factor_pool 非空.
        # 注意 (PR #87 LOW reviewer): 仅 EVENT 例外, 不可扩至 MONTHLY/WEEKLY/DAILY/QUARTERLY,
        # 防止 ranking 策略 typo 漏检 factor_pool 配置. 未来若新增 freq 值需重审本条款.
        if not factor_pool and strategy.rebalance_freq != RebalanceFreq.EVENT:
            raise ValueError(
                f"Strategy {name} factor_pool is empty — "
                "铁律 13/14 要求 ranking/timing 策略必依赖显式因子清单. "
                "仅 rebalance_freq=EVENT 且通过非 factor_registry 数据源提供 alpha 的策略可空."
            )

        # 序列化 Enum -> text
        rebalance_freq = strategy.rebalance_freq.value
        status = getattr(strategy, "status", StrategyStatus.DRAFT)
        status_text = status.value if isinstance(status, StrategyStatus) else str(status)
        config = getattr(strategy, "config", {})
        description = getattr(strategy, "description", "")

        conn = self._conn_factory()
        # reviewer P1 (code+db, 2026-04-24 PR #69): `with conn.cursor() as cur` 防泄漏
        with conn.cursor() as cur:
            # 查是否首次 register (决定 strategy_status_log 是否写首行)
            cur.execute(
                "SELECT status FROM strategy_registry WHERE strategy_id = %s",
                (str(sid),),
            )
            existing_row = cur.fetchone()
            existing_status = existing_row[0] if existing_row else None

            # Upsert (幂等, 保 status 不动, 交给 update_status 管状态迁移)
            cur.execute(
                """
                INSERT INTO strategy_registry
                    (strategy_id, name, rebalance_freq, status, factor_pool, config, description)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                ON CONFLICT (strategy_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    rebalance_freq = EXCLUDED.rebalance_freq,
                    factor_pool = EXCLUDED.factor_pool,
                    config = EXCLUDED.config,
                    description = EXCLUDED.description
                """,
                (
                    str(sid),
                    name,
                    rebalance_freq,
                    status_text,
                    json.dumps(factor_pool),
                    json.dumps(config),
                    description,
                ),
            )

            # 审计日志: 首次 register 插 log (old_status=NULL)
            if existing_status is None:
                cur.execute(
                    """
                    INSERT INTO strategy_status_log
                        (strategy_id, old_status, new_status, reason)
                    VALUES (%s, NULL, %s, %s)
                    """,
                    (str(sid), status_text, f"initial register via {self.__class__.__name__}"),
                )

        # In-memory cache (无论首次 or 重注)
        self._instances[sid] = strategy

        _logger.info(
            "strategy registered: id=%s name=%s status=%s rebalance=%s factors=%d",
            sid,
            name,
            status_text,
            rebalance_freq,
            len(factor_pool),
        )

    # ─── Query: get_live / get_by_id ──────────────────────────────────

    def get_live(self) -> list[Strategy]:
        """返回所有 DB status=LIVE 的策略 instance.

        Raises:
          StrategyRegistryIntegrityError: DB live UUID 但 in-memory cache 未 register
            (fail-loud 防 production 静默跳过策略, 铁律 33)
        """
        conn = self._conn_factory()
        # reviewer P1 cursor context manager
        with conn.cursor() as cur:
            cur.execute(
                "SELECT strategy_id, name FROM strategy_registry WHERE status = 'live' ORDER BY name"
            )
            rows = cur.fetchall()

        instances: list[Strategy] = []
        for sid_str, name in rows:
            sid = UUID(sid_str) if isinstance(sid_str, str) else sid_str
            instance = self._instances.get(sid)
            if instance is None:
                raise StrategyRegistryIntegrityError(
                    f"DB 有 live strategy {name} (id={sid}) 但 in-memory cache 未 register. "
                    "可能原因: (1) boot 时未调 register() (2) 进程重启后 instance 未重新注入. "
                    "铁律 33 fail-loud: production 跳过 live 策略是安全事故."
                )
            instances.append(instance)
        return instances

    def get_by_id(self, strategy_id: str) -> Strategy:
        """按 ID 取策略 instance. 若 DB 无或 cache 未 register 则 raise."""
        sid = self._parse_uuid(strategy_id, "strategy_id")
        conn = self._conn_factory()
        # reviewer P1 cursor context manager
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM strategy_registry WHERE strategy_id = %s", (str(sid),)
            )
            row = cur.fetchone()
        if row is None:
            raise StrategyNotFound(f"strategy_id {sid} 不在 strategy_registry DB 表中")
        instance = self._instances.get(sid)
        if instance is None:
            raise StrategyNotFound(
                f"strategy_id {sid} in DB 但 in-memory cache 未 register (需 boot 时调 register())"
            )
        return instance

    # ─── Mutate: update_status ────────────────────────────────────────

    def update_status(
        self,
        strategy_id: str,
        new_status: StrategyStatus,
        reason: str,
    ) -> None:
        """变更策略状态 + 写 strategy_status_log 审计行.

        **MVP 3.5.1 守门 (2026-04-28)**: 当 new_status == LIVE 且 old_status != LIVE 时,
        必须 strategy_evaluations 表已有最新 passed=True 行且 evaluated_at 在
        freshness 窗口内 (默认 30 天). 否则 raise EvaluationRequired (fail-loud).

        Raises:
          StrategyNotFound: strategy_id 不在 DB
          ValueError: reason 空 (审计必附原因)
          EvaluationRequired: 升 LIVE 但缺最新有效评估 (MVP 3.5.1)
        """
        if not reason or not reason.strip():
            raise ValueError("update_status 必须附 reason (审计要求)")
        sid = self._parse_uuid(strategy_id, "strategy_id")
        new_status_text = (
            new_status.value
            if isinstance(new_status, StrategyStatus)
            else str(new_status)
        )

        conn = self._conn_factory()
        # reviewer P1 cursor context manager
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM strategy_registry WHERE strategy_id = %s",
                (str(sid),),
            )
            row = cur.fetchone()
            if row is None:
                raise StrategyNotFound(
                    f"update_status 失败: strategy_id {sid} 不在 DB. 先调 register()."
                )
            old_status_text = row[0]
            if old_status_text == new_status_text:
                _logger.info(
                    "update_status no-op: id=%s already at status=%s",
                    sid,
                    new_status_text,
                )
                return

            # MVP 3.5.1 LIVE 守门: 升 LIVE 必 latest evaluation passed + fresh.
            # 仅检查 transitions INTO LIVE (old != LIVE), LIVE→其他 status (PAUSE/RETIRE)
            # 不需要重评估 (反而是降级路径, 评估守门只防止"未评估升 LIVE").
            if (
                new_status_text == StrategyStatus.LIVE.value
                and old_status_text != StrategyStatus.LIVE.value
            ):
                # Same cursor + same transaction (调用方 commit 时整体原子)
                self._assert_eval_passed_for_live(sid, cur)

            cur.execute(
                "UPDATE strategy_registry SET status = %s WHERE strategy_id = %s",
                (new_status_text, str(sid)),
            )
            cur.execute(
                """
                INSERT INTO strategy_status_log
                    (strategy_id, old_status, new_status, reason)
                VALUES (%s, %s, %s, %s)
                """,
                (str(sid), old_status_text, new_status_text, reason.strip()),
            )
        _logger.info(
            "strategy status changed: id=%s %s → %s reason=%r",
            sid,
            old_status_text,
            new_status_text,
            reason,
        )

    # ─── MVP 3.5.1: record_evaluation + LIVE 守门 ──────────────────────

    def record_evaluation(
        self,
        verdict: Verdict,
        *,
        evaluator_class: str = "PlatformStrategyEvaluator",
    ) -> None:
        """记录 Strategy 评估结果到 strategy_evaluations 表 (append-only history).

        调用顺序 (MVP 3.5.1 LIVE 守门约定):
          verdict = evaluator.evaluate_strategy(strategy_id)
          registry.record_evaluation(verdict)
          registry.update_status(strategy_id, StrategyStatus.LIVE, reason)

        Args:
          verdict: PlatformStrategyEvaluator 输出. verdict.subject 必 = strategy_id (UUID str).
          evaluator_class: 评估器 class name (审计 + 多评估器并存预留).

        Raises:
          ValueError: verdict.subject 非 UUID, 或 evaluator_class 空.
          psycopg2.errors.ForeignKeyViolation: strategy_id 不在 strategy_registry
            (调用方需先 register()).
        """
        if not evaluator_class or not evaluator_class.strip():
            raise ValueError("evaluator_class 不可为空 (审计要求)")
        sid = self._parse_uuid(verdict.subject, "verdict.subject")
        blockers_json = json.dumps(list(verdict.blockers))
        details_json = json.dumps(dict(verdict.details))

        conn = self._conn_factory()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO strategy_evaluations
                    (strategy_id, passed, blockers, p_value, details, evaluator_class)
                VALUES (%s, %s, %s::jsonb, %s, %s::jsonb, %s)
                """,
                (
                    str(sid),
                    bool(verdict.passed),
                    blockers_json,
                    verdict.p_value,
                    details_json,
                    evaluator_class.strip(),
                ),
            )
        _logger.info(
            "strategy evaluation recorded: id=%s passed=%s blockers=%d evaluator=%s",
            sid,
            verdict.passed,
            len(verdict.blockers),
            evaluator_class,
        )

    def _assert_eval_passed_for_live(
        self,
        sid: UUID,
        cur: psycopg2.extensions.cursor,
    ) -> None:
        """MVP 3.5.1 LIVE 守门 — 检查最新 strategy_evaluations 行.

        语义:
          - 无任何评估行 → EvaluationRequired (调用方需先 record_evaluation)
          - 最新 passed=False → EvaluationRequired (修 blockers 后重评估)
          - 最新 evaluated_at 过期 (> freshness_days) → EvaluationRequired (重评估)

        Args:
          sid: strategy UUID.
          cur: 复用 update_status 的 cursor (同 tx, 调用方 commit 整体原子).

        Raises:
          EvaluationRequired: 任一守门条件失败.
        """
        cur.execute(
            """
            SELECT passed, blockers, evaluated_at
            FROM strategy_evaluations
            WHERE strategy_id = %s
            ORDER BY evaluated_at DESC, id DESC
            LIMIT 1
            """,
            (str(sid),),
        )
        row = cur.fetchone()
        if row is None:
            raise EvaluationRequired(
                f"strategy_id {sid} 无 strategy_evaluations 记录, 拒绝升 LIVE. "
                f"调用方需: evaluator.evaluate_strategy(sid) → "
                f"registry.record_evaluation(verdict) → registry.update_status(sid, LIVE, reason)."
            )
        passed, blockers, evaluated_at = row
        if not passed:
            blockers_repr = (
                json.dumps(blockers) if blockers else "[]"
            ) if isinstance(blockers, (list, dict)) else str(blockers)
            raise EvaluationRequired(
                f"strategy_id {sid} 最新评估未通过 (blockers={blockers_repr}), 拒绝升 LIVE. "
                f"修复 blockers 后重 evaluate_strategy + record_evaluation."
            )
        # Freshness check: evaluated_at 是 timestamptz, psycopg2 返 tz-aware datetime (UTC).
        # 铁律 41: 内部用 UTC compare, datetime.now(timezone.utc) 对齐.
        if not isinstance(evaluated_at, datetime):
            # Defensive: 老 driver / mock 可能返 None / str. fail-loud.
            raise EvaluationRequired(
                f"strategy_id {sid} evaluated_at 非 datetime ({type(evaluated_at).__name__}), "
                f"无法做 freshness check. DB schema / driver 异常."
            )
        if evaluated_at.tzinfo is None:
            # Defensive: 若 driver 返 naive datetime, 当 UTC 处理 (PG timestamptz 应永远 aware,
            # 这里只是防御 mock / sqlite test fixture).
            evaluated_at = evaluated_at.replace(tzinfo=UTC)
        now_utc = datetime.now(UTC)
        age = now_utc - evaluated_at
        max_age = timedelta(days=self._live_eval_freshness_days)
        if age > max_age:
            raise EvaluationRequired(
                f"strategy_id {sid} 最新评估已过期 (age={age.days} 天 > "
                f"{self._live_eval_freshness_days} 天阈值), 拒绝升 LIVE. "
                f"重 evaluate_strategy + record_evaluation 后重试."
            )

    # ─── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_uuid(val: str | UUID, field_name: str) -> UUID:
        if isinstance(val, UUID):
            return val
        try:
            return UUID(val)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"{field_name} 必须是 UUID, 实测 {type(val).__name__}: {val!r}"
            ) from e
