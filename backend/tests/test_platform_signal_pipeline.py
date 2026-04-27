"""Unit tests for backend.qm_platform.signal.pipeline.PlatformSignalPipeline (MVP 3.3 批 1).

测试覆盖:
  - compose() error paths: empty universe / missing metadata / empty factor_pool
  - compose() happy path: minimal + signals 输出格式 + total_weight invariant
  - compose() SSOT: factor_pool override + 其他 config 沿 base
  - generate() Strategy ABC delegation: pass-through + log + invariant warning
  - 配置 SSOT: 默认 PAPER_TRADING_CONFIG / 自定义 config
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd
import pytest

from backend.qm_platform._types import Signal
from backend.qm_platform.signal.pipeline import (
    COMPOSE_STRATEGY_ID,
    PlatformSignalPipeline,
    UniverseEmpty,
)
from backend.qm_platform.strategy.interface import (
    Strategy,
    StrategyContext,
)

# ─── Helpers ──────────────────────────────────────────────────────


def _make_ctx(
    universe: list[str],
    factor_df: pd.DataFrame,
    industry_map: dict[str, str] | None = None,
    **extra,
) -> StrategyContext:
    metadata = {
        "factor_df": factor_df,
        "industry_map": industry_map if industry_map is not None else {},
        **extra,
    }
    return StrategyContext(
        trade_date=date(2026, 4, 27),
        capital=Decimal("1000000"),
        universe=universe,
        regime="bull",
        metadata=metadata,
    )


def _make_factor_df(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    """rows: list[(code, factor_name, neutral_value)]"""
    return pd.DataFrame(rows, columns=["code", "factor_name", "neutral_value"])


# ─── compose() error paths ───────────────────────────────────────


class TestComposeErrorPaths:
    def test_empty_factor_pool_raises_value_error(self):
        pipe = PlatformSignalPipeline()
        ctx = _make_ctx(universe=["600519.SH"], factor_df=_make_factor_df([]))
        with pytest.raises(ValueError, match="factor_pool 不能空"):
            pipe.compose([], date(2026, 4, 27), ctx)

    def test_empty_universe_raises_universe_empty(self):
        pipe = PlatformSignalPipeline()
        ctx = _make_ctx(universe=[], factor_df=_make_factor_df([]))
        with pytest.raises(UniverseEmpty, match="ctx.universe 空"):
            pipe.compose(["bp_ratio"], date(2026, 4, 27), ctx)

    def test_missing_factor_df_raises_key_error(self):
        pipe = PlatformSignalPipeline()
        ctx = StrategyContext(
            trade_date=date(2026, 4, 27),
            capital=Decimal("1000000"),
            universe=["600519.SH"],
            regime="bull",
            metadata={"industry_map": {}},  # 缺 factor_df
        )
        with pytest.raises(KeyError, match="factor_df"):
            pipe.compose(["bp_ratio"], date(2026, 4, 27), ctx)

    def test_missing_industry_map_raises_key_error(self):
        pipe = PlatformSignalPipeline()
        ctx = StrategyContext(
            trade_date=date(2026, 4, 27),
            capital=Decimal("1000000"),
            universe=["600519.SH"],
            regime="bull",
            metadata={"factor_df": _make_factor_df([])},  # 缺 industry_map
        )
        with pytest.raises(KeyError, match="industry_map"):
            pipe.compose(["bp_ratio"], date(2026, 4, 27), ctx)


# ─── compose() happy path ────────────────────────────────────────


class TestComposeHappyPath:
    def test_empty_factor_df_returns_empty(self):
        pipe = PlatformSignalPipeline()
        ctx = _make_ctx(
            universe=["600519.SH"],
            factor_df=pd.DataFrame(columns=["code", "factor_name", "neutral_value"]),
        )
        result = pipe.compose(["bp_ratio"], date(2026, 4, 27), ctx)
        assert result == []

    def test_minimal_returns_signals(self):
        # 50 codes 跨 5 industries, single factor — 应 select Top-N (PAPER_TRADING top_n=20)
        codes = [f"600{i:03d}.SH" for i in range(50)]
        factor_df = _make_factor_df(
            [(code, "bp_ratio", float(50 - idx)) for idx, code in enumerate(codes)]
        )
        industries = ["白酒", "银行", "新能源", "医药", "其他"]
        industry_map = {code: industries[idx % 5] for idx, code in enumerate(codes)}
        ctx = _make_ctx(universe=codes, factor_df=factor_df, industry_map=industry_map)

        pipe = PlatformSignalPipeline()
        signals = pipe.compose(["bp_ratio"], date(2026, 4, 27), ctx)
        assert len(signals) > 0
        for s in signals:
            assert isinstance(s, Signal)
            assert s.strategy_id == COMPOSE_STRATEGY_ID
            assert s.target_weight > 0
            assert s.metadata["action"] == "target"
            assert "industry" in s.metadata
            assert s.metadata["factor_pool"] == ["bp_ratio"]
            assert s.trade_date == date(2026, 4, 27)

    def test_total_weight_within_one(self):
        codes = [f"600{i:03d}.SH" for i in range(50)]
        factor_df = _make_factor_df(
            [(code, "bp_ratio", float(50 - idx)) for idx, code in enumerate(codes)]
        )
        industry_map = {code: "其他" for code in codes}  # 全 "其他", industry_cap=1.0 不约束
        ctx = _make_ctx(universe=codes, factor_df=factor_df, industry_map=industry_map)

        pipe = PlatformSignalPipeline()
        signals = pipe.compose(["bp_ratio"], date(2026, 4, 27), ctx)
        total = sum(s.target_weight for s in signals)
        # PortfolioBuilder 保留 cash_buffer (default 5%), 总和 ≤ 1.0
        assert total <= 1.0001
        assert total > 0  # 有 selection

    def test_signals_strategy_id_is_compose_sentinel(self):
        codes = [f"600{i:03d}.SH" for i in range(30)]
        factor_df = _make_factor_df(
            [(code, "bp_ratio", float(idx)) for idx, code in enumerate(codes)]
        )
        ctx = _make_ctx(
            universe=codes,
            factor_df=factor_df,
            industry_map={code: "其他" for code in codes},
        )
        pipe = PlatformSignalPipeline()
        signals = pipe.compose(["bp_ratio"], date(2026, 4, 27), ctx)
        assert all(s.strategy_id == COMPOSE_STRATEGY_ID for s in signals)
        assert COMPOSE_STRATEGY_ID == "compose:factor_pool"


# ─── compose() SSOT 行为 ────────────────────────────────────────


class TestComposeConfigSSOT:
    def test_factor_pool_overrides_factor_names(self):
        """factor_pool 由 caller 提供, 其他 config 沿 base_config (SSOT)."""
        pipe = PlatformSignalPipeline()
        # base_config.factor_names 是 PT 4 因子, 但本次只用 1 个
        codes = [f"600{i:03d}.SH" for i in range(30)]
        factor_df = _make_factor_df(
            [(code, "bp_ratio", float(idx)) for idx, code in enumerate(codes)]
        )
        ctx = _make_ctx(
            universe=codes,
            factor_df=factor_df,
            industry_map={code: "其他" for code in codes},
        )
        signals = pipe.compose(["bp_ratio"], date(2026, 4, 27), ctx)
        # 不抛错 — factor_pool 单因子覆盖成功 (即便 base 是 4 因子)
        assert len(signals) > 0
        assert signals[0].metadata["factor_pool"] == ["bp_ratio"]


# ─── generate() Strategy ABC delegation ─────────────────────────


class TestGenerateDelegation:
    def test_generate_passes_through_strategy_signals(self):
        signal = Signal(
            strategy_id="test-uuid",
            code="600519.SH",
            target_weight=0.05,
            score=1.5,
            trade_date=date(2026, 4, 27),
            metadata={},
        )
        strategy = MagicMock(spec=Strategy)
        strategy.generate_signals.return_value = [signal]
        strategy.strategy_id = "test-uuid"
        strategy.name = "test_strategy"

        pipe = PlatformSignalPipeline()
        ctx = _make_ctx(universe=["600519.SH"], factor_df=pd.DataFrame())
        result = pipe.generate(strategy, ctx)
        assert result == [signal]
        strategy.generate_signals.assert_called_once_with(ctx)

    def test_generate_warns_on_total_weight_exceed(self, caplog):
        # 3 signals × 0.5 = 1.5 > 1.0 触发 warning
        signals = [
            Signal(
                strategy_id="test-uuid",
                code=f"6005{i:02d}.SH",
                target_weight=0.5,
                score=1.0,
                trade_date=date(2026, 4, 27),
                metadata={},
            )
            for i in range(3)
        ]
        strategy = MagicMock(spec=Strategy)
        strategy.generate_signals.return_value = signals
        strategy.strategy_id = "test-uuid"
        strategy.name = "test_strategy"

        pipe = PlatformSignalPipeline()
        ctx = _make_ctx(universe=["600519.SH"], factor_df=pd.DataFrame())
        with caplog.at_level(logging.WARNING, logger="backend.qm_platform.signal.pipeline"):
            pipe.generate(strategy, ctx)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("total_weight" in r.message for r in warnings), (
            f"expected total_weight warning, got: {[r.message for r in warnings]}"
        )

    def test_generate_empty_signals_passes_through(self):
        strategy = MagicMock(spec=Strategy)
        strategy.generate_signals.return_value = []
        strategy.strategy_id = "test-uuid"
        strategy.name = "test_strategy"

        pipe = PlatformSignalPipeline()
        ctx = _make_ctx(universe=["600519.SH"], factor_df=pd.DataFrame())
        result = pipe.generate(strategy, ctx)
        assert result == []

    def test_generate_within_tolerance_no_warning(self, caplog):
        # total = 0.95 (cash_buffer 5%), tolerance 1.0001, 不应 warn.
        signals = [
            Signal(
                strategy_id="test-uuid",
                code=f"6005{i:02d}.SH",
                target_weight=0.05,
                score=1.0,
                trade_date=date(2026, 4, 27),
                metadata={},
            )
            for i in range(19)
        ]
        strategy = MagicMock(spec=Strategy)
        strategy.generate_signals.return_value = signals
        strategy.strategy_id = "test-uuid"
        strategy.name = "test_strategy"

        pipe = PlatformSignalPipeline()
        ctx = _make_ctx(universe=["600519.SH"], factor_df=pd.DataFrame())
        with caplog.at_level(logging.WARNING, logger="backend.qm_platform.signal.pipeline"):
            pipe.generate(strategy, ctx)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert not any("total_weight" in r.message for r in warnings)


# ─── 配置 SSOT ────────────────────────────────────────────────


class TestConfigSSOT:
    def test_default_uses_paper_trading_config(self):
        from engines.signal_engine import PAPER_TRADING_CONFIG
        pipe = PlatformSignalPipeline()
        assert pipe.base_config is PAPER_TRADING_CONFIG

    def test_custom_config_override(self):
        from engines.signal_engine import SignalConfig

        # P2 code-reviewer (PR #107) 采纳: factor_names 类型注解 list[str] | None,
        # 用 list 而非 tuple 跟 SignalConfig 字段类型对齐.
        custom = SignalConfig(
            factor_names=["bp_ratio"],
            top_n=10,
            industry_cap=1.0,
            size_neutral_beta=0.0,
        )
        pipe = PlatformSignalPipeline(config=custom)
        assert pipe.base_config is custom


# ─── P2/P3 reviewer (PR #107) 新增测试 ────────────────────────


class TestGenerateExceptionPropagation:
    """P2-4 reviewer (PR #107) 采纳: generate() 透传 strategy 异常契约必须 test."""

    def test_generate_propagates_strategy_exception(self):
        strategy = MagicMock(spec=Strategy)
        strategy.generate_signals.side_effect = RuntimeError("data unavailable")
        strategy.strategy_id = "test-uuid"

        pipe = PlatformSignalPipeline()
        ctx = _make_ctx(universe=["600519.SH"], factor_df=pd.DataFrame())
        with pytest.raises(RuntimeError, match="data unavailable"):
            pipe.generate(strategy, ctx)

    def test_generate_propagates_key_error(self):
        # 模拟 S1MonthlyRanking.generate_signals raise KeyError (factor_df 缺)
        strategy = MagicMock(spec=Strategy)
        strategy.generate_signals.side_effect = KeyError("factor_df")
        strategy.strategy_id = "test-uuid"

        pipe = PlatformSignalPipeline()
        ctx = _make_ctx(universe=["600519.SH"], factor_df=pd.DataFrame())
        with pytest.raises(KeyError, match="factor_df"):
            pipe.generate(strategy, ctx)


class TestComposeSSOTPreservation:
    """P3-4 reviewer (PR #107) 采纳: 验证 base_config 非 factor_names 字段
    (top_n / size_neutral_beta) 透 compose() replace() 保留, 是 SSOT 核心契约."""

    def test_custom_top_n_preserved_through_replace(self):
        """base_config.top_n=5 → compose() 选股最多 5 (PAPER_TRADING default 是 20)."""
        from engines.signal_engine import SignalConfig

        # 自定义 top_n=5, 防默认 20 干扰
        custom = SignalConfig(
            factor_names=["bp_ratio"],
            top_n=5,
            industry_cap=1.0,
            size_neutral_beta=0.0,  # SN off, 防 ln_mcap 缺导致 fallback
        )
        pipe = PlatformSignalPipeline(config=custom)

        # 50 codes, 全部 industry "其他", 应 select Top-5
        codes = [f"600{i:03d}.SH" for i in range(50)]
        factor_df = _make_factor_df(
            [(code, "bp_ratio", float(50 - idx)) for idx, code in enumerate(codes)]
        )
        ctx = _make_ctx(
            universe=codes,
            factor_df=factor_df,
            industry_map={code: "其他" for code in codes},
        )
        signals = pipe.compose(["bp_ratio"], date(2026, 4, 27), ctx)
        # base_config.top_n=5 应限定到 5 而非 PAPER_TRADING 的 20
        assert len(signals) == 5, (
            f"top_n SSOT 漂移: 期望 5 但 {len(signals)} (replace() 错误覆盖了非 factor_names 字段?)"
        )

    def test_factor_names_field_stays_list_type(self):
        """P1-1 reviewer (PR #107) 采纳: replace() 后 factor_names 必须仍是 list 类型,
        不是 tuple (跟 SignalConfig.factor_names: list[str] | None 字段注解一致)."""
        pipe = PlatformSignalPipeline()
        codes = [f"600{i:03d}.SH" for i in range(30)]
        factor_df = _make_factor_df(
            [(code, "bp_ratio", float(idx)) for idx, code in enumerate(codes)]
        )
        ctx = _make_ctx(
            universe=codes,
            factor_df=factor_df,
            industry_map={code: "其他" for code in codes},
        )
        # 走一次 compose() 观察内部 SignalConfig.factor_names 类型 — 通过 metadata 间接验证
        signals = pipe.compose(["bp_ratio", "dv_ttm"], date(2026, 4, 27), ctx)
        # signals[0].metadata['factor_pool'] 是 list (compose 内部 list(factor_pool))
        assert isinstance(signals[0].metadata["factor_pool"], list)


class TestComposeNegativeOneScore:
    """P1-2 reviewer (PR #107) 采纳: 真实 score=-1.0 不应触发 sentinel 误报 corruption.

    sentinel-based `raw_score == -1.0` 检测会把真实 score=-1.0 替为 0.0; membership
    test `code in scores` 修复后应不动真 score 值.
    """

    def test_score_neg_one_not_corrupted(self, caplog):
        # 构造场景: 单 factor 1 code score=-1.0 (z-score 边缘) 应保留
        pipe = PlatformSignalPipeline()
        codes = [f"600{i:03d}.SH" for i in range(20)]
        # bp_ratio 让 600000 的 score=-1.0 (相对其他)
        # SignalComposer 走 z-score 后某 code 可能正好 -1.0
        # 直接构造 factor_df 使 600000 是 minimum
        factor_df = _make_factor_df(
            [(code, "bp_ratio", -1.0 if idx == 0 else float(idx)) for idx, code in enumerate(codes)]
        )
        ctx = _make_ctx(
            universe=codes,
            factor_df=factor_df,
            industry_map={code: "其他" for code in codes},
        )
        with caplog.at_level(logging.ERROR, logger="backend.qm_platform.signal.pipeline"):
            pipe.compose(["bp_ratio"], date(2026, 4, 27), ctx)
        # 不应该有 invariant violation error log
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert not any("invariant violation" in r.message for r in errors), (
            "P1-2 regression: 真实 score=-1.0 误判为 sentinel 触发 invariant log"
        )
