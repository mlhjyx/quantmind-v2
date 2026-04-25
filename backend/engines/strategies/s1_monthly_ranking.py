"""MVP 3.2 批 2 — S1 Monthly Ranking Strategy (当前 live PT 迁移).

当前 PT 生产策略 (CORE3+dv_ttm 等权月度 Top-20 + SN b=0.50) 迁移到 Platform
Strategy ABC. 铁律 16 唯一信号路径保持 — 内部仍调现有 `SignalComposer` +
`apply_size_neutral` + `PortfolioBuilder` 三步, 本类只是 **wrapper** 符合
Platform Strategy(ABC) 契约, 为 batch 4 multi-strategy daily_pipeline 铺路.

## 架构决策 (铁律 39 显式)

- **纯计算 (铁律 31)**: 本类 `generate_signals(ctx)` 是纯函数, 不做 DB IO.
  factor_df / industry_map / ln_mcap / prev_holdings 等数据由调用方 (daily_pipeline
  batch 4) 预加载注入 `ctx.metadata`. 对齐 S2 pattern (PR #70 已 settle).

- **复用现有核心逻辑 (铁律 16)**: `SignalComposer.compose` + `apply_size_neutral` +
  `PortfolioBuilder.build` 三个核心函数**不改**, S1 只 orchestrate 调用顺序. 现有
  regression_test --years 5/12 max_diff=0 锚点依赖这些函数 bit-identical, 重写即破.

- **UUID 复用当前 live (铁律 34 SSOT)**: `strategy_id = "28fc37e5-..."` 当前 PT DB
  position_snapshot / trade_log / perf_series 257+ rows 的 strategy_id. 换 UUID 会
  orphan 所有历史. Session 33 precondition 实测 (SELECT DISTINCT strategy_id FROM
  position_snapshot WHERE execution_mode='live') 确认此 UUID 权威.

- **factor_pool = SignalConfig.factor_names 对齐**: ClassVar 存 tuple 匹配
  `_PT_FACTOR_NAMES_DEFAULT` (signal_engine.py L118), auditor.check_config_alignment
  硬拦截 drift (铁律 34). YAML 改 factors 必同步此 ClassVar + pt_live.yaml + .env,
  auditor 检出 drift 抛 ConfigDriftError.

- **SN beta 在 wrapper 内部应用**: 符合现有 runner.py L176-178 + walk_forward.py
  L190-192 + runner.py L323-325 pattern — compose→SN→build 三步. beta=0 时
  apply_size_neutral 直接返回原值 (早返支路), 零开销 (size_neutral.py L116).

## Signal 语义 (简)

- 返 Signal 列表 = target portfolio (每 code 一个 target_weight > 0).
- 未在 target 的旧持仓 = 隐式 sell (caller daily_pipeline diff prev_holdings 决定实际
  OrderRouter sell 单). 对齐 PortfolioBuilder.build() 返 dict 语义.
- 与 S2 event-driven 不同 — S2 emit 显式 sell (过期 = target_weight=0), S1 不 emit.
"""
from __future__ import annotations

import logging
from typing import ClassVar
from uuid import UUID

import pandas as pd

from backend.qm_platform._types import Signal
from backend.qm_platform.strategy.interface import (
    RebalanceFreq,
    Strategy,
    StrategyContext,
    StrategyStatus,
)
from engines.signal_engine import (
    PAPER_TRADING_CONFIG,
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
)

# P2 code/python-reviewer (PR #71) 采纳: 原 lazy import 内嵌 `generate_signals` 隐藏
# import errors + 破 smoke 铁律 10b import 时可见性. 移至 module-top.
from engines.size_neutral import apply_size_neutral

_logger = logging.getLogger(__name__)


# ─── Fixed UUID for S1 (复用当前 live position_snapshot UUID) ─────────
# 当前 PT 生产策略 UUID, 迁移必保不变以避免 orphan 257+ 历史 rows
# (Session 33 DB precondition 实测: SELECT DISTINCT strategy_id FROM position_snapshot
# WHERE execution_mode='live' = 28fc37e5-2d32-4ada-92e0-41c11a5103d0).
_S1_STRATEGY_UUID = UUID("28fc37e5-2d32-4ada-92e0-41c11a5103d0")


