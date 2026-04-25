"""MVP 2.3 Sub1 PR C2 · InMemoryBacktestRegistry — ad-hoc/研究脚本不落 DB.

`DBBacktestRegistry` 是生产默认 (backtest_run 表 + U3 lineage + config_hash cache).
但 `scripts/run_backtest.py --config ...` / 研究快速迭代 / 单测场景既不想污染
backtest_run 7 行历史 + 无法 rollback, 又想每次真跑不被 cache 挡住 (ad-hoc 验证刚改的
引擎逻辑必须真跑, cache 反而是噪声).

本 Registry 实现三点语义:
  1. `log_run` no-op (记到内存 list 供测试断言, 不写 DB, 不触 lineage).
     **不存 config / artifact_paths / 扩签名 kwargs** — 消费者若需上下文, 自行持久化
     `BacktestConfig` (单进程 ad-hoc 场景足够).
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

from backend.qm_platform._types import BacktestMode

from .interface import BacktestConfig, BacktestRegistry, BacktestResult

if TYPE_CHECKING:
    from datetime import date


class InMemoryBacktestRegistry(BacktestRegistry):
    """BacktestRegistry concrete 走内存 list, 不触 DB (MVP 2.3 PR C2).

    线程安全: **不保证** — 设计意图是单进程 ad-hoc 脚本/单测. 多线程场景走
    DBBacktestRegistry + PG 事务.

    Args:
      max_history: 内存保留条数上限 (LRU trim, 默认 100 防 long-lived 进程 OOM).
                   传 None 关闭上限 (测试场景). **必须 >0 或 None** —
                   传 0 会 raise ValueError (原 ``list[-0:]`` 等同 ``list[0:]``
                   返全量是 Python 坑, PR C2 review P1 fix 显式拒绝).
    """

    def __init__(self, max_history: int | None = 100) -> None:
        if max_history is not None and max_history <= 0:
            raise ValueError(
                f"max_history must be positive or None, got {max_history}. "
                f"(list[-0:] == list[0:] 返全量是 Python 坑, 禁止传 0/负数)"
            )
        self._results: list[BacktestResult] = []
        self._max_history = max_history

    def log_run(
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
        """记 result 到内存, 不写 DB, 不触 lineage. 返 None (abstract 允许).

        config / artifact_paths / mode / elapsed_sec / lineage / perf / start_date /
        end_date 均不存 — 消费者若需上下文, 自行保留 BacktestConfig.
        PR C2 review P1 fix: abstract 扩签名后无需 ``# type: ignore[override]``.
        """
        self._results.append(result)
        if self._max_history is not None and len(self._results) > self._max_history:
            self._results = self._results[-self._max_history :]

    def get_by_hash(self, config_hash: str) -> BacktestResult | None:
        """恒返 None — 强制 PlatformBacktestRunner cache miss + 每次真跑.

        **设计决策**: ad-hoc 场景 cache 反而有害 (引擎改后 cache 会返旧结果).
        生产 cache 走 DBBacktestRegistry, 本 Registry 不做.
        """
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
        """单测方便断言 `len(registry) == N`.

        BacktestRegistry 抽象不继承 Sized, 此方法只对持 concrete 引用的调用方可见
        (抽象侧用 list_recent() 替代).
        """
        return len(self._results)


__all__ = ["InMemoryBacktestRegistry"]
