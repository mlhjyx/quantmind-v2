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
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from .._types import BacktestMode

# ────────────────────────────────────────────────────────────────
# MVP 2.3 Sub3 C1: 嵌套 value object (frozen=True, Platform 自含镜像)
#
# 设计决策 (Plan agent review): Platform 保持自足, 不 import engines 嵌套类型.
# - engines.slippage_model.SlippageConfig 已 frozen=True, 但仍镜像防 engines 改字段
#   破坏 Platform config_hash 稳定性 (铁律 15 锚).
# - engines.backtest.config.PMSConfig 是 `@dataclass` 非 frozen + `list[tuple]` tiers,
#   直接 import 会破 Platform frozen/hashable. 镜像用 `tuple[tuple[...]]`.
# - UniverseFilter 新独占字段 (engines 无对应, pt_live.yaml `universe` 段驱动).
#
# Runner 层 (`_build_engine_config`, C4) 负责 Platform 嵌套 → engines 嵌套转换.
# ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UniverseFilter:
    """股票池过滤规则 (Platform 独有, engines 通过 price_data 列驱动).

    Args:
      exclude_st: 排除 ST/*ST 股 (stock_status_daily.is_st=true)
      exclude_bj: 排除北交所股 (symbols.board='bse')
      exclude_suspended: 排除停牌股 (stock_status_daily.is_suspended=true)
      min_listing_days: 最小上市天数 (days_since_ipo >= min_listing_days), 60 = 新股过滤
    """

    exclude_st: bool = True
    exclude_bj: bool = True
    exclude_suspended: bool = True
    min_listing_days: int = 60


@dataclass(frozen=True)
class SlippageConfig:
    """三因素滑点配置 (镜像 `engines.slippage_model.SlippageConfig`, frozen + hashable).

    字段默认值严格对齐 engines 侧 (R4 研究结论). C4 Runner fallback 负责 Platform
    SlippageConfig → engines SlippageConfig 字段对字段转换.

    Args:
      Y_large / Y_mid / Y_small: 市值分档冲击乘数 (Bouchaud 2018)
      sell_penalty: 卖出方向冲击惩罚倍数
      base_bps: 旧版固定基础滑点 (bps), tiered 模式下被覆盖
      base_bps_large / base_bps_mid / base_bps_small: 市值分档 bid-ask spread (bps)
      gap_penalty_factor: 隔夜跳空惩罚系数 (0-1, 默认 0.5 只承受一半跳空)
    """

    Y_large: float = 0.8
    Y_mid: float = 1.0
    Y_small: float = 1.5
    sell_penalty: float = 1.2
    base_bps: float = 5.0
    base_bps_large: float = 3.0
    base_bps_mid: float = 5.0
    base_bps_small: float = 8.0
    gap_penalty_factor: float = 0.5


@dataclass(frozen=True)
class PMSConfig:
    """利润保护配置 (镜像 `engines.backtest.config.PMSConfig`, frozen + hashable).

    engines 版本用 `list[tuple[float, float]]` tiers, Platform 改用
    `tuple[tuple[float, float], ...]` 保 frozen/hashable. C4 Runner fallback
    转换为 engines list 供 engine 使用.

    Args:
      enabled: 是否启用 PMS
      tiers: (pnl_threshold, trailing_stop) 元组序列, 按 pnl 从高到低排列
             默认 ((0.30, 0.15), (0.20, 0.12), (0.10, 0.10)): 3 层阶梯
      exec_mode: "next_open" (T+1 开盘卖, 保守) | "same_close" (当日收盘卖, 乐观)
    """

    enabled: bool = False
    tiers: tuple[tuple[float, float], ...] = (
        (0.30, 0.15),
        (0.20, 0.12),
        (0.10, 0.10),
    )
    exec_mode: str = "next_open"


