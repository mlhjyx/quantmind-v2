"""Framework #5 Backtest — 同一套 SignalPipeline 跑研究和生产 (U1 Parity).

目标: quick/full/batch/WF 四种模式统一入口, 替代现有散落 runner.

关联铁律:
  - 14: 回测引擎不做数据清洗 (DataFeed 提供什么就用什么)
  - 15: 回测可复现 (config_yaml_hash + git_commit 记录, regression max_diff=0)
  - 16: 信号路径唯一 (走同一 SignalPipeline)
  - 18: 回测成本与实盘对齐 (H0 验证 + 季度复核)

实施时机:
  - MVP 2.3 Backtest Framework + U1 Parity: BacktestRunner + BacktestRegistry
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from .._types import BacktestMode


@dataclass(frozen=True)
class BacktestConfig:
    """回测配置 — 可序列化, hash 稳定 (用于 regression_test 锚点).

    Args:
      start: 回测起始日
      end: 终止日
      universe: "csi300" / "csi500" / "all_a"
      factor_pool: 因子名列表
      rebalance_freq: "daily" / "weekly" / "monthly"
      top_n: Top-N 选股 (e.g. 20)
      industry_cap: 行业权重上限 (1.0 = 无限制)
      size_neutral_beta: SN modifier 系数 (0.50 = partial SN)
      cost_model: "simplified" / "full" (full 含印花税历史 + 三因素滑点)
      capital: 初始资本 (Decimal, 序列化为字符串)
      benchmark: 基准 ("csi300" / "none")
      extra: 扩展参数 (FUTURE-PROOF)
    """

    start: date
    end: date
    universe: str
    factor_pool: tuple[str, ...]
    rebalance_freq: str
    top_n: int
    industry_cap: float
    size_neutral_beta: float
    cost_model: str
    capital: str
    benchmark: str
    extra: dict[str, Any]


@dataclass(frozen=True)
class BacktestResult:
    """回测结果 — 不含大 artifact, 仅指标; artifacts 通过 BacktestRegistry 查找.

    Args:
      run_id: 唯一运行 ID (UUID)
      config_hash: BacktestConfig 的 sha256 (铁律 15 复现锚)
      git_commit: 回测时的 git HEAD commit
      sharpe: 年化 Sharpe
      annual_return: 年化收益率 (decimal, e.g. 0.22 = 22%)
      max_drawdown: 最大回撤 (negative, e.g. -0.15)
      total_return: 总收益
      trades_count: 成交笔数
      metrics: 扩展指标 (Sortino / Calmar / IR / WF stats)
    """

    run_id: UUID
    config_hash: str
    git_commit: str
    sharpe: float
    annual_return: float
    max_drawdown: float
    total_return: float
    trades_count: int
    metrics: dict[str, Any]


class BacktestRunner(ABC):
    """回测运行器 — 4 种 mode 统一入口.

    关联铁律 15: config_hash + git_commit 每次必录入 BacktestRegistry.
    """

    @abstractmethod
    def run(self, mode: BacktestMode, config: BacktestConfig) -> BacktestResult:
        """执行一次回测.

        Args:
          mode: QUICK_1Y / FULL_5Y / FULL_12Y / WF_5FOLD
          config: 回测配置

        Returns:
          BacktestResult, 指标 + 锚点

        Raises:
          DataIntegrityError: 数据地基不满足 (universe / 前瞻)
          ConfigHashCollision: 已有相同 config_hash 的记录 (可能 reuse)
        """


class BacktestRegistry(ABC):
    """回测运行记录表 — 替代散落 JSON artifact.

    每次 BacktestRunner.run 都写一行, 含 config_hash 方便查重复.
    """

    @abstractmethod
    def log_run(
        self,
        config: BacktestConfig,
        result: BacktestResult,
        artifact_paths: dict[str, str],
    ) -> UUID:
        """记录一次运行.

        Args:
          config: 回测配置
          result: 结果指标
          artifact_paths: parquet / json 文件路径 (nav / holdings / metrics)

        Returns:
          run_id
        """

    @abstractmethod
    def get_by_hash(self, config_hash: str) -> BacktestResult | None:
        """按 config_hash 查历史运行 (用于 regression anchor)."""

    @abstractmethod
    def list_recent(self, limit: int = 20) -> list[BacktestResult]:
        """列最近 N 次运行."""


class BatchBacktestExecutor(ABC):
    """批量回测 — 串行尊重 32GB 约束 (铁律 9).

    用于 AI 闭环内循环淘汰 / 参数 sweep.
    """

    @abstractmethod
    def run_batch(
        self, configs: list[BacktestConfig], mode: BacktestMode = BacktestMode.QUICK_1Y
    ) -> list[BacktestResult]:
        """串行执行一批回测.

        铁律 9: 禁裸并发, 走 ResourceManager 仲裁 (Framework #11).

        Returns:
          结果列表, 顺序对齐 configs
        """
