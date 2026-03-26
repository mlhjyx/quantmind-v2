"""BaseStrategy — 所有策略的抽象基类。

提供统一的策略接口，核心方法generate_signals由子类实现。
默认的compute_alpha和build_portfolio复用现有SignalComposer/PortfolioBuilder。

设计文档对照:
- DEV_BACKTEST_ENGINE.md §4.12.4: BaseStrategy接口规范
- DESIGN_V5.md §6: 7步组合构建链路
  ①Alpha Score合成 → ②排名选股(Top-N) → ③权重分配
  → ④约束调整 → ⑤换手控制 → ⑥整手处理 → ⑦最终目标持仓

信号类型分类(§6扩展):
- ranking: 排序型(因子得分排名选Top-N，如EqualWeight)
- filter: 过滤型(条件过滤，如ROE>阈值)
- event: 事件型(离散触发，如PEAD)
- modifier: 调节型(调整权重/仓位，如regime切换)
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Optional

import pandas as pd

from engines.signal_engine import (
    FACTOR_DIRECTION,
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
    get_rebalance_dates,
)

logger = logging.getLogger(__name__)


class SignalType(str, Enum):
    """信号类型分类。"""

    RANKING = "ranking"    # 排序型: 因子得分排名选Top-N
    FILTER = "filter"      # 过滤型: 条件过滤(ROE>阈值)
    EVENT = "event"        # 事件型: 离散触发(PEAD/公告)
    MODIFIER = "modifier"  # 调节型: 调整权重/仓位(regime切换)


class WeightMethod(str, Enum):
    """权重分配方案（DESIGN_V5 §6.4）。"""

    EQUAL = "equal"              # 等权 1/N
    SCORE_WEIGHTED = "score_weighted"  # Alpha加权
    RISK_PARITY = "risk_parity"  # 风险平价 (Phase 1)


class RebalanceFreq(str, Enum):
    """调仓频率。"""

    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"


@dataclass
class StrategyContext:
    """框架提供给Strategy的运行时上下文。"""

    strategy_id: str
    trade_date: date
    factor_df: pd.DataFrame  # [code, factor_name, neutral_value]
    universe: set[str]
    industry_map: dict[str, str]  # code -> industry_sw1
    prev_holdings: Optional[dict[str, float]]  # code -> weight (上期)
    conn: Any  # psycopg2连接
    total_capital: float = 0.0  # 当前总资产(用于整手计算)


@dataclass
class StrategyDecision:
    """Strategy决策输出。"""

    target_weights: dict[str, float]  # code -> weight
    is_rebalance: bool
    reasoning: str
    warnings: list[str] = field(default_factory=list)
    signal_type: SignalType = SignalType.RANKING  # 信号类型标记


@dataclass
class StrategyMeta:
    """策略元信息，用于注册和展示。"""

    name: str
    signal_type: SignalType
    supported_freqs: list[RebalanceFreq]
    supported_weights: list[WeightMethod]
    description: str = ""


class BaseStrategy(ABC):
    """所有策略基类。

    子类必须实现:
    - generate_signals: 核心方法，因子->信号->目标持仓
    - should_rebalance: 判断是否调仓日

    可选覆盖:
    - compute_alpha: 默认等权合成（复用SignalComposer）
    - build_portfolio: 默认Top-N+行业约束（复用PortfolioBuilder）
    - filter_universe: 额外Universe过滤（DEV_BACKTEST_ENGINE §4.12.4）
    - on_rebalance: 自定义调仓逻辑钩子

    属性:
    - signal_type: 信号类型分类
    - meta: 策略元信息
    """

    signal_type: SignalType = SignalType.RANKING

    def __init__(self, config: dict, strategy_id: str):
        self.config = config
        self.strategy_id = strategy_id
        self._signal_config = self._build_signal_config()
        self._validate_config()

    @abstractmethod
    def generate_signals(self, context: StrategyContext) -> StrategyDecision:
        """核心方法：因子->信号->目标持仓。"""

    @abstractmethod
    def should_rebalance(self, trade_date: date, conn: Any) -> bool:
        """判断是否调仓日。"""

    @classmethod
    def get_meta(cls) -> StrategyMeta:
        """返回策略元信息。子类可覆盖。"""
        return StrategyMeta(
            name=cls.__name__,
            signal_type=cls.signal_type,
            supported_freqs=[RebalanceFreq.MONTHLY],
            supported_weights=[WeightMethod.EQUAL],
        )

    def compute_alpha(
        self,
        factor_df: pd.DataFrame,
        universe: Optional[set[str]] = None,
    ) -> pd.Series:
        """Alpha Score合成（DESIGN_V5 §6.2）。复用SignalComposer。

        Args:
            factor_df: [code, factor_name, neutral_value] 单日截面
            universe: 可选的universe过滤

        Returns:
            pd.Series: code -> composite score, 降序排列
        """
        composer = SignalComposer(self._signal_config)
        return composer.compose(factor_df, universe)

    def build_portfolio(
        self,
        scores: pd.Series,
        industry_map: dict[str, str],
        prev_holdings: Optional[dict[str, float]] = None,
    ) -> dict[str, float]:
        """构建目标持仓权重（§6.3-§6.5）。复用PortfolioBuilder。

        Args:
            scores: 综合得分 (code -> score), 已排序
            industry_map: code -> industry_sw1
            prev_holdings: 上期持仓权重

        Returns:
            dict: {code: target_weight}
        """
        builder = PortfolioBuilder(self._signal_config)
        industry_series = pd.Series(industry_map)
        return builder.build(scores, industry_series, prev_holdings)

    def filter_universe(self, universe: set[str], context: StrategyContext) -> set[str]:
        """自定义Universe过滤（DEV_BACKTEST_ENGINE §4.12.4）。

        默认不额外过滤。子类可覆盖添加条件(如ROE>0)。

        Args:
            universe: 标准8层过滤后的Universe
            context: 运行时上下文

        Returns:
            过滤后的Universe
        """
        return universe

    def on_rebalance(
        self,
        current_holdings: dict[str, float],
        target_holdings: dict[str, float],
    ) -> dict[str, float]:
        """自定义调仓逻辑钩子（DEV_BACKTEST_ENGINE §4.12.4）。

        默认直接返回target。子类可覆盖实现:
        - 限制换手率
        - 保留强趋势股
        - max_replace限制

        Args:
            current_holdings: 当前持仓权重
            target_holdings: 目标持仓权重

        Returns:
            调整后的目标持仓权重
        """
        return target_holdings

    def _build_signal_config(self) -> SignalConfig:
        """从config dict构建SignalConfig。"""
        return SignalConfig(
            factor_names=self.config.get("factor_names", []),
            top_n=self.config.get("top_n", 15),
            weight_method=self.config.get("weight_method", "equal"),
            industry_cap=self.config.get("industry_cap", 0.25),
            rebalance_freq=self.config.get("rebalance_freq", "monthly"),
            turnover_cap=self.config.get("turnover_cap", 0.50),
        )

    def _validate_config(self) -> None:
        """验证config必要字段。子类可覆盖增加验证。"""
        required = ["factor_names", "top_n", "weight_method"]
        missing = [k for k in required if k not in self.config]
        if missing:
            raise ValueError(
                f"策略 {self.strategy_id} config缺少必要字段: {missing}"
            )
        if not self.config["factor_names"]:
            raise ValueError(
                f"策略 {self.strategy_id} factor_names不能为空"
            )