# ─── Factor pool (CORE3+dv_ttm, SSOT 对齐 signal_engine._PT_FACTOR_NAMES_DEFAULT) ─
# 铁律 34: 此 tuple / pt_live.yaml strategy.factors / .env / signal_engine
# _PT_FACTOR_NAMES_DEFAULT 四处必严格对齐. auditor.check_config_alignment
# 启动时硬拦截 drift (ConfigDriftError).
_S1_FACTOR_POOL: tuple[str, ...] = (
    "turnover_mean_20",
    "volatility_20",
    "bp_ratio",
    "dv_ttm",
)


class S1MonthlyRanking(Strategy):
    """MVP 3.2 批 2 — S1 Monthly Ranking Strategy (LIVE, 复用当前 PT UUID).

    纯计算 wrapper 围绕 SignalComposer + apply_size_neutral + PortfolioBuilder 三步.
    调用方 (daily_pipeline batch 4) 预加载以下 metadata:

      必需:
        - ctx.metadata['factor_df']: pd.DataFrame
          长表 columns = [code, factor_name, neutral_value] (单日截面).
          由 factor_repository.load_daily() 或 equivalent 预加载.
        - ctx.metadata['industry_map']: dict[str, str]
          {code: industry_sw1}, 行业约束 + 行业集中度检查用.

      可选:
        - ctx.metadata['ln_mcap']: pd.Series
          {code: ln_market_cap}, size_neutral 计算用. 缺失时 SN 跳过
          (beta > 0 but ln_mcap is None → fallback 返原 scores).
        - ctx.metadata['prev_holdings']: dict[str, float]
          {code: weight}, turnover_cap 约束用. 缺失时不限换手.
        - ctx.metadata['exclude']: set[str]
          ST/停牌/新股/BJ 等日期级过滤集合. 缺失时不过滤.
        - ctx.metadata['vol_regime_scale']: float (默认 1.0)
          vol_regime 仓位缩放 [0.5, 2.0]. 1.0 = 不调整.
        - ctx.metadata['volatility_map']: dict[str, float]
          risk_parity / min_variance 模式用 (默认 equal 不需).

    Usage:
      >>> s1 = S1MonthlyRanking()  # 使用 PAPER_TRADING_CONFIG 默认
      >>> ctx = StrategyContext(trade_date=date(2026, 4, 28),
      ...                       capital=Decimal("1000000"),
      ...                       universe=["600519.SH", ...],
      ...                       regime="neutral",
      ...                       metadata={"factor_df": ..., "industry_map": ...})
      >>> signals = s1.generate_signals(ctx)  # list[Signal]
    """

    # ─── Class attrs (required by Strategy ABC) ──────────────────
    # ClassVar 显式声明防子类/instance shadow (对齐 S2 PR #70 reviewer LOW 采纳)
    strategy_id: ClassVar[str] = str(_S1_STRATEGY_UUID)
    name: ClassVar[str] = "s1_monthly_ranking"
    # P1 python-reviewer (PR #71) 采纳: factor_pool 原为 mutable list 有 class-level
    # mutation 风险 (auditor 启动期校验通过后仍可被 runtime 修改). 改 tuple 不可变.
    # DBStrategyRegistry.register() L76 已 `factor_pool = list(strategy.factor_pool)`
    # 包装兼容 JSONB, tuple 无影响 (list(tuple)=list).
    # type: ignore[assignment] — Strategy ABC 声明 `list[str]`, tuple 是 Sequence
    # 子型语义兼容 (duck typing); 严格 mypy --strict 不启用本项目, 非关键.
    factor_pool: ClassVar[tuple[str, ...]] = _S1_FACTOR_POOL  # type: ignore[assignment]
    rebalance_freq: ClassVar[RebalanceFreq] = RebalanceFreq.MONTHLY
    status: ClassVar[StrategyStatus] = StrategyStatus.LIVE
    description: ClassVar[str] = (
        "S1 Monthly Ranking — CORE3+dv_ttm 等权合成 + Top-20 + SN β=0.50 + 月频调仓. "
        "当前 PT 生产策略 (WF OOS Sharpe=0.8659 2026-04-12 PASS)."
    )

    def __init__(self, config: SignalConfig | None = None) -> None:
        """Args:
          config: SignalConfig. None → 使用 PAPER_TRADING_CONFIG (从 pt_live.yaml +
            .env 自动构建, 铁律 34 SSOT).
        """
        self._config = config or PAPER_TRADING_CONFIG
        # Instance-level composer/builder 持有 config ref (config 变必重建 instance)
        self._composer = SignalComposer(self._config)
        self._builder = PortfolioBuilder(self._config)

    # ─── Strategy ABC impl ──────────────────────────────────────

    def generate_signals(self, ctx: StrategyContext) -> list[Signal]:
        """生成当日 S1 目标持仓信号 (target weights, 非 delta).

        流程 (对齐 runner.py L119-180 L268-327 pattern):
          1. Compose: SignalComposer.compose(factor_df, universe, exclude) → scores
          2. Size-neutral: apply_size_neutral(scores, ln_mcap, beta) if beta > 0
          3. Build: PortfolioBuilder.build(scores, industry, prev_holdings, ...) → target dict
          4. Convert: dict → list[Signal]

        Returns:
          Signal 列表, 每 entry target_weight > 0 (target portfolio). 空列表合法
          (scores.empty / target.empty, 例如 factor_df 空 / universe 空).

        Raises:
          KeyError: ctx.metadata 缺 'factor_df' / 'industry_map' 必需 key
            (调用方 daily_pipeline 必须预加载, fail-loud 铁律 33).
        """
        # ─── Validate metadata pre-conditions (调用方必须预加载) ──────
        for required_key in ("factor_df", "industry_map"):
            if required_key not in ctx.metadata:
                raise KeyError(
                    f"S1MonthlyRanking.generate_signals: ctx.metadata 缺 "
                    f"{required_key!r} key. daily_pipeline batch 4 调用前必须预加载 "
                    f"(铁律 31 pure-calc, 铁律 33 fail-loud)."
                )

        factor_df: pd.DataFrame = ctx.metadata["factor_df"]
        industry_map: dict[str, str] = ctx.metadata["industry_map"]
        ln_mcap: pd.Series | None = ctx.metadata.get("ln_mcap")
        prev_holdings: dict[str, float] | None = ctx.metadata.get("prev_holdings")
        exclude: set[str] | None = ctx.metadata.get("exclude")
        vol_regime_scale: float = float(ctx.metadata.get("vol_regime_scale", 1.0))
        volatility_map: dict[str, float] | None = ctx.metadata.get("volatility_map")

        # ─── Early return: empty factor_df / empty universe ──────
        # SignalComposer.compose 调 pivot_table 对 empty df (无 neutral_value 列)
        # 会 raise KeyError. 这里显式早返, 语义清晰 + 保护下游.
        if factor_df.empty or not ctx.universe:
            _logger.info(
                "S1 generate_signals: trade_date=%s empty inputs "
                "(factor_df_rows=%d universe=%d) -> no signals",
                ctx.trade_date,
                len(factor_df),
                len(ctx.universe),
            )
            return []

        # ─── Step 1: Compose (existing SignalComposer, 铁律 16) ────
        universe_set: set[str] = set(ctx.universe)
        scores = self._composer.compose(
            factor_df=factor_df,
            universe=universe_set,
            exclude=exclude,
        )

        if scores.empty:
            _logger.info(
                "S1 generate_signals: trade_date=%s scores empty (factor_df rows=%d) -> no signals",
                ctx.trade_date,
                len(factor_df),
            )
            return []

        # ─── Step 2: Size-neutral (existing apply_size_neutral, 铁律 16) ─
        if self._config.size_neutral_beta > 0.0:
            if ln_mcap is None or ln_mcap.empty:
                # ln_mcap 缺失不 raise — apply_size_neutral 设计接受 empty df fallback,
                # 但 beta > 0 却无 ln_mcap 是潜在 drift, logger.warning 暴露.
                _logger.warning(
                    "S1 generate_signals: size_neutral_beta=%.2f > 0 but ln_mcap missing, "
                    "SN skipped (fallback to raw scores). ctx.metadata['ln_mcap'] 应预加载.",
                    self._config.size_neutral_beta,
                )
            else:
                pre_sn_scores = scores
                scores = apply_size_neutral(
                    scores, ln_mcap, self._config.size_neutral_beta
                )
                # P1 code-reviewer (PR #71) 采纳: apply_size_neutral 对 all-NaN
                # ln_mcap (reindex 后 dropna df empty) 会 silently return 原 scores
                # (size_neutral.py L126-127), 违 铁律 33. 此处显式检测并 warn.
                # `is` 检查: apply_size_neutral 的 empty-df fallback 正是 `return scores`
                # (原 ref 返回), 因此 `is` 最严格识别 "SN 未生效" 情况.
                if scores is pre_sn_scores:
                    _logger.warning(
                        "S1 generate_signals: size_neutral_beta=%.2f > 0 but SN 未生效 "
                        "(apply_size_neutral 返原 scores). 可能原因: ln_mcap reindex "
                        "后 all-NaN (ln_mcap %d entries vs scores %d entries).",
                        self._config.size_neutral_beta,
                        len(ln_mcap),
                        len(scores),
                    )

        # ─── Step 3: Build portfolio (existing PortfolioBuilder, 铁律 16) ─
        # industry_map dict → pd.Series (builder 接 Series + .get fallback "其他")
        industry_ser = pd.Series(industry_map, dtype=object, name="industry_sw1")
        target: dict[str, float] = self._builder.build(
            scores=scores,
            industry=industry_ser,
            prev_holdings=prev_holdings,
            vol_regime_scale=vol_regime_scale,
            volatility_map=volatility_map,
        )

        if not target:
            _logger.info(
                "S1 generate_signals: trade_date=%s target empty (scores=%d -> build no selection)",
                ctx.trade_date,
                len(scores),
            )
            return []

        # ─── Step 4: Convert target dict → list[Signal] ────────────
        # P2 code/python-reviewer (PR #71) 采纳: 原 `scores.loc[code] if code in
        # scores.index else 0.0` 有 silent dead-branch. Invariant: target.keys() ⊆
        # scores.index (PortfolioBuilder.build selects from scores). 改 .get() +
        # logger.error 暴露 invariant 违反 (铁律 33 fail-loud 非静默 0.0).
        signals: list[Signal] = []
        missing = -1.0  # sentinel for .get() default, 验 invariant
        for code, weight in target.items():
            raw_score = scores.get(code, missing)
            if raw_score == missing:
                # Invariant 违反 — PortfolioBuilder 返 target 有 scores 无此 code
                _logger.error(
                    "S1 generate_signals: invariant violation — code=%s in target "
                    "but not in scores.index (target=%d scores=%d). 回退 score=0.0.",
                    code,
                    len(target),
                    len(scores),
                )
                code_score = 0.0
            else:
                code_score = float(raw_score)
            signals.append(
                Signal(
                    strategy_id=self.strategy_id,
                    code=code,
                    target_weight=float(weight),
                    score=code_score,
                    trade_date=ctx.trade_date,
                    metadata={
                        "action": "target",  # target portfolio entry (非 buy/sell delta)
                        "industry": industry_map.get(code, "其他"),
                    },
                )
            )

        _logger.info(
            "S1 generate_signals: trade_date=%s universe=%d scores=%d target=%d total_weight=%.4f",
            ctx.trade_date,
            len(ctx.universe),
            len(scores),
            len(target),
            sum(target.values()),
        )
        return signals

    def validate_signals(
        self, signals: list[Signal], ctx: StrategyContext
    ) -> list[Signal]:
        """Pass-through validation — 批 2 简化 (靠 ctx.universe 已 filter BJ/ST/停牌).

        未来批次 (MVP 3.3+) 可接入 Platform 公共 validator (流动性 / 涨跌停 / 最小订单额).
        保留 code ∈ universe 的防御检查, 杀 degenerate signals (target_weight<=0 剔除).
        """
        validated: list[Signal] = []
        universe_set = set(ctx.universe)
        for sig in signals:
            if sig.target_weight <= 0.0:
                _logger.warning(
                    "S1 validate_signals: skip non-positive weight signal code=%s weight=%.6f",
                    sig.code,
                    sig.target_weight,
                )
                continue
            if sig.code not in universe_set:
                _logger.warning(
                    "S1 validate_signals: skip signal code=%s not in universe (universe_size=%d)",
                    sig.code,
                    len(universe_set),
                )
                continue
            validated.append(sig)
        return validated

    # ─── Introspection helpers (debug / test) ──────────────────

    def get_config(self) -> SignalConfig:
        """Return underlying SignalConfig (test / debug only)."""
        return self._config

    def __repr__(self) -> str:
        return (
            f"S1MonthlyRanking(id={self.strategy_id}, "
            f"factors={self.factor_pool}, "
            f"top_n={self._config.top_n}, "
            f"rebalance={self.rebalance_freq.value}, "
            f"sn_beta={self._config.size_neutral_beta:.2f}, "
            f"status={self.status.value})"
        )


# ─── Module-level Helper (test + batch 4 registry boot) ──────────

def get_s1_factor_pool() -> tuple[str, ...]:
    """Expose _S1_FACTOR_POOL tuple for auditor / test drift check (铁律 34).

    用途:
      - auditor.check_config_alignment 对比此 tuple vs pt_live.yaml strategy.factors
      - tests/test_s1_monthly_ranking.py 验 ClassVar factor_pool == _S1_FACTOR_POOL
    """
    return _S1_FACTOR_POOL
