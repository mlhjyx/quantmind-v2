"""Unit tests for run_paper_trading.py SDK parity dual-run helpers (MVP 3.3 batch 2 Step 2).

测试覆盖:
  - _build_sdk_strategy_context: pure function ctx 构造
  - industry pd.Series → dict 转换
  - universe set → list 转换
  - ln_mcap None / 提供 两种路径
  - StrategyContext 字段完整性 (S1MonthlyRanking metadata 契约)
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

# scripts/ 目录加到 path 防 conftest 顺序导致的 ImportError
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

# 导入 run_paper_trading 会触发其 module-top imports (Settings 等),
# 但只调 helper 函数, 不实际启动 PT.
from run_paper_trading import _build_sdk_strategy_context  # noqa: E402

# ─── Helpers ────────────────────────────────────────────────


def _make_factor_df(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["code", "factor_name", "neutral_value"])


# ─── _build_sdk_strategy_context ─────────────────────────────


class TestBuildContextBasic:
    def test_returns_strategy_context_instance(self):
        from backend.qm_platform.strategy.interface import StrategyContext

        ctx = _build_sdk_strategy_context(
            trade_date=date(2026, 4, 27),
            factor_df=_make_factor_df([("600519.SH", "bp_ratio", 1.0)]),
            universe={"600519.SH"},
            industry=pd.Series({"600519.SH": "白酒"}),
            capital=Decimal("1000000"),
        )
        assert isinstance(ctx, StrategyContext)

    def test_trade_date_preserved(self):
        ctx = _build_sdk_strategy_context(
            trade_date=date(2026, 4, 27),
            factor_df=_make_factor_df([]),
            universe=set(),
            industry=pd.Series(dtype=object),
            capital=Decimal("1000000"),
        )
        assert ctx.trade_date == date(2026, 4, 27)

    def test_capital_decimal_preserved(self):
        ctx = _build_sdk_strategy_context(
            trade_date=date(2026, 4, 27),
            factor_df=_make_factor_df([]),
            universe=set(),
            industry=pd.Series(dtype=object),
            capital=Decimal("999999.99"),
        )
        assert ctx.capital == Decimal("999999.99")
        assert isinstance(ctx.capital, Decimal)

    def test_regime_default(self):
        ctx = _build_sdk_strategy_context(
            trade_date=date(2026, 4, 27),
            factor_df=_make_factor_df([]),
            universe=set(),
            industry=pd.Series(dtype=object),
            capital=Decimal("1000000"),
        )
        assert ctx.regime == "default"


# ─── 类型转换: industry / universe ────────────────────────


class TestTypeConversions:
    def test_industry_pd_series_to_dict(self):
        industry = pd.Series({"600519.SH": "白酒", "000001.SZ": "银行"})
        ctx = _build_sdk_strategy_context(
            trade_date=date(2026, 4, 27),
            factor_df=_make_factor_df([]),
            universe={"600519.SH", "000001.SZ"},
            industry=industry,
            capital=Decimal("1000000"),
        )
        assert isinstance(ctx.metadata["industry_map"], dict)
        assert ctx.metadata["industry_map"]["600519.SH"] == "白酒"
        assert ctx.metadata["industry_map"]["000001.SZ"] == "银行"

    def test_universe_set_to_list(self):
        ctx = _build_sdk_strategy_context(
            trade_date=date(2026, 4, 27),
            factor_df=_make_factor_df([]),
            universe={"600519.SH", "000001.SZ"},
            industry=pd.Series(dtype=object),
            capital=Decimal("1000000"),
        )
        assert isinstance(ctx.universe, list)
        assert set(ctx.universe) == {"600519.SH", "000001.SZ"}

    def test_industry_dict_input_also_works(self):
        """Defensive: 若 caller 已传 dict (非 Series), 也能 round-trip."""
        ctx = _build_sdk_strategy_context(
            trade_date=date(2026, 4, 27),
            factor_df=_make_factor_df([]),
            universe={"600519.SH"},
            industry={"600519.SH": "白酒"},  # dict 而非 Series
            capital=Decimal("1000000"),
        )
        assert ctx.metadata["industry_map"]["600519.SH"] == "白酒"


# ─── ln_mcap 可选注入 ───────────────────────────────────


class TestLnMcap:
    def test_ln_mcap_none_default(self):
        ctx = _build_sdk_strategy_context(
            trade_date=date(2026, 4, 27),
            factor_df=_make_factor_df([]),
            universe=set(),
            industry=pd.Series(dtype=object),
            capital=Decimal("1000000"),
        )
        assert ctx.metadata["ln_mcap"] is None

    def test_ln_mcap_provided(self):
        ln_mcap = pd.Series({"600519.SH": 24.5, "000001.SZ": 23.0})
        ctx = _build_sdk_strategy_context(
            trade_date=date(2026, 4, 27),
            factor_df=_make_factor_df([]),
            universe={"600519.SH", "000001.SZ"},
            industry=pd.Series({"600519.SH": "白酒", "000001.SZ": "银行"}),
            capital=Decimal("1000000"),
            ln_mcap=ln_mcap,
        )
        assert ctx.metadata["ln_mcap"] is not None
        # 内容引用一致
        assert ctx.metadata["ln_mcap"].equals(ln_mcap)


# ─── S1MonthlyRanking metadata 契约 ─────────────────────


class TestS1MetadataContract:
    """S1MonthlyRanking.generate_signals() 要求 metadata 含 factor_df + industry_map.
    本 ctx builder 必须满足此契约 (否则 SDK dual-run 必 KeyError).
    """

    def test_factor_df_in_metadata(self):
        df = _make_factor_df([("600519.SH", "bp_ratio", 1.0)])
        ctx = _build_sdk_strategy_context(
            trade_date=date(2026, 4, 27),
            factor_df=df,
            universe={"600519.SH"},
            industry=pd.Series({"600519.SH": "白酒"}),
            capital=Decimal("1000000"),
        )
        assert "factor_df" in ctx.metadata
        assert ctx.metadata["factor_df"] is df  # ref preserved

    def test_industry_map_in_metadata(self):
        ctx = _build_sdk_strategy_context(
            trade_date=date(2026, 4, 27),
            factor_df=_make_factor_df([]),
            universe=set(),
            industry=pd.Series({"600519.SH": "白酒"}),
            capital=Decimal("1000000"),
        )
        assert "industry_map" in ctx.metadata

    def test_prev_holdings_default_none(self):
        ctx = _build_sdk_strategy_context(
            trade_date=date(2026, 4, 27),
            factor_df=_make_factor_df([]),
            universe=set(),
            industry=pd.Series(dtype=object),
            capital=Decimal("1000000"),
        )
        assert ctx.metadata["prev_holdings"] is None


# ─── Stage 2.5 STRICT 模式: SignalPathDriftError 类 ─────────


class TestSignalPathDriftError:
    """Stage 2.5: env SDK_PARITY_STRICT=true 时 DIFF 必 raise."""

    def test_signal_path_drift_error_is_runtime_error(self):
        from run_paper_trading import SignalPathDriftError
        assert issubclass(SignalPathDriftError, RuntimeError)

    def test_signal_path_drift_error_can_be_raised(self):
        from run_paper_trading import SignalPathDriftError
        with pytest.raises(SignalPathDriftError, match="DIFF"):
            raise SignalPathDriftError("[Step3-SDK-parity] DIFF test")

    def test_signal_path_drift_error_module_exported(self):
        """模块 import path 验 (SignalPathDriftError 是 public)."""
        import run_paper_trading
        assert hasattr(run_paper_trading, "SignalPathDriftError")
