"""MVP 3.2 批 4 — Strategy Registry Bootstrap + 多策略查询 helper.

批 4 scope:
  - 为 daily_pipeline.risk_daily_check / intraday_risk_check 提供多策略迭代入口
  - 幂等 bootstrap: 每次 task 调用 register S1 (DBStrategyRegistry 幂等 upsert)
  - **Fail-safe fallback**: DB 挂 / registry 异常 / get_live() empty → `[S1MonthlyRanking()]`
    (legacy 单策略路径, Monday 4-27 首次真生产触发 zero 干扰)

## 关键设计决策 (铁律 39 显式)

- **Bootstrap 层管理 conn + commit (铁律 32)**: DBStrategyRegistry 内部 `with
  conn.cursor()` 不 commit (Service 层职责分工). 本 wiring 层 (app/services/
  strategy_bootstrap.py, 铁律 31 允许 IO) 开 conn → 传 `conn_factory=lambda: conn`
  → 调用 register → `conn.commit()` 持久化. 异常 rollback + fallback.

- **per-task 重建 registry**: instance 持 in-memory cache, 多 task 共享 cache 能省
  register 开销. MVP 3.2 批 4 simple-first: 每 task 重建 (ms 级开销) 换 state-less 简洁.
  Wave 4+ observability 再评估 worker-level cache.

- **S1 class attr status=LIVE → DB 首次 INSERT status='live'**: 符合当前 PT 真生产.
  首 task 跑 register() 自动 INSERT status='live' + strategy_status_log 审计行.

- **S2 NOT registered here**: S2.status=DRY_RUN, 即便 register get_live() 也会 filter.
  **Monday 4-27 后** (Tuesday+) 手工 register S2 or 独立 ops script. 本 bootstrap
  故意不 register S2, 让 Monday 观察 S1-only 基线.

- **Fail-safe**: 任何 Exception → `[S1MonthlyRanking()]` + logger.error. S1 UUID 与
  当前 PT `settings.PAPER_STRATEGY_ID` 一致, fallback 语义 = 老单策略路径.

关联铁律: 23 (独立可执行) / 31 (app 层允许 IO) / 32 (wiring 层管事务) /
          33 (fail-loud log, 不 silent) / 34 (Config SSOT)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.db import get_sync_conn

# P3-B python-reviewer (PR #72) 采纳: S1MonthlyRanking module-top import 保 fail-safe
# 契约 (原 lazy import inside try 若未执行到 except 会 NameError 破 fallback).
# s1_monthly_ranking → signal_engine → app.config chain 实测无循环 (smoke test 已验).
from backend.engines.strategies.s1_monthly_ranking import S1MonthlyRanking

if TYPE_CHECKING:
    from backend.qm_platform.strategy.interface import Strategy

logger = logging.getLogger(__name__)


def get_live_strategies_for_risk_check() -> list[Strategy]:
    """返回当前 LIVE 策略列表 (daily_pipeline.risk_daily_check / intraday_risk_check 消费).

    流程:
      1. 开 conn (wiring 层管事务, 铁律 32)
      2. 构 DBStrategyRegistry with conn_factory=lambda: conn (共享 conn)
      3. 幂等 register S1MonthlyRanking (填 in-memory cache + upsert DB metadata)
      4. conn.commit() 持久化
      5. 调 registry.get_live() 返 Strategy instances (status='live' filter 过)
      6. Fail-safe: empty list / 任何 Exception → `[S1MonthlyRanking()]` (legacy)

    Returns:
        非空 list of Strategy. 至少 1 个 (fallback 保底 S1MonthlyRanking). 保证下游
        `for strategy in strategies:` loop 总有迭代项, Monday 4-27 生产链不挂.

    Raises:
        None (fail-safe by design). 异常捕获 + logger.error + fallback.

    铁律 33 说明:
      - 返 fallback 非 silent fail: logger.error 显式记录原因 + fallback 语义
      - 生产链路决策: fail-safe 优先 fail-loud (Monday 真金不能因 registry 异常挂)
      - 异常 root cause logger.error 捕获, Flower / logs 可观测
    """
    # S1MonthlyRanking 已在 module-top import (P3-B 采纳, 保 fail-safe 契约).
    conn = None
    try:
        from backend.qm_platform.strategy.registry import DBStrategyRegistry

        conn = get_sync_conn()
        # conn_factory 返 captured conn, 保证 register() 所有 cursor 操作共享同一事务
        registry = DBStrategyRegistry(conn_factory=lambda: conn)

        # 幂等: DB 已有 S1 row → ON CONFLICT DO UPDATE 只更 metadata (name/freq/
        # factor_pool/config/description), status 保留由 update_status 管.
        # 首次 register (DB 空): INSERT status='live' (S1.status ClassVar) + status_log.
        registry.register(S1MonthlyRanking())

        # TODO (Tuesday 4-28+ post-Monday observation): register S2PEADEvent() 激活
        # dual-running. S2.status=DRY_RUN, get_live() filter 自动排除. 代码无改动仅
        # uncomment 下 2 行 + 明日 Monday 观察干净后执行:
        # from backend.engines.strategies.s2_pead_event import S2PEADEvent
        # registry.register(S2PEADEvent())

        # 铁律 32: wiring 层 commit 关闭事务 (Service register 内部不 commit)
        conn.commit()

        live = registry.get_live()
        if live:
            logger.info(
                "[strategy-bootstrap] %d live strategies: %s",
                len(live),
                [s.strategy_id for s in live],
            )
            return live

        # Empty: S1 status != 'live' (可能被 update_status retired/paused) → fallback
        logger.warning(
            "[strategy-bootstrap] registry.get_live() empty after register(S1), "
            "fallback to [S1MonthlyRanking()] (legacy path). "
            "可能 S1 DB status != 'live' (被手工 retired/paused).",
        )
        return [S1MonthlyRanking()]

    except Exception as e:  # noqa: BLE001 — fail-safe 所有异常回退
        # 铁律 32: 异常 rollback (若 conn 已开启事务)
        if conn is not None:
            try:
                conn.rollback()
            except Exception as rb_e:  # noqa: BLE001
                logger.error(
                    "[strategy-bootstrap] rollback failed after exception: %s: %s",
                    type(rb_e).__name__,
                    rb_e,
                )
        logger.error(
            "[strategy-bootstrap] get_live_strategies FALLBACK to [S1] — %s: %s",
            type(e).__name__,
            e,
            exc_info=True,
        )
        return [S1MonthlyRanking()]

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception as close_e:  # noqa: BLE001
                logger.warning(
                    "[strategy-bootstrap] conn.close() failed: %s: %s",
                    type(close_e).__name__,
                    close_e,
                )
