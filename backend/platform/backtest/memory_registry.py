"""MVP 2.3 Sub1 PR C2 · InMemoryBacktestRegistry — ad-hoc/研究脚本不落 DB.

`DBBacktestRegistry` 是生产默认 (backtest_run 表 + U3 lineage + config_hash cache).
但 `scripts/run_backtest.py --config ...` / 研究快速迭代 / 单测场景既不想污染
backtest_run 7 行历史 + 无法 rollback, 又想每次真跑不被 cache 挡住 (ad-hoc 验证刚改的
引擎逻辑必须真跑, cache 反而是噪声).

本 Registry 实现三点语义:
  1. `log_run` no-op (记到内存 list 供测试断言, 不写 DB, 不触 lineage).
  2. `get_by_hash` 恒返 None (强制 cache miss, 每次真跑).
  3. `list_recent` 返内存 list 最后 N 条 (测试/调试用).

调用方 (e.g. run_backtest.py) 用本 Registry 配 PlatformBacktestRunner 后,
每次 `runner.run(mode, config)` 必走 engine + 产 `engine_artifacts`, 消费者可从
`result.engine_artifacts["engine_result"]` 取 daily_nav 走 `generate_report`.

关联铁律: 17 (DataPipeline 入库 — 本 Registry 显式选择不入库, 注释标明) / 34 (配置
  single source of truth — InMem 不是默认, 调用方显式选择) / 40 (测试债务 — 测试场景
  用 InMem 避免 DB 依赖 + 事务污染).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .interface import BacktestConfig, BacktestRegistry, BacktestResult

if TYPE_CHECKING:
    from datetime import date

    from backend.platform._types import BacktestMode


class InMemoryBacktestRegistry(BacktestRegistry):
    """BacktestRegistry concrete 走内存 list, 不触 DB (MVP 2.3 PR C2).

    线程安全: **不保证** — 设计意图是单进程 ad-hoc 脚本/单测. 多线程场景走
    DBBacktestRegistry + PG 事务.

    Args:
      max_history: 内存保留条数上限 (LRU trim, 默认 100 防 long-lived 进程 OOM).
                   调用方可传 None 关闭上限 (测试场景).
    """

    def __init__(self, max_history: int | None = 100) -> None:
        self._results: list[BacktestResult] = []
        self._max_history = max_history

    def log_run(  # type: ignore[override]
        self,
        config: BacktestConfig,
        result: BacktestResult,
        artifact_paths: dict[str, str],
        *,
        mode: BacktestMode | None = None,
        elapsed_sec: int | None = None,
        lineage: Any | None = None,
        perf: Any | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> None:
        """记 result 到内存, 不写 DB, 不触 lineage. 恒返 None (abstract 允许 None).

        扩展签名匹配 DBBacktestRegistry.log_run (PR B concrete 扩, 调用方 Runner 按扩名调),
        kwargs 全 unused — InMem 不持久化 mode/elapsed/lineage/perf/dates.
        """
        del config, artifact_paths, mode, elapsed_sec, lineage, perf, start_date, end_date
        self._results.append(result)
        if self._max_history is not None and len(self._results) > self._max_history:
            # trim 最旧 (保最近 max_history 条)
            self._results = self._results[-self._max_history :]
        return None

    def get_by_hash(self, config_hash: str) -> BacktestResult | None:
        """恒返 None — 强制 PlatformBacktestRunner cache miss + 每次真跑.

        **设计决策**: ad-hoc 场景 cache 反而有害 (引擎改后 cache 会返旧结果).
        生产 cache 走 DBBacktestRegistry, 本 Registry 不做.
        """
        del config_hash
        return None

    def list_recent(self, limit: int = 20) -> list[BacktestResult]:
        """返内存 list 最后 N 条 (最新在尾). 测试/调试用."""
        if limit <= 0:
            return []
        return list(self._results[-limit:])

    # ─── 测试辅助 (非 abstract, 调用方可选用) ─────────────────

    def clear(self) -> None:
        """清空内存 list (测试 teardown / 长跑进程 cleanup)."""
        self._results.clear()

    def __len__(self) -> int:
        """单测方便断言 `len(registry) == N`."""
        return len(self._results)


__all__ = ["InMemoryBacktestRegistry"]
