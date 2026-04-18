"""MVP 2.3 Sub1 PR B · SerialBacktestExecutor concrete — 串行批量执行.

设计 (铁律 24 不预优化):
  - MVP 3.0 Resource Orchestration 前串行即可, 配合 32GB RAM + 数据密集任务限制 (铁律 9).
  - Wave 3 MVP 3.0 后升级为 `ResourceAwareExecutor` (走 ResourceManager 仲裁, U6 升维).

关联铁律: 9 (资源密集串行) / 23 (独立可执行) / 24 (过早优化 YAGNI).
"""

from __future__ import annotations

from backend.platform._types import BacktestMode

from .interface import BacktestConfig, BacktestResult, BacktestRunner, BatchBacktestExecutor


class SerialBacktestExecutor(BatchBacktestExecutor):
    """串行执行一批 BacktestConfig (MVP 2.3 PR B).

    Args:
      runner: BacktestRunner 实例 (PlatformBacktestRunner 或 mock).
    """

    def __init__(self, runner: BacktestRunner) -> None:
        self._runner = runner

    def run_batch(
        self,
        configs: list[BacktestConfig],
        mode: BacktestMode = BacktestMode.QUICK_1Y,
    ) -> list[BacktestResult]:
        """串行跑 configs, 返回结果列表 (顺序对齐 configs).

        失败策略: 任一 config fail (raise) → 直接传播, 不吞. 上层决定 partial batch 还是全 abort.
        """
        return [self._runner.run(mode, cfg) for cfg in configs]


__all__ = ["SerialBacktestExecutor"]
