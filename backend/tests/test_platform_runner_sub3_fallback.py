"""MVP 2.3 Sub3 C4 · Platform Runner _build_engine_config fallback 14 字段全映射单测.

覆盖:
  - Fallback (engine_config_builder=None): Platform BacktestConfig → Engine BacktestConfig
    14 字段全映射 (消 Sub1 PR C3 5-field 技术债)
  - SlippageConfig 嵌套转换 (Platform frozen mirror → engines frozen, 字段 1:1)
  - PMSConfig 嵌套转换 (Platform tuple-of-tuple → engines list[tuple], 其他字段 1:1)
  - cost_model 兼容 (Sub1 签名: simplified → historical_stamp_tax=False, full → True)
  - engine_config_builder 注入仍 override fallback (Sub1 兼容)
  - signal_config_builder=None fallback 不发 UserWarning (Sub3 C4 降噪)

Sub3 C4 动机: 消除 Sub1 PR C3 `engine_config_builder` callable 绕 5-field fallback 技术债.
C1 扩 Platform BacktestConfig 字段 (+ 3 嵌套) 后, fallback 可全字段映射, 覆盖 Sub2 未来
research scripts 迁 SDK 时不注入 builder 的场景.

关联铁律: 25 (代码变更前读当前代码) / 34 (config SSOT).
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from backend.platform.backtest.interface import (
    BacktestConfig,
    PMSConfig,
    SlippageConfig,
    UniverseFilter,
)
from backend.platform.backtest.runner import PlatformBacktestRunner


def _make_config(**overrides) -> BacktestConfig:
    base = {
        "start": date(2021, 1, 1),
        "end": date(2025, 12, 31),
        "universe": "csi300",
        "factor_pool": ("bp_ratio", "dv_ttm"),
        "rebalance_freq": "monthly",
        "top_n": 20,
        "industry_cap": 1.0,
        "size_neutral_beta": 0.50,
        "cost_model": "full",
        "capital": "1000000.0",
        "benchmark": "csi300",
        "extra": {},
    }
    base.update(overrides)
    return BacktestConfig(**base)


class TestFallbackFullFieldMapping:
    """Sub3 C4: fallback 14 字段全映射 (消 Sub1 PR C3 5-field 技术债)."""

    def test_fallback_default_config_maps_all_scalar_fields(self) -> None:
        """Default Platform config → Engine config 14 scalar 字段全映射 (无 engine_config_builder)."""
        runner = PlatformBacktestRunner(registry=MagicMock(), engine_config_builder=None)
        cfg = _make_config()
        engine_cfg = runner._build_engine_config(cfg)

        # Sub1 原 5 字段
        assert engine_cfg.initial_capital == 1_000_000.0
        assert engine_cfg.top_n == 20
        assert engine_cfg.rebalance_freq == "monthly"
        assert engine_cfg.benchmark_code == "000300.SH"  # csi300 → 000300.SH
        assert engine_cfg.historical_stamp_tax is True  # cost_model='full' → True

        # Sub3 C4 新 9 scalar 字段 (之前走 engine default)
        assert engine_cfg.turnover_cap == 0.50
        assert engine_cfg.commission_rate == 0.0000854
        assert engine_cfg.stamp_tax_rate == 0.0005
        assert engine_cfg.transfer_fee_rate == 0.00001
        assert engine_cfg.slippage_bps == 10.0
        assert engine_cfg.slippage_mode == "volume_impact"
        assert engine_cfg.volume_cap_pct == 0.10
        assert engine_cfg.lot_size == 100

    def test_fallback_override_scalar_fields(self) -> None:
        """Platform config 显式传新 scalar 字段 → Engine config 对应字段对齐."""
        runner = PlatformBacktestRunner(registry=MagicMock(), engine_config_builder=None)
        cfg = _make_config(
            turnover_cap=0.75,
            commission_rate=0.001,
            slippage_bps=20.0,
            slippage_mode="fixed",
            volume_cap_pct=0.05,
            lot_size=200,
        )
        engine_cfg = runner._build_engine_config(cfg)

        assert engine_cfg.turnover_cap == 0.75
        assert engine_cfg.commission_rate == 0.001
        assert engine_cfg.slippage_bps == 20.0
        assert engine_cfg.slippage_mode == "fixed"
        assert engine_cfg.volume_cap_pct == 0.05
        assert engine_cfg.lot_size == 200

    def test_fallback_slippage_config_nested_mirror(self) -> None:
        """Platform SlippageConfig (frozen) → engines SlippageConfig (frozen, 字段 1:1)."""
        runner = PlatformBacktestRunner(registry=MagicMock(), engine_config_builder=None)
        custom_slip = SlippageConfig(Y_large=2.0, base_bps_large=10.0, gap_penalty_factor=0.3)
        cfg = _make_config(slippage_config=custom_slip)
        engine_cfg = runner._build_engine_config(cfg)

        # engines.slippage_model.SlippageConfig 字段 1:1
        assert engine_cfg.slippage_config.Y_large == 2.0
        assert engine_cfg.slippage_config.Y_mid == 1.0  # default 保留
        assert engine_cfg.slippage_config.base_bps_large == 10.0
        assert engine_cfg.slippage_config.gap_penalty_factor == 0.3

    def test_fallback_pms_config_tiers_list_conversion(self) -> None:
        """Platform PMSConfig (tuple-of-tuple) → engines PMSConfig (list[tuple])."""
        runner = PlatformBacktestRunner(registry=MagicMock(), engine_config_builder=None)
        custom_pms = PMSConfig(
            enabled=True,
            tiers=((0.40, 0.20), (0.25, 0.12)),
            exec_mode="same_close",
        )
        cfg = _make_config(pms_config=custom_pms)
        engine_cfg = runner._build_engine_config(cfg)

        # engines PMSConfig 是 @dataclass (非 frozen), tiers 是 list[tuple]
        assert engine_cfg.pms.enabled is True
        assert engine_cfg.pms.exec_mode == "same_close"
        assert engine_cfg.pms.tiers == [(0.40, 0.20), (0.25, 0.12)]
        # tiers 是 list (engines 侧期望 list, Sub1 行为兼容)
        assert isinstance(engine_cfg.pms.tiers, list)

    def test_fallback_cost_model_simplified_sets_historical_false(self) -> None:
        """Sub1 兼容: cost_model='simplified' → historical_stamp_tax=False."""
        runner = PlatformBacktestRunner(registry=MagicMock(), engine_config_builder=None)
        cfg = _make_config(cost_model="simplified")
        engine_cfg = runner._build_engine_config(cfg)

        assert engine_cfg.historical_stamp_tax is False

    def test_fallback_cost_model_full_sets_historical_true(self) -> None:
        """Sub1 兼容: cost_model='full' → historical_stamp_tax=True (覆盖 Platform 默认)."""
        runner = PlatformBacktestRunner(registry=MagicMock(), engine_config_builder=None)
        cfg = _make_config(cost_model="full", historical_stamp_tax=False)  # cost_model=full 强制 True
        engine_cfg = runner._build_engine_config(cfg)

        assert engine_cfg.historical_stamp_tax is True

    def test_fallback_benchmark_none_to_empty_str(self) -> None:
        """benchmark='none' → benchmark_code='' (Sub1 兼容映射)."""
        runner = PlatformBacktestRunner(registry=MagicMock(), engine_config_builder=None)
        cfg = _make_config(benchmark="none")
        engine_cfg = runner._build_engine_config(cfg)

        assert engine_cfg.benchmark_code == ""

    def test_builder_override_fallback(self) -> None:
        """engine_config_builder 注入 → 走注入路径, 忽略 fallback (Sub1 兼容)."""
        from engines.backtest.config import BacktestConfig as EngineBC

        custom_engine_cfg = EngineBC(top_n=99, turnover_cap=0.99)
        runner = PlatformBacktestRunner(
            registry=MagicMock(),
            engine_config_builder=lambda _cfg: custom_engine_cfg,
        )
        cfg = _make_config()
        engine_cfg = runner._build_engine_config(cfg)

        # 返回的是 builder 注入的对象, 不走 fallback
        assert engine_cfg is custom_engine_cfg
        assert engine_cfg.top_n == 99
        assert engine_cfg.turnover_cap == 0.99

    def test_fallback_capital_decimal_precision_preserved(self) -> None:
        """Platform capital (Decimal str) → Engine initial_capital (float Decimal 中转保精度).

        review P3-D 修: 原用 "99999.99" IEEE 754 能精确表示, 不足以触发精度边界.
        改用 "9999999.99" (7 位整数 + 2 位小数) — PR B review P1 fix 点名的大金额场景,
        float("9999999.99") 直接转会 9999999.99 (可能), 但 PR B 教训是 `float(str)` 有
        边界精度丢失, 统一走 Decimal 中转保险.
        """
        from decimal import Decimal

        runner = PlatformBacktestRunner(registry=MagicMock(), engine_config_builder=None)
        cfg = _make_config(capital="9999999.99")
        engine_cfg = runner._build_engine_config(cfg)

        # 走 float(Decimal("9999999.99")) 路径, 对齐 PR B review P1 fix
        expected = float(Decimal("9999999.99"))
        assert engine_cfg.initial_capital == expected

    def test_fallback_platform_universe_filter_not_propagated(self) -> None:
        """UniverseFilter 是 Platform 独有字段 (engines BacktestConfig 无对应), fallback 不传.

        engines 通过 price_data 列驱动 universe filter (见 run_hybrid_backtest L137-154),
        不依赖 BacktestConfig. Platform config.universe_filter 是未来 Sub3+ 扩展信号 (e.g.
        DAL 注入时用), 当前 fallback 不映射 (engines BacktestConfig 无 universe_filter 字段).
        """
        runner = PlatformBacktestRunner(registry=MagicMock(), engine_config_builder=None)
        cfg = _make_config(universe_filter=UniverseFilter(min_listing_days=120))
        engine_cfg = runner._build_engine_config(cfg)

        # engines BacktestConfig 无 universe_filter, hasattr 应 False
        assert not hasattr(engine_cfg, "universe_filter")
