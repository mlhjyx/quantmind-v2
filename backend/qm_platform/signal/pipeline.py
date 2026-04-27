"""Framework #6 Signal — PlatformSignalPipeline concrete (MVP 3.3 批 1).

铁律 16 唯一信号路径: 内部调 `engines.signal_engine` 现有 `SignalComposer` +
`PortfolioBuilder` + `apply_size_neutral`, **不重写**. 本类是 SDK 公共入口
wrapper, 为 multi-strategy daily_pipeline (MVP 3.3 批 2 OrderRouter) 铺路.

## 两条入口

1. `compose(factor_pool, trade_date, ctx)`: research/backtest 路径 — 因子池直合成,
   调用方无 Strategy 对象 (e.g. ad-hoc 因子池研究 / 历史回测因子组合枚举).
2. `generate(strategy, ctx)`: 生产 PT 路径 — 委 `Strategy.generate_signals(ctx)`,
   Strategy 自身知道 factor_pool 与 strategy_id.

## 架构决策 (铁律 39 显式)

- **不重写 signal_engine 内部逻辑**: regression `regression_test --years 5`
  max_diff=0 锚点依赖 `SignalComposer.compose` + `PortfolioBuilder.build` bit-identical.
- **`compose()` 沿用 PAPER_TRADING_CONFIG SSOT**: 仅 `factor_names` 由调用方覆盖
  (SignalConfig.factor_names ← factor_pool), 其他 (top_n / industry_cap /
  size_neutral_beta) 走 SSOT (铁律 34). 防研究路径 silently drift 偏离生产.
- **`generate()` 是 Strategy ABC SDK delegation**: thin pass-through, 仅 log +
  total_weight invariant 检查. Strategy 自身实现已组装链路 (`SignalComposer` +
  `apply_size_neutral` + `PortfolioBuilder`), 不再夹层.
- **MVP 3.3 批 1 仅交付 SDK wrapper, 不改生产入口** (铁律 23 独立可执行):
  `daily_pipeline.py` 仍直调 `engines.signal_engine`, 等批 2 OrderRouter 落地后
  再切换. 本批 regression 硬门 max_diff=0 因 production caller 不动 trivially 通过.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd
from engines.signal_engine import (
    PAPER_TRADING_CONFIG,
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
)
from engines.size_neutral import apply_size_neutral

from backend.qm_platform._types import Signal
from backend.qm_platform.signal.interface import SignalPipeline

if TYPE_CHECKING:
    from backend.qm_platform.strategy.interface import Strategy, StrategyContext

_logger = logging.getLogger(__name__)

# Sentinel strategy_id for compose() factor-pool route (no Strategy obj).
# 与 Strategy.strategy_id (UUID) 命名空间隔离防止混淆 — compose route 不入
# strategy_registry / position_snapshot, 是研究/回测专用.
_COMPOSE_STRATEGY_ID = "compose:factor_pool"

# 浮点容忍 — total_weight invariant 检查 (PortfolioBuilder 应保证 ≤ 1.0).
_TOTAL_WEIGHT_TOLERANCE = 1.0001


class FactorStaleError(RuntimeError):
    """因子数据 stale (DB max_date 落后交易日 > 1).

    本批 1 暂不实施 stale 检测 (调用方负责), 留 SDK ABI 给批 2+ 使用.
    """


class UniverseEmpty(RuntimeError):  # noqa: N818 — 语义优先 (对齐 FlagNotFound/UnsupportedColumn 项目惯例)
    """ctx.universe 空 — 调用方应预 filter 停牌/ST/BJ/新股 (load_universe)."""


class PlatformSignalPipeline(SignalPipeline):
    """SDK SignalPipeline concrete — wraps `engines.signal_engine` 纯逻辑.

    Args:
      config: SignalConfig override. None → PAPER_TRADING_CONFIG (SSOT, 铁律 34).
        生产路径强烈推荐传 None 或 PAPER_TRADING_CONFIG, 防 config drift.

    Usage:
      >>> pipe = PlatformSignalPipeline()
      >>> # research 路径 (因子池直合成):
      >>> signals = pipe.compose(["bp_ratio", "dv_ttm"], date.today(), ctx)
      >>> # 生产路径 (Strategy ABC delegation):
      >>> signals = pipe.generate(s1_monthly_ranking, ctx)
    """

    def __init__(self, config: SignalConfig | None = None) -> None:
        self._base_config = config or PAPER_TRADING_CONFIG

    @property
    def base_config(self) -> SignalConfig:
        """Read-only access to base SignalConfig (test 用)."""
        return self._base_config

    # ─── compose: factor-pool 直合成 (research/backtest 路径) ────────

    def compose(
        self,
        factor_pool: list[str],
        trade_date: date,
        ctx: StrategyContext,
    ) -> list[Signal]:
        """因子池 → composite score → Top-N → list[Signal].

        Args:
          factor_pool: 因子名列表 (覆盖 base_config.factor_names, 其他 config 沿 SSOT).
          trade_date: 信号生成日 (写入 Signal.trade_date).
          ctx: StrategyContext, 提供 universe / metadata. metadata 必含
            'factor_df' (DataFrame[code, factor_name, neutral_value]) 和
            'industry_map' (dict[code, industry_sw1]). 可选: 'ln_mcap' (Series),
            'prev_holdings' (dict), 'exclude' (set), 'vol_regime_scale' (float),
            'volatility_map' (dict).

        Returns:
          Signal 列表 (target portfolio, 每 entry weight > 0).
          空列表合法 (factor_df 空 / scores 空 / target 空).

        Raises:
          UniverseEmpty: ctx.universe 空 (调用方未预 filter).
          KeyError: ctx.metadata 缺 'factor_df' 或 'industry_map' (铁律 33 fail-loud).
          ValueError: factor_pool 空.
        """
        if not factor_pool:
            raise ValueError(
                "factor_pool 不能空. compose route 必须显式提供因子清单."
            )
        if not ctx.universe:
            raise UniverseEmpty(
                f"ctx.universe 空 (trade_date={trade_date}). 调用方应预 filter "
                "停牌/ST/BJ/新股 (load_universe())."
            )
        for required_key in ("factor_df", "industry_map"):
            if required_key not in ctx.metadata:
                raise KeyError(
                    f"PlatformSignalPipeline.compose: ctx.metadata 缺 "
                    f"{required_key!r}. 调用方必预加载 (铁律 31 pure-calc + 33 fail-loud)."
                )

        factor_df: pd.DataFrame = ctx.metadata["factor_df"]
        industry_map: dict[str, str] = ctx.metadata["industry_map"]
        ln_mcap: pd.Series | None = ctx.metadata.get("ln_mcap")
        prev_holdings: dict[str, float] | None = ctx.metadata.get("prev_holdings")
        exclude: set[str] | None = ctx.metadata.get("exclude")
        vol_regime_scale: float = float(ctx.metadata.get("vol_regime_scale", 1.0))
        volatility_map: dict[str, float] | None = ctx.metadata.get("volatility_map")

        if factor_df.empty:
            _logger.info(
                "compose: trade_date=%s factor_df empty -> no signals", trade_date
            )
            return []

        # SSOT 沿 base_config, 仅覆盖 factor_names (铁律 34).
        config = replace(self._base_config, factor_names=tuple(factor_pool))

        # ─── Step 1: SignalComposer.compose (铁律 16 复用) ────────
        composer = SignalComposer(config)
        scores = composer.compose(
            factor_df=factor_df,
            universe=set(ctx.universe),
            exclude=exclude,
        )
        if scores.empty:
            _logger.info(
                "compose: trade_date=%s scores empty (factor_df=%d) -> no signals",
                trade_date,
                len(factor_df),
            )
            return []

        # ─── Step 2: Size-neutral (条件应用) ────────────────────
        if config.size_neutral_beta > 0.0 and ln_mcap is not None and not ln_mcap.empty:
            pre_sn = scores
            scores = apply_size_neutral(scores, ln_mcap, config.size_neutral_beta)
            # 对齐 S1MonthlyRanking PR #71 P1 reviewer fix: 显式检测 SN no-op
            # (apply_size_neutral 对 reindex 后 all-NaN ln_mcap silently return 原 scores).
            if scores is pre_sn:
                _logger.warning(
                    "compose: size_neutral_beta=%.2f >0 but SN no-op "
                    "(apply_size_neutral 返原 scores, 可能 ln_mcap reindex all-NaN). "
                    "trade_date=%s ln_mcap=%d scores=%d",
                    config.size_neutral_beta,
                    trade_date,
                    len(ln_mcap),
                    len(scores),
                )

        # ─── Step 3: PortfolioBuilder.build (铁律 16 复用) ────────
        builder = PortfolioBuilder(config)
        industry_ser = pd.Series(industry_map, dtype=object, name="industry_sw1")
        target = builder.build(
            scores=scores,
            industry=industry_ser,
            prev_holdings=prev_holdings,
            vol_regime_scale=vol_regime_scale,
            volatility_map=volatility_map,
        )
        if not target:
            _logger.info(
                "compose: trade_date=%s target empty (scores=%d -> build no selection)",
                trade_date,
                len(scores),
            )
            return []

        # ─── Step 4: dict → list[Signal] ─────────────────────────
        signals: list[Signal] = []
        sentinel = -1.0  # 防 invariant 违反 (target.keys() ⊆ scores.index)
        for code, weight in target.items():
            raw_score = scores.get(code, sentinel)
            if raw_score == sentinel:
                _logger.error(
                    "compose: invariant violation — code=%s in target but not in scores "
                    "(target=%d scores=%d). 回退 score=0.0.",
                    code,
                    len(target),
                    len(scores),
                )
                code_score = 0.0
            else:
                code_score = float(raw_score)
            signals.append(
                Signal(
                    strategy_id=_COMPOSE_STRATEGY_ID,
                    code=code,
                    target_weight=float(weight),
                    score=code_score,
                    trade_date=trade_date,
                    metadata={
                        "action": "target",
                        "industry": industry_map.get(code, "其他"),
                        "factor_pool": list(factor_pool),
                    },
                )
            )

        _logger.info(
            "compose: trade_date=%s factors=%d universe=%d scores=%d target=%d total_w=%.4f",
            trade_date,
            len(factor_pool),
            len(ctx.universe),
            len(scores),
            len(target),
            sum(target.values()),
        )
        return signals

    # ─── generate: Strategy ABC delegation (生产 PT 路径) ────────

    def generate(
        self,
        strategy: Strategy,
        ctx: StrategyContext,
    ) -> list[Signal]:
        """委 `Strategy.generate_signals(ctx)` — Strategy ABC SDK 入口.

        Thin pass-through. Strategy 实现 (e.g. S1MonthlyRanking) 已包含
        SignalComposer + apply_size_neutral + PortfolioBuilder 完整组装链路,
        Pipeline 不再夹层 — 仅做调用 + log + total_weight invariant 检查.

        Args:
          strategy: 已注册的 Strategy 实例 (DBStrategyRegistry.register 后).
          ctx: StrategyContext, 由 daily_pipeline 调度器构造.

        Returns:
          Signal 列表 (strategy.generate_signals 原样).

        Raises:
          (透传 strategy.generate_signals 原始异常 — KeyError/DataUnavailable 等)
        """
        signals = strategy.generate_signals(ctx)
        total = sum(s.target_weight for s in signals)
        if total > _TOTAL_WEIGHT_TOLERANCE:
            _logger.warning(
                "generate: strategy=%s trade_date=%s total_weight=%.4f > 1.0 "
                "(PortfolioBuilder invariant 违反? 检查 cash_buffer / vol_regime_scale).",
                getattr(strategy, "name", strategy.strategy_id),
                ctx.trade_date,
                total,
            )
        _logger.info(
            "generate: strategy=%s trade_date=%s signals=%d total_w=%.4f",
            getattr(strategy, "name", strategy.strategy_id),
            ctx.trade_date,
            len(signals),
            total,
        )
        return signals