@dataclass(frozen=True)
class BacktestConfig:
    """回测配置 — 可序列化, hash 稳定 (用于 regression_test 锚点).

    MVP 2.3 Sub3 C1 扩 12 字段 + 3 嵌套 value object, 消除 Sub1 PR C3 `engine_config_builder`
    callable 绕 5-field fallback 的技术债. 默认值严格对齐 `engines.backtest.config.BacktestConfig`
    保 17 现有调用方 0 break. 新字段加入 config_hash 会破历史 cache, 但 LIVE_PT 不 cache
    + regression_test 守 `max_diff=0` 双保险.

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
      capital: 初始资本 (Decimal 序列化字符串)
      benchmark: 基准 ("csi300" / "none")
      extra: 扩展参数 (FUTURE-PROOF)
      turnover_cap: 单次换手率上限 (Sub3 C1)
      commission_rate: 佣金费率 (Sub3 C1, 默认国金万 0.854)
      stamp_tax_rate: 印花税率 (Sub3 C1, 默认千 0.5, historical_stamp_tax=True 覆盖)
      historical_stamp_tax: 启用历史税率 (Sub3 C1, 2023-08-28 前 0.1%, 后 0.05%)
      transfer_fee_rate: 过户费率 (Sub3 C1, 默认万 0.1)
      slippage_bps: 基础滑点 (bps, fixed 模式用) (Sub3 C1)
      slippage_mode: "volume_impact" | "fixed" (Sub3 C1)
      volume_cap_pct: 单笔成交额上限占当日成交额比例 (Sub3 C1)
      lot_size: A 股最小交易单位 (100 股) (Sub3 C1)
      universe_filter: 股票池过滤规则 (Sub3 C1, ST/BJ/suspended/new-stock)
      slippage_config: 三因素滑点配置 (Sub3 C1, 镜像 engines SlippageConfig)
      pms_config: 利润保护配置 (Sub3 C1, 镜像 engines PMSConfig)
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
    # ── Sub3 C1 扩字段 (对齐 engines.backtest.config.BacktestConfig 默认值) ──
    turnover_cap: float = 0.50
    commission_rate: float = 0.0000854
    stamp_tax_rate: float = 0.0005
    historical_stamp_tax: bool = True
    transfer_fee_rate: float = 0.00001
    slippage_bps: float = 10.0
    slippage_mode: str = "volume_impact"
    volume_cap_pct: float = 0.10
    lot_size: int = 100
    universe_filter: UniverseFilter = field(default_factory=UniverseFilter)
    slippage_config: SlippageConfig = field(default_factory=SlippageConfig)
    pms_config: PMSConfig = field(default_factory=PMSConfig)


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
      lineage_id: data_lineage.lineage_id FK (MVP 2.3 U3 追溯, nullable 向后兼容).
                  DBBacktestRegistry.log_run 通过 DataPipeline.ingest(lineage=...)
                  自动生成 + 回填. 老 17 调用方默认 None 不受影响.
      engine_artifacts: 瞬态 dict, cache-miss 真跑时由 PlatformBacktestRunner 注入
                  ``{"engine_result": <engines.backtest.types.BacktestResult>,
                   "price_data": <pd.DataFrame>}``. cache-hit (DB round-trip) 永远 None.
                  消费者 (e.g. ``scripts/run_backtest.py``) 从中取 daily_nav / trades
                  走 ``engines.metrics.generate_report`` 出完整报告.
                  **永不持久化** — DBBacktestRegistry 只落 metrics DECIMAL 列.
                  ``field(compare=False, repr=False)`` 防 __eq__/repr 被大 pandas 对象污染.
                  MVP 2.3 PR C2 新增 (2026-04-19), 老 18 调用方默认 None 向后兼容.

                  **序列化禁忌** (reviewer P2): 本字段含 pandas Series/DataFrame
                  (非 JSON-safe), 任何 ``dataclasses.asdict(result)`` / 推送到
                  JSON 序列化管道必 raise TypeError. 生产路径只该用 ``result.metrics``
                  (dict[str, float/int]) 和 DECIMAL 列. 消费者如需持久化 NAV, 走独立
                  parquet 落盘, 不借 artifacts 链路.

                  **浅拷贝隔离** (reviewer P1): ``__post_init__`` 对入参 dict 做
                  ``dict(...)`` 浅拷贝, 防消费者 ``result.engine_artifacts["engine_result"] = None``
                  污染 Runner 内部引用 (frozen=True 只防重新赋 ``result.engine_artifacts=...``,
                  不防 dict 内容修改). 内部 pandas 对象仍共享, 调用方不得原地 mutate.
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
    lineage_id: UUID | None = None
    engine_artifacts: dict[str, Any] | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        """Shallow-copy engine_artifacts dict 防消费者 mutation 污染内部引用 (PR C2 review P1).

        frozen=True 只防 ``result.engine_artifacts = None`` 重新赋值, 不防
        ``result.engine_artifacts["key"] = value`` 原地修改. 浅拷贝外层 dict 隔离消费者
        对 Runner 内部引用的无意 mutation. ``engine_result`` / ``price_data`` 自身仍
        共享 (成本/收益不划算深拷贝), 消费者契约是"只读".
        """
        if self.engine_artifacts is not None:
            # frozen=True 阻止 self.engine_artifacts = ..., 用 object.__setattr__ 绕.
            object.__setattr__(self, "engine_artifacts", dict(self.engine_artifacts))


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
        *,
        mode: Any | None = None,
        elapsed_sec: int | None = None,
        lineage: Any | None = None,
        perf: Any | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> UUID | None:
        """记录一次运行.

        PR C2 review P1 fix: 抽象契约扩 keyword-only args 对齐 PR B 以来 Runner 实际
        调用模式. 原 3-arg abstract + concretes 扩签名导致 ``# type: ignore[override]``
        散落 (见 DBBacktestRegistry + InMemoryBacktestRegistry), 两处都绕过 mypy LSP
        检查. 修正抽象签名后 concretes 无需 ``type: ignore``.

        Args:
          config: 回测配置
          result: 结果指标
          artifact_paths: parquet / json 文件路径 (nav / holdings / metrics, 当前 PR B 暂不处理)
          mode: BacktestMode (QUICK_1Y / FULL_5Y / ...) — 记录 backtest_run.mode 列
          elapsed_sec: 回测耗时 (秒), registry 落 DB elapsed_sec 列
          lineage: MVP 2.2 U3 血缘记录 (Lineage dataclass), DBBacktestRegistry 写 data_lineage
                   表并回填 lineage_id; InMem 忽略
          perf: engines.metrics.PerformanceReport (DECIMAL 列源头); InMem 忽略
          start_date / end_date: 实际回测窗口 (mode override 后的最终日期)

        Returns:
          lineage_id (UUID) 若 lineage 传入且 write 成功; None 若 lineage=None
          或 lineage 写入失败 (fail-safe, backtest_run 行仍落盘), 或 InMem concrete.
          MVP 2.3 PR B review P1-D + PR C2 review P1 修订.
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
